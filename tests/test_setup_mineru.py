#!/usr/bin/env python3
"""Behavioral tests for the optional MinerU runtime bootstrap."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "setup-mineru.sh"


class SetupMinerUTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.home = Path(self.tempdir.name)
        self.bin_dir = self.home / "bin"
        self.bin_dir.mkdir()
        self.uv_tool_dir = self.home / "uv-tools"
        self.runtime_dir = self.uv_tool_dir / "mineru"
        self.cache_dir = self.home / "model-cache"
        self.config_file = self.home / "mineru.json"

        self.env = os.environ.copy()
        self.env.update(
            {
                "HOME": str(self.home),
                "PATH": f"{self.bin_dir}:/usr/bin:/bin",
                "MINERU_UV_TOOL_DIR": str(self.uv_tool_dir),
                "MINERU_MODEL_CACHE_DIR": str(self.cache_dir),
                "MINERU_TOOLS_CONFIG_JSON": str(self.config_file),
                "MINERU_MIN_DISK_GB": "0",
            }
        )
        self.write_executable(
            "uname",
            """#!/bin/sh
if [ "$1" = "-s" ]; then printf '%s\n' "${FAKE_UNAME_S:-Darwin}"; exit 0; fi
if [ "$1" = "-m" ]; then printf '%s\n' "${FAKE_UNAME_M:-arm64}"; exit 0; fi
exit 1
""",
        )

    def write_executable(self, name: str, body: str) -> Path:
        path = self.bin_dir / name
        path.write_text(body)
        path.chmod(0o755)
        return path

    def install_fake_runtime(
        self,
        *,
        mineru_version: str = "3.4.4",
        python_version: str = "3.12",
        machine: str = "arm64",
        mps_built: str = "yes",
        mps_available: str = "yes",
        mlx: str = "yes",
        mlx_vlm: str = "yes",
        mlx_gpu: str = "yes",
        vlm_engine: str = "mlx-engine",
    ) -> None:
        runtime_bin = self.runtime_dir / "bin"
        runtime_bin.mkdir(parents=True)
        probe = "|".join(
            (
                mineru_version,
                python_version,
                machine,
                mps_built,
                mps_available,
                mlx,
                mlx_vlm,
                mlx_gpu,
                vlm_engine,
            )
        )
        python = runtime_bin / "python3"
        python.write_text(f"#!/bin/sh\nprintf '%s\\n' '{probe}'\n")
        python.chmod(0o755)
        downloader = runtime_bin / "mineru-models-download"
        downloader.write_text("#!/bin/sh\nexit 0\n")
        downloader.chmod(0o755)

    def install_fake_uv(self) -> None:
        self.write_executable("uv", "#!/bin/sh\nprintf 'uv 0.8.0\\n'\n")

    def install_fake_uv_bootstrap(self, log_file: Path) -> None:
        runtime_dir = shlex.quote(str(self.runtime_dir))
        probe = "3.4.4|3.12|arm64|yes|yes|yes|yes|yes|mlx-engine"
        self.write_executable(
            "uv",
            f"""#!/bin/sh
printf '%s\n' "$*" >> {shlex.quote(str(log_file))}
if [ "$1" = "tool" ] && [ "$2" = "install" ]; then
  mkdir -p {runtime_dir}/bin
  printf '%s\n' '#!/bin/sh' "printf '%s\\n' '{probe}'" > {runtime_dir}/bin/python3
  chmod +x {runtime_dir}/bin/python3
