"""Bounded stock LaTeXiT GUI adapter; caller owns the file transaction and lock.

Only private working documents may be passed here. A timeout is never retried.
The adapter does not decode equation archives or change LinkBack ownership.
TeX and its installed runtime must be trusted; profile checks are not a sandbox.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile
import time


class AdapterError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class LatexitAdapter:
    def __init__(self, omni_app="/Applications/OmniGraffle.app", latexit_app="/Applications/LaTeXiT.app", timeout=30, runtime_dir=None):
        self.omni_app = str(Path(omni_app).resolve())
        self.latexit_app = str(Path(latexit_app).resolve())
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 1 <= timeout <= 180:
            raise ValueError("timeout must be 1..180 seconds")
        self.timeout = timeout
        self.runtime_dir = Path(runtime_dir or Path.home() / "Library/Caches/codex-omnigraffle")
        self.source_dir = Path(__file__).resolve().parent
        self._deadline = None
        self._operation_dir = None
        self._diagnostic_paths = []

    def _diagnostic(self, args, returncode, stderr, stdout=None):
        """Private bounded native diagnostics; never include them in stdout receipts."""
        if self._operation_dir is None:
            return
        try:
            raw = stderr if isinstance(stderr, bytes) else (stderr or "").encode("utf-8", errors="replace")
            phase = args[2] if len(args) > 2 and args[0] == "/usr/bin/osascript" else (args[1] if len(args) > 1 else "native")
            record = {"phase": phase, "returncode": returncode, "stderr": raw[:65536].decode("utf-8", errors="replace"), "truncated": len(raw) > 65536}
            if stdout is not None:
                output = stdout.encode("utf-8", errors="replace")
                record["stdout"] = output[:65536].decode("utf-8", errors="replace")
                record["truncated"] |= len(output) > 65536
            path = self._operation_dir / ("native-error-" + str(len(self._diagnostic_paths) + 1) + ".private.json")
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(record, stream, ensure_ascii=False)
            self._diagnostic_paths.append(str(path))
        except (OSError, TypeError, ValueError):
            pass  # Logging must not replace the primary native outcome.

    def _remaining(self):
        remaining = self.timeout if self._deadline is None else self._deadline - time.monotonic()
        if remaining <= 0:
            raise AdapterError("timeout", "Equation operation deadline exhausted")
        return remaining

    @staticmethod
    def _profile(readiness):
        profile = readiness.get("composition_profile", {})
        if profile.get("status") != "safe":
            raise AdapterError("unsafe_composition_profile", "Use a trusted PDFLaTeX profile without custom arguments or enabled processing scripts")

    @staticmethod
    def _validate(request):
        if not isinstance(request, dict):
            raise AdapterError("invalid_request", "Request must be an object")
        r = dict(request)
        operation = r.get("op", r.get("operation"))
        if operation not in {"equation-render", "equation-insert", "equation-source", "equation-update"}:
            raise AdapterError("invalid_request", "Unsupported equation operation")
        r["op"] = operation
        if operation != "equation-source":
            equation = r.get("equation")
            if not isinstance(equation, dict) or set(equation) != {"source", "preamble", "mode", "font_size"}:
                raise AdapterError("invalid_equation", "Provide source, preamble, mode, and font_size")
            for key in ("source", "preamble"):
                value = equation[key]
                if not isinstance(value, str) or "\0" in value or len(value.encode("utf-8")) > 65536:
                    raise AdapterError("invalid_equation", "Equation text must be at most 65536 UTF-8 bytes without NUL")
            size = equation["font_size"]
            if isinstance(size, bool) or not isinstance(size, (int, float)) or not math.isfinite(size) or not 1 <= size <= 256:
                raise AdapterError("invalid_equation", "Font size must be 1..256 points")
            if equation["mode"] not in {"display", "inline", "align", "text"}:
                raise AdapterError("invalid_equation", "Unsupported equation mode")
        if operation != "equation-render":
            value = r.get("path")
            if not isinstance(value, str) or not Path(value).is_absolute() or "\0" in value:
                raise AdapterError("invalid_request", "An absolute working document path is required")
            r["path"] = str(Path(value).resolve(strict=True))
            for key in (["canvas_id"] if operation == "equation-insert" else ["canvas_id", "object_id"]):
                if type(r.get(key)) is not int or r[key] < 1:
                    raise AdapterError("invalid_request", "Native identifiers must be positive integers")
        if operation == "equation-insert":
            if not isinstance(r.get("key"), str) or not r["key"] or len(r["key"]) > 256 or "\0" in r["key"]:
                raise AdapterError("invalid_request", "A bounded equation key is required")
            for key in ("x", "y"):
                if type(r.get(key)) not in {int, float} or not math.isfinite(r[key]) or abs(r[key]) > 1_000_000:
                    raise AdapterError("invalid_request", "Coordinates must be finite points")
        if operation in {"equation-render", "equation-insert"}:
            value = r.get("output_dir")
            if not isinstance(value, str) or not Path(value).is_absolute() or "\0" in value:
                raise AdapterError("invalid_request", "An absolute new output directory is required")
            p = Path(value)
            if p.exists() or p.is_symlink():
                raise AdapterError("output_exists", "Output directory must not exist")
            r["output_dir"] = str(p.parent.resolve(strict=True) / p.name)
        return r

    def _run(self, args, *, mutation=False):
        try:
            p = subprocess.run(args, capture_output=True, text=True, timeout=self._remaining(), check=False)
        except subprocess.TimeoutExpired as exc:
            self._diagnostic(args, "timeout", exc.stderr)
            raise AdapterError("outcome_unknown" if mutation else "timeout", "Native operation timed out; do not retry mutations") from exc
        if p.returncode == 3 and len(args) > 1 and args[1] == "restore":
            try:
                skipped = json.loads(p.stdout)
            except ValueError:
                skipped = None
            if skipped == {"status": "restore_skipped", "reason": "clipboard_changed"}:
                return skipped
        if p.returncode:
            self._diagnostic(args, p.returncode, p.stderr, p.stdout)
            # No source, clipboard content or arbitrary application diagnostics in receipts.
            raise AdapterError("outcome_unknown" if mutation else "native_error", "Native adapter failed; inspect the operation before retrying")
        try:
            result = json.loads(p.stdout)
        except (ValueError, TypeError) as exc:
            self._diagnostic(args, p.returncode, p.stderr)
            raise AdapterError("outcome_unknown" if mutation else "invalid_response", "Native adapter returned invalid JSON") from exc
        if not isinstance(result, dict):
            self._diagnostic(args, p.returncode, p.stderr)
            raise AdapterError("outcome_unknown" if mutation else "invalid_response", "Native adapter response must be an object")
        if result.get("status") not in {"ok", "invalid_tex", "snapshot_saved", "captured", "restored"}:
            self._diagnostic(args, p.returncode, p.stderr)
            raise AdapterError("outcome_unknown" if mutation else "native_error", "Native adapter did not confirm successful completion")
        return result

    def _helper(self):
        source = self.source_dir / "pasteboard.m"
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        self.runtime_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.runtime_dir.is_symlink() or self.runtime_dir.stat().st_uid != os.getuid() or self.runtime_dir.stat().st_mode & 0o077:
            raise AdapterError("unsafe_runtime", "Runtime directory must be private and owned by the current user")
        binary = self.runtime_dir / ("pasteboard-" + digest)
        if not binary.exists():
            temporary = Path(tempfile.mkdtemp(prefix="compile-", dir=self.runtime_dir)) / "pasteboard"
            try:
                subprocess.run(["/usr/bin/xcrun", "clang", "-fobjc-arc", "-framework", "Cocoa", "-framework", "ApplicationServices", str(source), "-o", str(temporary)], capture_output=True, timeout=self._remaining(), check=True)
                temporary.chmod(0o700)
                os.replace(temporary, binary)
            except (OSError, subprocess.SubprocessError) as exc:
                raise AdapterError("helper_unavailable", "Compiling the fixed Cocoa helper requires local Xcode command-line tools") from exc
            finally:
                if temporary.exists():
                    temporary.unlink()
                temporary.parent.rmdir()
        if binary.is_symlink() or binary.stat().st_uid != os.getuid() or binary.stat().st_mode & 0o022:
            raise AdapterError("unsafe_runtime", "Unsafe helper executable")
        return str(binary)

    def _script(self, phase, request, directory, *, mutation=False):
        path = directory / (phase + ".json")
        with path.open("x", encoding="utf-8") as stream:
            json.dump(request, stream, ensure_ascii=False, allow_nan=False)
        path.chmod(0o600)
        result = self._run(["/usr/bin/osascript", str(self.source_dir / "latexit.applescript"), phase, str(path)], mutation=mutation)
        allowed = {"ok", "invalid_tex"} if phase == "render" else {"ok"}
        if result.get("status") not in allowed:
            raise AdapterError("outcome_unknown" if mutation else "native_error", "Native phase did not confirm completion")
        return result

    def call(self, request):
        warnings = []
        result = None
        directory = None
        cleanup_unknown = False
        self._operation_dir = None
        self._diagnostic_paths = []
        self._deadline = time.monotonic() + self.timeout
        try:
            r = self._validate(request)
            helper = self._helper()
            readiness = self._run([helper, "readiness"])
            if not readiness.get("unlocked") or not readiness.get("accessibility"):
                raise AdapterError("desktop_unavailable", "An unlocked desktop and existing Accessibility permission are required")
            if r["op"] != "equation-source":
                self._profile(readiness)
            for bundle, path, key in (("com.omnigroup.OmniGraffle7", self.omni_app, "omni_pid"), ("fr.chachatelier.pierre.LaTeXiT", self.latexit_app, "latexit_pid")):
                matches = [app for app in readiness.get("apps", []) if app.get("bundle_id") == bundle]
                if len(matches) != 1 or str(Path(matches[0]["path"]).resolve()) != path:
                    raise AdapterError("application_identity", "Start exactly one instance of the configured official application")
                r[key] = matches[0]["pid"]
            r.update(omni_app=self.omni_app, latexit_app=self.latexit_app)
            directory = Path(tempfile.mkdtemp(prefix="equation-", dir=self.runtime_dir))
            self._operation_dir = directory
            if r["op"] in {"equation-render", "equation-insert"}:
                # A GUI New document protects its first two preamble lines.
                # Official TeX import initializes a document with the requested
                # preamble instead of trying to overwrite those protected lines.
                tex_input = directory / "equation.tex"
                tex_input.write_text(r["equation"]["preamble"] + "\n\\begin{document}\n" + r["equation"]["source"] + "\n\\end{document}\n", encoding="utf-8")
                tex_input.chmod(0o600)
                r["tex_input"] = str(tex_input)
            snapshot = directory / "clipboard.private-plist"
            clipboard_count = None
            owned_editor = False
            editor_idle = False
            try:
                self._script("preflight", r, directory)
                if r["op"] != "equation-source":
                    saved = self._run([helper, "snapshot", str(snapshot)])
                    clipboard_count = saved["change_count"]
                    if saved.get("unavailable_legacy_text_aliases", 0):
                        warnings.append("Clipboard snapshot retained all readable formats and Unicode text; an unavailable legacy text alias had no bytes to preserve")
                    r["clipboard_count"] = clipboard_count
                # Failure after begin may have opened an editor; leave it for reconciliation.
                begun = self._script("begin", r, directory, mutation=True)
                owned_editor = True
                editor_idle = True
                r["editor_title"] = begun["editor_title"]
                if r["op"] == "equation-source":
                    result = self._script("read", r, directory)
                    editor_idle = True
                else:
                    if r["op"] == "equation-update":
                        current = self._script("read", r, directory)
                        if current.get("equation", {}).get("preamble") != r["equation"]["preamble"]:
                            raise AdapterError("protected_preamble", "Linked updates must retain the existing preamble; LaTeXiT protects its leading lines. Insert a new equation to use a different preamble")
                    self._profile(self._run([helper, "readiness"]))
                    editor_idle = False
                    # Text entry uses AX values and leaves the clipboard alone.
                    # Retain its count; restoration still refuses external changes.
                    result = self._script("render", r, directory, mutation=True)
                    editor_idle = True
                    clipboard_count = result["change_count"]
                    if result.get("status") != "ok":
                        raise AdapterError("invalid_tex", "LaTeXiT reported rendering errors; the transaction must not be committed")
                    if result.get("equation") != r["equation"]:
                        raise AdapterError("equation_mismatch", "Rendered editor settings do not match the request")
                    if r["op"] in {"equation-render", "equation-insert"}:
                        r["clipboard_count"] = clipboard_count
                        clipboard_count = None
                        copied = self._script("copy", r, directory, mutation=True)
                        clipboard_count = copied["change_count"]
                        capture = self._run([helper, "capture", r["output_dir"], str(clipboard_count)])
                        result.update(capture)
                        result["status"] = "ok"
                        result["output_dir"] = r["output_dir"]
                        if r["op"] == "equation-insert":
                            r["clipboard_count"] = clipboard_count
                            result.update(self._script("paste", r, directory, mutation=True))
                result.update(verification="adapter_completed_requires_native_verification", owner="fr.chachatelier.pierre.LaTeXiT")
            finally:
                # One shared cleanup budget; never extend a phase timeout independently.
                self._deadline = min(self._deadline + 5, time.monotonic() + 5)
                if clipboard_count is not None:
                    try:
                        restored = self._run([helper, "restore", str(snapshot), str(clipboard_count)], mutation=True)
                        if restored.get("status") != "restored":
                            if restored == {"status": "restore_skipped", "reason": "clipboard_changed"}:
                                warnings.append("clipboard_changed_private_backup_retained")
                            else:
                                cleanup_unknown = True
                                warnings.append("clipboard_restore_outcome_unknown")
                    except (AdapterError, OSError, ValueError, KeyError):
                        warnings.append("clipboard_not_restored_private_backup_retained")
                        cleanup_unknown = True
                elif snapshot.exists():
                    warnings.append("clipboard_copy_outcome_unknown_private_backup_retained")
                    cleanup_unknown = True
                if owned_editor and editor_idle:
                    try:
                        self._script("close", r, directory, mutation=True)
                    except (AdapterError, OSError, ValueError, KeyError):
                        warnings.append("adapter_editor_left_open_inspect_before_retry")
                        cleanup_unknown = True
                elif owned_editor:
                    warnings.append("editor_outcome_unknown_left_open_for_reconciliation")
                    cleanup_unknown = True
        except (AdapterError, OSError, ValueError, KeyError) as exc:
            result = {"status": "error", "code": getattr(exc, "code", "invalid_request"), "message": str(exc)}
        if cleanup_unknown:
            result = {"status": "error", "code": "outcome_unknown", "message": "Native editor or clipboard operation needs reconciliation before another mutation"}
        result["outcome_unknown"] = result.get("code") == "outcome_unknown"
        self._deadline = None
        result["warnings"] = warnings
        if directory is not None:
            result["operation_dir"] = str(directory)
        if self._diagnostic_paths:
            result["diagnostics_paths"] = self._diagnostic_paths[:]
        self._operation_dir = None
        return result
