"""Behavior tests for the local MinerU extraction wrapper."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = (
    ROOT
    / "plugins"
    / "research-tools"
    / "skills"
    / "mineru-document-extraction"
    / "scripts"
    / "run_mineru.py"
)


class MineruWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.input = self.root / "paper.pdf"
        self.input.write_bytes(b"%PDF-1.7\nsource bytes\n")
        self.output = self.root / "output"

    def run_wrapper(
        self,
        *extra_args: str,
        env: dict[str, str] | None = None,
        input_path: str | Path | None = None,
        output_path: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [
            sys.executable,
            str(WRAPPER),
            "--input",
            str(input_path if input_path is not None else self.input),
            "--output",
            str(output_path or self.output),
            *extra_args,
        ]
        run_env = os.environ.copy()
        run_env.update(env or {})
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            env=run_env,
            check=False,
        )

    def read_manifest(self, output: Path | None = None) -> dict[str, object]:
        path = (output or self.output) / "mineru-run.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def install_fake_mineru(
        self, body: str, *, version: str = "3.4.4"
    ) -> tuple[Path, dict[str, str]]:
        bin_dir = self.root / "bin"
        bin_dir.mkdir(exist_ok=True)
        executable = bin_dir / "mineru"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            "if '--version' in sys.argv:\n"
            f"    print('mineru, version {version}')\n"
            "    raise SystemExit(0)\n"
            + textwrap.dedent(body),
            encoding="utf-8",
        )
        executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
        models = self.root / "models"
        pipeline = models / "pipeline"
        vlm = models / "vlm"
        pipeline.mkdir(parents=True, exist_ok=True)
        vlm.mkdir(parents=True, exist_ok=True)
        (pipeline / "model.bin").write_bytes(b"pipeline")
        (vlm / "model.bin").write_bytes(b"vlm")
        config = self.root / "mineru.json"
        config.write_text(
            json.dumps({"models-dir": {"pipeline": str(pipeline), "vlm": str(vlm)}}),
            encoding="utf-8",
        )
        return executable, {
            "MINERU_EXECUTABLE": str(executable),
            "MINERU_TOOLS_CONFIG_JSON": str(config),
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        }

    def test_missing_runtime_writes_failure_manifest(self) -> None:
        result = self.run_wrapper(
            env={
                "MINERU_EXECUTABLE": "",
                "MINERU_UV_TOOL_DIR": str(self.root / "missing-tools"),
                "PATH": str(self.root / "missing-bin"),
            }
        )

        self.assertNotEqual(result.returncode, 0)
        manifest = self.read_manifest()
        self.assertEqual(manifest["status"], "failure")
        self.assertEqual(manifest["error"]["code"], "runtime_missing")
        self.assertEqual(manifest["source"]["sha256"], hashlib.sha256(self.input.read_bytes()).hexdigest())

    def test_path_shadow_is_ignored_and_wrong_version_is_rejected(self) -> None:
        executable, shadow_env = self.install_fake_mineru("raise SystemExit(88)")
        shadow_env.pop("MINERU_EXECUTABLE")
        shadow_env["MINERU_UV_TOOL_DIR"] = str(self.root / "missing-tools")

        shadow_result = self.run_wrapper(env=shadow_env, output_path=self.root / "shadow")

        self.assertEqual(shadow_result.returncode, 127)
        self.assertEqual(self.read_manifest(self.root / "shadow")["error"]["code"], "runtime_missing")

        _, mismatch_env = self.install_fake_mineru("raise SystemExit(88)", version="3.4.3")
        mismatch_result = self.run_wrapper(env=mismatch_env, output_path=self.root / "mismatch")

        self.assertEqual(mismatch_result.returncode, 127)
        mismatch_manifest = self.read_manifest(self.root / "mismatch")
        self.assertEqual(mismatch_manifest["error"]["code"], "runtime_version_mismatch")
        self.assertEqual(mismatch_manifest["mineru"]["version"], "3.4.3")
        self.assertTrue(executable.exists())

    def test_rejects_url_directory_and_unsupported_input(self) -> None:
        directory = self.root / "inputs"
        directory.mkdir()
        unsupported = self.root / "notes.exe"
        unsupported.write_bytes(b"not a document")

        for invalid_input, code in (
            ("https://example.com/paper.pdf", "input_url"),
            (directory, "input_not_file"),
            (unsupported, "input_unsupported"),
        ):
            with self.subTest(invalid_input=invalid_input):
                output = self.root / f"invalid-{code}"
                result = self.run_wrapper(input_path=invalid_input, output_path=output)
                self.assertNotEqual(result.returncode, 0)
                manifest = self.read_manifest(output)
                self.assertEqual(manifest["status"], "failure")
                self.assertEqual(manifest["error"]["code"], code)

    def test_rejects_one_sided_or_non_pdf_page_ranges(self) -> None:
        one_sided = self.run_wrapper("--start", "1", output_path=self.root / "one-sided")
        self.assertEqual(one_sided.returncode, 2)
        self.assertEqual(
            self.read_manifest(self.root / "one-sided")["error"]["code"],
            "invalid_pages",
        )

        office = self.root / "report.docx"
        office.write_bytes(b"fake office file")
        office_result = self.run_wrapper(
            "--start",
            "0",
            "--end",
            "0",
            input_path=office,
            output_path=self.root / "office-range",
        )
        self.assertEqual(office_result.returncode, 2)
        self.assertEqual(
            self.read_manifest(self.root / "office-range")["error"]["code"],
            "invalid_pages",
        )

    def test_rejects_git_or_vault_output_without_creating_artifacts(self) -> None:
        git_checkout = self.root / "checkout"
        (git_checkout / ".git").mkdir(parents=True)
        discovered_vault = self.root / "discovered-vault"
        (discovered_vault / ".obsidian").mkdir(parents=True)
        configured_vault = self.root / "configured-vault"
        configured_vault.mkdir()

        cases = (
            (git_checkout / "extract", {}, "Git checkout"),
            (discovered_vault / "extract", {}, "Obsidian vault"),
            (
                configured_vault / "extract",
                {"CODEX_OBSIDIAN_VAULT": str(configured_vault)},
                "Obsidian vault",
            ),
        )
        for output, env, expected in cases:
            with self.subTest(output=output):
                result = self.run_wrapper(output_path=output, env=env)
                self.assertEqual(result.returncode, 2)
                self.assertIn(expected, result.stderr)
                self.assertFalse(output.exists())

    def test_rejects_unsafe_model_config_and_model_paths(self) -> None:
        _, base_env = self.install_fake_mineru("raise SystemExit(88)")
        safe_models = json.loads(
            Path(base_env["MINERU_TOOLS_CONFIG_JSON"]).read_text(encoding="utf-8")
        )["models-dir"]
        checkout = self.root / "model-config-checkout"
        (checkout / ".git").mkdir(parents=True)
        unsafe_config = checkout / "mineru.json"
        unsafe_config.write_text(json.dumps({"models-dir": safe_models}), encoding="utf-8")

        config_env = base_env.copy()
        config_env["MINERU_TOOLS_CONFIG_JSON"] = str(unsafe_config)
        config_result = self.run_wrapper(
            env=config_env, output_path=self.root / "unsafe-config"
        )

        self.assertEqual(config_result.returncode, 2)
        self.assertEqual(
            self.read_manifest(self.root / "unsafe-config")["error"]["code"],
            "model_config_unsafe",
        )

        vault = self.root / "model-vault"
        (vault / ".obsidian").mkdir(parents=True)
        unsafe_pipeline = vault / "pipeline"
        unsafe_pipeline.mkdir()
        (unsafe_pipeline / "model.bin").write_bytes(b"pipeline")
        model_config = self.root / "unsafe-models.json"
        model_config.write_text(
            json.dumps(
                {
                    "models-dir": {
                        "pipeline": str(unsafe_pipeline),
                        "vlm": safe_models["vlm"],
                    }
                }
            ),
            encoding="utf-8",
        )
        model_env = base_env.copy()
        model_env["MINERU_TOOLS_CONFIG_JSON"] = str(model_config)

        model_result = self.run_wrapper(
            env=model_env, output_path=self.root / "unsafe-model-path"
        )

        self.assertEqual(model_result.returncode, 2)
        self.assertEqual(
            self.read_manifest(self.root / "unsafe-model-path")["error"]["code"],
            "model_config_unsafe",
        )

        cache_checkout = self.root / "cache-checkout"
        (cache_checkout / ".git").mkdir(parents=True)
        for cache_variable in ("TORCH_HOME", "HF_HUB_CACHE", "FTLANG_CACHE"):
            with self.subTest(cache_variable=cache_variable):
                cache_env = base_env.copy()
                cache_env[cache_variable] = str(cache_checkout / cache_variable.lower())
                cache_output = self.root / f"unsafe-cache-{cache_variable.lower()}"
                cache_result = self.run_wrapper(env=cache_env, output_path=cache_output)

                self.assertEqual(cache_result.returncode, 2)
                self.assertEqual(
                    self.read_manifest(cache_output)["error"]["code"],
                    "model_config_unsafe",
                )

    def test_rejects_enabled_llm_aided_remote_config(self) -> None:
        _, env = self.install_fake_mineru("raise SystemExit(88)")
        config_path = Path(env["MINERU_TOOLS_CONFIG_JSON"])
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["llm-aided-config"] = {
            "title_aided": {
                "enable": True,
                "base_url": "https://remote.example/v1",
                "api_key": "must-not-be-used",
                "model": "remote-model",
            }
        }
        config_path.write_text(json.dumps(config), encoding="utf-8")

        result = self.run_wrapper(env=env)

        self.assertEqual(result.returncode, 2)
        manifest = self.read_manifest()
        self.assertEqual(manifest["error"]["code"], "model_config_remote_features")

    def test_non_object_model_config_writes_stable_failure_manifest(self) -> None:
        _, env = self.install_fake_mineru("raise SystemExit(88)")
        Path(env["MINERU_TOOLS_CONFIG_JSON"]).write_text("[]", encoding="utf-8")

        result = self.run_wrapper(env=env)

        self.assertEqual(result.returncode, 2)
        manifest = self.read_manifest()
        self.assertEqual(manifest["status"], "failure")
        self.assertEqual(manifest["error"]["code"], "model_config_not_ready")

    def test_parse_failure_records_command_logs_and_requested_defaults(self) -> None:
        _, env = self.install_fake_mineru(
            """
            import sys
            print("Using mlx-engine for local inference")
            print("parse stdout")
            print("parse stderr", file=sys.stderr)
            raise SystemExit(7)
            """
        )

        result = self.run_wrapper(env=env)

        self.assertNotEqual(result.returncode, 0)
        manifest = self.read_manifest()
        self.assertEqual(manifest["status"], "failure")
        self.assertEqual(manifest["error"]["code"], "parse_failed")
        self.assertEqual(manifest["process"]["exit_code"], 7)
        self.assertEqual(manifest["mineru"]["version"], "3.4.4")
        self.assertEqual(manifest["mineru"]["observed_device_engine"], "mlx-engine")
        self.assertEqual(manifest["request"]["backend"], "hybrid-engine")
        self.assertEqual(manifest["request"]["effort"], "high")
        self.assertEqual(manifest["request"]["method"], "auto")
        self.assertEqual(manifest["request"]["concurrency"], 1)
        self.assertEqual(manifest["artifacts"]["logs"], ["mineru-stderr.log", "mineru-stdout.log"])
        self.assertEqual(
            (self.output / "mineru-stdout.log").read_text(),
            "Using mlx-engine for local inference\nparse stdout\n",
        )
        self.assertEqual((self.output / "mineru-stderr.log").read_text(), "parse stderr\n")
        self.assertIsInstance(manifest["timing"]["started_at"], str)
        self.assertIsInstance(manifest["timing"]["finished_at"], str)
        self.assertGreaterEqual(manifest["timing"]["duration_seconds"], 0)

    def test_malformed_output_fails_when_required_structured_artifacts_are_missing(self) -> None:
        _, env = self.install_fake_mineru(
            """
            from pathlib import Path
            import sys
            output = Path(sys.argv[sys.argv.index("--output") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / "paper.md").write_text("# extracted", encoding="utf-8")
            """
        )

        result = self.run_wrapper(env=env)

        self.assertNotEqual(result.returncode, 0)
        manifest = self.read_manifest()
        self.assertEqual(manifest["status"], "failure")
        self.assertEqual(manifest["error"]["code"], "malformed_output")
        self.assertEqual(manifest["artifacts"]["markdown"], ["paper.md"])
        self.assertEqual(manifest["artifacts"]["content_list_v2"], [])

    def test_staged_input_contains_runtime_mutation_and_preserves_source(self) -> None:
        original = self.input.read_bytes()
        _, env = self.install_fake_mineru(
            """
            from pathlib import Path
            import sys
            source = Path(sys.argv[sys.argv.index("--path") + 1])
            output = Path(sys.argv[sys.argv.index("--output") + 1])
            source.chmod(0o600)
            source.write_bytes(b"mutated by runtime")
            output.mkdir(parents=True, exist_ok=True)
            (output / "paper.md").write_text("# extracted", encoding="utf-8")
            (output / "paper_content_list_v2.json").write_text(
                '[[{"type":"paragraph","content":{},"bbox":[0,0,1,1]}]]',
                encoding="utf-8",
            )
            """
        )

        result = self.run_wrapper(env=env)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.input.read_bytes(), original)
        manifest = self.read_manifest()
        self.assertEqual(manifest["status"], "failure")
        self.assertEqual(manifest["error"]["code"], "staged_input_mutated")
        self.assertTrue(manifest["source"]["verified_unchanged"])
        self.assertTrue(manifest["source"]["staged_copy_used"])

    def test_deleted_staged_input_is_audited_after_original_recheck(self) -> None:
        original = self.input.read_bytes()
        _, env = self.install_fake_mineru(
            """
            from pathlib import Path
            import sys
            source = Path(sys.argv[sys.argv.index("--path") + 1])
            output = Path(sys.argv[sys.argv.index("--output") + 1])
            source.unlink()
            output.mkdir(parents=True, exist_ok=True)
            (output / "paper.md").write_text("# extracted", encoding="utf-8")
            """
        )

        result = self.run_wrapper(env=env)

        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.input.read_bytes(), original)
        manifest = self.read_manifest()
        self.assertEqual(manifest["error"]["code"], "staged_input_mutated")
        self.assertTrue(manifest["source"]["verified_unchanged"])
        self.assertFalse(manifest["source"]["staged_copy_verified_unchanged"])

    def test_rejects_invalid_content_list_v2_shape(self) -> None:
        _, env = self.install_fake_mineru(
            """
            from pathlib import Path
            import sys
            output = Path(sys.argv[sys.argv.index("--output") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / "paper.md").write_text("# extracted", encoding="utf-8")
            (output / "paper_content_list_v2.json").write_text("[]", encoding="utf-8")
            """
        )

        result = self.run_wrapper(env=env)

        self.assertEqual(result.returncode, 2)
        manifest = self.read_manifest()
        self.assertEqual(manifest["error"]["code"], "malformed_output")
        self.assertIn("page-grouped", manifest["error"]["message"])

    def test_rejects_invalid_root_content_type_and_symlink_artifact(self) -> None:
        _, invalid_env = self.install_fake_mineru(
            """
            from pathlib import Path
            import sys
            output = Path(sys.argv[sys.argv.index("--output") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / "paper.md").write_text("# extracted", encoding="utf-8")
            (output / "paper_content_list_v2.json").write_text(
                '[[{"type":"simple_table","content":{"html":"<table/>"}}]]',
                encoding="utf-8",
            )
            """
        )
        invalid_result = self.run_wrapper(
            env=invalid_env, output_path=self.root / "invalid-root-type"
        )
        self.assertEqual(invalid_result.returncode, 2)
        self.assertIn(
            "unknown block type",
            self.read_manifest(self.root / "invalid-root-type")["error"]["message"],
        )

        external_markdown = self.root / "external.md"
        external_markdown.write_text("# external", encoding="utf-8")
        _, symlink_env = self.install_fake_mineru(
            f"""
            from pathlib import Path
            import sys
            output = Path(sys.argv[sys.argv.index("--output") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / "paper.md").symlink_to(Path({str(external_markdown)!r}))
            (output / "paper_content_list_v2.json").write_text(
                '[[{{"type":"paragraph","content":{{"paragraph_content":[]}}}}]]',
                encoding="utf-8",
            )
            """
        )
        symlink_result = self.run_wrapper(
            env=symlink_env, output_path=self.root / "symlink-artifact"
        )
        self.assertEqual(symlink_result.returncode, 2)
        self.assertEqual(
            self.read_manifest(self.root / "symlink-artifact")["error"]["code"],
            "unsafe_artifact",
        )

    def test_rejects_invalid_content_value_type(self) -> None:
        _, env = self.install_fake_mineru(
            """
            from pathlib import Path
            import sys
            output = Path(sys.argv[sys.argv.index("--output") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / "paper.md").write_text("# extracted", encoding="utf-8")
            (output / "paper_content_list_v2.json").write_text(
                '[[{"type":"paragraph","content":{"paragraph_content":123}}]]',
                encoding="utf-8",
            )
            """
        )

        result = self.run_wrapper(env=env)

        self.assertEqual(result.returncode, 2)
        self.assertIn("must be a list", self.read_manifest()["error"]["message"])

    def test_rejects_partial_requested_page_coverage(self) -> None:
        _, env = self.install_fake_mineru(
            """
            from pathlib import Path
            import sys
            output = Path(sys.argv[sys.argv.index("--output") + 1])
            output.mkdir(parents=True, exist_ok=True)
            (output / "paper.md").write_text("# extracted", encoding="utf-8")
            (output / "paper_content_list_v2.json").write_text(
                '[[{"type":"paragraph","content":{"paragraph_content":[]}}]]',
                encoding="utf-8",
            )
            """
        )

        result = self.run_wrapper("--start", "0", "--end", "1", env=env)

        self.assertEqual(result.returncode, 2)
        self.assertIn("page coverage", self.read_manifest()["error"]["message"])

    def test_success_discovers_artifacts_and_forwards_all_options(self) -> None:
        args_file = self.root / "args.json"
        env_file = self.root / "env.json"
        _, env = self.install_fake_mineru(
            f"""
            from pathlib import Path
            import json
            import os
            import sys
            Path({str(args_file)!r}).write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
            Path({str(env_file)!r}).write_text(json.dumps({{
                "MINERU_API_MAX_CONCURRENT_REQUESTS": os.environ.get("MINERU_API_MAX_CONCURRENT_REQUESTS"),
                "MINERU_PDF_RENDER_THREADS": os.environ.get("MINERU_PDF_RENDER_THREADS"),
                "MINERU_MODEL_SOURCE": os.environ.get("MINERU_MODEL_SOURCE"),
                "HF_HUB_OFFLINE": os.environ.get("HF_HUB_OFFLINE"),
                "TRANSFORMERS_OFFLINE": os.environ.get("TRANSFORMERS_OFFLINE"),
                "HTTP_PROXY": os.environ.get("HTTP_PROXY"),
                "HTTPS_PROXY": os.environ.get("HTTPS_PROXY"),
                "ALL_PROXY": os.environ.get("ALL_PROXY"),
                "http_proxy": os.environ.get("http_proxy"),
                "https_proxy": os.environ.get("https_proxy"),
                "all_proxy": os.environ.get("all_proxy"),
                "NO_PROXY": os.environ.get("NO_PROXY"),
                "no_proxy": os.environ.get("no_proxy"),
                "TMPDIR": os.environ.get("TMPDIR"),
                "TEMP": os.environ.get("TEMP"),
                "TMP": os.environ.get("TMP"),
                "PYTHONUNBUFFERED": os.environ.get("PYTHONUNBUFFERED"),
            }}), encoding="utf-8")
            output = Path(sys.argv[sys.argv.index("--output") + 1]) / "paper" / "auto"
            print("Using device: mps")
            images = output / "images"
            images.mkdir(parents=True, exist_ok=True)
            (output / "paper.md").write_text("# extracted", encoding="utf-8")
            block = {{"type": "paragraph", "content": {{"paragraph_content": []}}}}
            (output / "paper_content_list_v2.json").write_text(
                json.dumps([[block], [block], [block], [block]]),
                encoding="utf-8",
            )
            (output / "paper_layout.pdf").write_bytes(b"%PDF-layout")
            (images / "figure-1.png").write_bytes(b"png")
            """
        )
        unsafe_temp = self.root / "unsafe-temp"
        (unsafe_temp / ".git").mkdir(parents=True)
        env.update(
            {
                "HTTP_PROXY": "http://proxy.example:8080",
                "HTTPS_PROXY": "http://proxy.example:8080",
                "ALL_PROXY": "socks5://proxy.example:1080",
                "http_proxy": "http://proxy.example:8080",
                "https_proxy": "http://proxy.example:8080",
                "all_proxy": "socks5://proxy.example:1080",
                "NO_PROXY": "example.com",
                "no_proxy": "example.com",
                "TMPDIR": str(unsafe_temp),
                "TEMP": str(unsafe_temp),
                "TMP": str(unsafe_temp),
            }
        )

        result = self.run_wrapper(
            "--backend",
            "pipeline",
            "--effort",
            "medium",
            "--method",
            "ocr",
            "--start",
            "2",
            "--end",
            "5",
            env=env,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = self.read_manifest()
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["status"], "success")
        self.assertEqual(manifest["mineru"]["version"], "3.4.4")
        self.assertEqual(manifest["mineru"]["observed_device_engine"], "mps")
        self.assertGreaterEqual(manifest["timing"]["duration_seconds"], 0)
        self.assertTrue(manifest["source"]["verified_unchanged"])
        self.assertTrue(manifest["source"]["staged_copy_used"])
        self.assertEqual(manifest["request"]["backend"], "pipeline")
        self.assertEqual(manifest["request"]["effort"], "medium")
        self.assertEqual(manifest["request"]["pages"], {"start": 2, "end": 5})
        artifacts = manifest["artifacts"]
        self.assertEqual(artifacts["markdown"], ["paper/auto/paper.md"])
        self.assertEqual(artifacts["content_list_v2"], ["paper/auto/paper_content_list_v2.json"])
        self.assertEqual(artifacts["layout_pdf"], ["paper/auto/paper_layout.pdf"])
        self.assertEqual(artifacts["images"], ["paper/auto/images/figure-1.png"])
        self.assertEqual(artifacts["logs"], ["mineru-stderr.log", "mineru-stdout.log"])
        command_args = json.loads(args_file.read_text(encoding="utf-8"))
        self.assertEqual(command_args[0], "--path")
        staged_input = Path(command_args[1])
        self.assertNotEqual(staged_input, self.input.resolve())
        self.assertEqual(staged_input.name, self.input.name)
        self.assertFalse(staged_input.exists(), "the private staged copy must be removed")
        self.assertEqual(
            command_args[2:],
            [
                "--output",
                str(self.output.resolve()),
                "--backend",
                "pipeline",
                "--effort",
                "medium",
                "--method",
                "ocr",
                "--start",
                "2",
                "--end",
                "5",
            ],
        )
        runtime_env = json.loads(env_file.read_text(encoding="utf-8"))
        self.assertEqual(runtime_env["MINERU_API_MAX_CONCURRENT_REQUESTS"], "1")
        self.assertEqual(runtime_env["MINERU_PDF_RENDER_THREADS"], "1")
        self.assertEqual(runtime_env["MINERU_MODEL_SOURCE"], "local")
        self.assertEqual(runtime_env["HF_HUB_OFFLINE"], "1")
        self.assertEqual(runtime_env["TRANSFORMERS_OFFLINE"], "1")
        for proxy_name in (
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "ALL_PROXY",
            "http_proxy",
            "https_proxy",
            "all_proxy",
        ):
            self.assertIsNone(runtime_env[proxy_name])
        self.assertEqual(runtime_env["NO_PROXY"], "127.0.0.1,localhost,::1")
        self.assertEqual(runtime_env["no_proxy"], "127.0.0.1,localhost,::1")
        self.assertEqual(runtime_env["PYTHONUNBUFFERED"], "1")
        runtime_temp_paths = {
            Path(runtime_env[variable]) for variable in ("TMPDIR", "TEMP", "TMP")
        }
        self.assertEqual(len(runtime_temp_paths), 1)
        runtime_temp = runtime_temp_paths.pop()
        self.assertEqual(runtime_temp.parent.parent, self.output.resolve())
        self.assertFalse(runtime_temp.exists(), "private runtime temp must be cleaned normally")
        self.assertTrue(manifest["request"]["local_only"])
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.output / "mineru-stdout.log").stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