fi
""",
        )

    def install_ready_models(self) -> None:
        pipeline = self.cache_dir / "pipeline"
        vlm = self.cache_dir / "vlm"
        pipeline.mkdir(parents=True)
        vlm.mkdir(parents=True)
        (pipeline / "model.bin").write_text("pipeline")
        (vlm / "model.safetensors").write_text("vlm")
        self.config_file.write_text(
            json.dumps({"models-dir": {"pipeline": str(pipeline), "vlm": str(vlm)}})
        )

    def run_script(self, mode: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPT), mode],
            cwd=ROOT,
            env=self.env,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_check_with_absent_uv_and_runtime_is_non_mutating(self) -> None:
        before = sorted(path.relative_to(self.home) for path in self.home.rglob("*"))

        result = self.run_script("--check")

        after = sorted(path.relative_to(self.home) for path in self.home.rglob("*"))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("uv: missing", result.stdout)
        self.assertIn("MinerU runtime: missing", result.stdout)
        self.assertIn("MinerU version: missing (expected 3.4.4)", result.stdout)
        self.assertEqual(before, after, "--check must not create files or directories")

    def test_check_reports_version_mismatch(self) -> None:
        self.install_fake_uv()
        self.install_fake_runtime(mineru_version="3.4.3")
        self.install_ready_models()

        result = self.run_script("--check")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("MinerU version: mismatch (found 3.4.3; expected 3.4.4)", result.stdout)

    def test_check_reports_unsupported_platform(self) -> None:
        self.env["FAKE_UNAME_S"] = "Linux"
        self.env["FAKE_UNAME_M"] = "x86_64"

        result = self.run_script("--check")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Platform: unsupported (requires macOS arm64)", result.stdout)

    def test_check_reports_ready_state_without_personal_identifiers(self) -> None:
        self.install_fake_uv()
        self.install_fake_runtime()
        self.install_ready_models()
        before = sorted(path.relative_to(self.home) for path in self.home.rglob("*"))

        result = self.run_script("--check")

        after = sorted(path.relative_to(self.home) for path in self.home.rglob("*"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for expected in (
            "Platform: ready (macOS arm64)",
            "uv: ready",
            "MinerU runtime: ready",
            "MinerU version: ready (3.4.4)",
            "Python compatibility: ready (CPython 3.12, arm64)",
            "Disk capacity: ready",
            "MPS: ready (built and available)",
            "MLX: ready (GPU device and mlx-engine selected)",
            "Model cache: ready (pipeline and vlm)",
            "Overall: ready",
        ):
            self.assertIn(expected, result.stdout)
        self.assertNotIn(str(self.home), result.stdout)
        self.assertEqual(before, after, "a ready --check must also remain non-mutating")

    def test_check_rejects_mlx_without_gpu_engine_readiness(self) -> None:
        self.install_fake_uv()
        self.install_fake_runtime(mlx_gpu="no", vlm_engine="transformers")
        self.install_ready_models()

        result = self.run_script("--check")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("MLX: unavailable (GPU device or mlx-engine not ready)", result.stdout)

    def test_check_reports_model_paths_inside_a_vault_as_unsafe(self) -> None:
        self.install_fake_uv()
        self.install_fake_runtime()
        vault = self.home / "vault"
        (vault / ".obsidian").mkdir(parents=True)
        self.cache_dir = vault / "models"
        self.env["MINERU_MODEL_CACHE_DIR"] = str(self.cache_dir)
        self.install_ready_models()

        result = self.run_script("--check")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Model cache: unsafe", result.stdout)

    def test_check_reports_config_inside_a_git_checkout_as_unsafe(self) -> None:
        self.install_fake_uv()
        self.install_fake_runtime()
        self.install_ready_models()
        checkout = self.home / "config-checkout"
        (checkout / ".git").mkdir(parents=True)
        unsafe_config = checkout / "mineru.json"
        unsafe_config.write_text(self.config_file.read_text())
        self.env["MINERU_TOOLS_CONFIG_JSON"] = str(unsafe_config)

        result = self.run_script("--check")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("Model cache: unsafe", result.stdout)

    def test_check_rejects_enabled_llm_aided_remote_config(self) -> None:
        self.install_fake_uv()
        self.install_fake_runtime()
        self.install_ready_models()
        config = json.loads(self.config_file.read_text())
        config["llm-aided-config"] = {
            "title_aided": {
                "enable": True,
                "base_url": "https://remote.example/v1",
            }
        }
        self.config_file.write_text(json.dumps(config))

        result = self.run_script("--check")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("llm-aided remote features enabled", result.stdout)

    def test_no_argument_or_unknown_argument_never_mutates(self) -> None:
        for mode in ("", "--unknown"):
            command = ["bash", str(SCRIPT)]
            if mode:
                command.append(mode)
            result = subprocess.run(
                command,
                cwd=ROOT,
                env=self.env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Usage:", result.stderr)
        self.assertFalse(self.runtime_dir.exists())
        self.assertFalse(self.cache_dir.exists())

    def test_install_uses_exact_pin_without_downloading_models(self) -> None:
        log_file = self.home / "uv.log"
        self.install_fake_uv_bootstrap(log_file)

        result = self.run_script("--install")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        invocations = log_file.read_text()
        self.assertIn("tool install --python 3.12 mineru[all]==3.4.4", invocations)
        self.assertNotIn("venv", invocations)
        self.assertNotIn("pip install", invocations)
        self.assertFalse(self.cache_dir.exists(), "--install must not download models")

    def test_install_is_idempotent_when_exact_tool_is_ready(self) -> None:
        self.install_fake_runtime()
        self.write_executable("uv", "#!/bin/sh\nexit 99\n")

        result = self.run_script("--install")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("already installed in the managed uv tool environment", result.stdout)
        self.assertFalse(self.cache_dir.exists(), "an idempotent install must not download models")

    def test_install_force_repairs_a_mismatched_managed_tool(self) -> None:
        self.install_fake_runtime(mineru_version="3.4.3")
        log_file = self.home / "uv-repair.log"
        self.install_fake_uv_bootstrap(log_file)

        result = self.run_script("--install")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "tool install --force --python 3.12 mineru[all]==3.4.4",
            log_file.read_text(),
        )

    def test_download_models_rejects_an_incomplete_cache(self) -> None:
        self.install_fake_runtime()

        result = self.run_script("--download-models")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("did not produce a ready pipeline and VLM model cache", result.stderr)

    def test_download_models_uses_external_cache_and_noninteractive_flags(self) -> None:
        self.install_fake_runtime()
        log_file = self.home / "download.log"
        downloader = self.runtime_dir / "bin" / "mineru-models-download"
        downloader.write_text(
            f"""#!/bin/sh
printf '%s\n' "$*" > {shlex.quote(str(log_file))}
printf '%s\n' "$HF_HOME" "$MODELSCOPE_CACHE" "$MINERU_TOOLS_CONFIG_JSON" >> {shlex.quote(str(log_file))}
mkdir -p {shlex.quote(str(self.cache_dir / 'pipeline'))} {shlex.quote(str(self.cache_dir / 'vlm'))}
printf pipeline > {shlex.quote(str(self.cache_dir / 'pipeline' / 'model.bin'))}
printf vlm > {shlex.quote(str(self.cache_dir / 'vlm' / 'model.bin'))}
printf '%s\n' {shlex.quote(json.dumps({'models-dir': {'pipeline': str(self.cache_dir / 'pipeline'), 'vlm': str(self.cache_dir / 'vlm')}}))} > "$MINERU_TOOLS_CONFIG_JSON"
"""
        )
        downloader.chmod(0o755)

        result = self.run_script("--download-models")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        log = log_file.read_text()
        self.assertIn("--source auto --model_type all", log)
        self.assertIn(str(self.cache_dir / "huggingface"), log)
        self.assertIn(str(self.cache_dir / "modelscope"), log)
        self.assertIn(str(self.config_file), log)
        self.assertNotIn(str(ROOT), log)
        self.assertEqual(stat.S_IMODE(self.cache_dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.config_file.stat().st_mode), 0o600)

        self.config_file.chmod(0o644)
        second_result = self.run_script("--download-models")
        self.assertEqual(second_result.returncode, 0, second_result.stdout + second_result.stderr)
        self.assertEqual(stat.S_IMODE(self.config_file.stat().st_mode), 0o600)

    def test_download_models_refuses_a_cache_inside_the_checkout_before_writing(self) -> None:
        self.install_fake_runtime()
        unsafe_cache = ROOT / ".mineru-test-cache"
        self.env["MINERU_MODEL_CACHE_DIR"] = str(unsafe_cache)
        self.addCleanup(lambda: unsafe_cache.rmdir() if unsafe_cache.is_dir() else None)

        result = self.run_script("--download-models")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("outside every Git checkout and Obsidian vault", result.stderr)
        self.assertFalse(unsafe_cache.exists())

    def test_download_models_rejects_other_git_and_vault_destinations(self) -> None:
        self.install_fake_runtime()
        other_checkout = self.home / "other-checkout"
        (other_checkout / ".git").mkdir(parents=True)
        discovered_vault = self.home / "discovered-vault"
        (discovered_vault / ".obsidian").mkdir(parents=True)
        configured_vault = self.home / "configured-vault"
        configured_vault.mkdir()

        cases = (
            (
                "MINERU_MODEL_CACHE_DIR",
                other_checkout / "models",
                {},
            ),
            (
                "MINERU_TOOLS_CONFIG_JSON",
                discovered_vault / "mineru.json",
                {},
            ),
            (
                "MINERU_MODEL_CACHE_DIR",
                configured_vault / "models",
                {"CODEX_OBSIDIAN_VAULT": str(configured_vault)},
            ),
        )
        for env_name, destination, extra_env in cases:
            with self.subTest(destination=destination):
                env = self.env.copy()
                env.update(extra_env)
                env[env_name] = str(destination)
                result = subprocess.run(
                    ["bash", str(SCRIPT), "--download-models"],
                    cwd=ROOT,
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 1)
                self.assertIn("outside every Git checkout and Obsidian vault", result.stderr)
                self.assertFalse(destination.exists())

    def test_relative_mineru_config_name_is_resolved_under_home(self) -> None:
        self.install_fake_runtime()
        self.env["MINERU_TOOLS_CONFIG_JSON"] = "config/mineru.json"
        log_file = self.home / "config-path.log"
        downloader = self.runtime_dir / "bin" / "mineru-models-download"
        downloader.write_text(
            f"#!/bin/sh\nprintf '%s\\n' \"$MINERU_TOOLS_CONFIG_JSON\" > {shlex.quote(str(log_file))}\nexit 7\n"
        )
        downloader.chmod(0o755)

        result = self.run_script("--download-models")

        self.assertEqual(result.returncode, 7, result.stdout + result.stderr)
        self.assertEqual(log_file.read_text().strip(), str(self.home / "config/mineru.json"))


if __name__ == "__main__":
    unittest.main()
