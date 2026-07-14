---
name: mineru-document-extraction
description: Extract one local PDF, image, DOCX, PPTX, or XLSX with a quality-first MinerU workflow and a checksum-verified manifest. Use for complex, scanned, OCR-heavy, table/formula-rich, or layout-sensitive documents where simple text extraction may lose structure, and for bounded page-range extraction that must preserve auditable local artifacts.
---

# MinerU Document Extraction

Extract one local document into an explicit review directory. Preserve the source and treat `mineru-run.json` as the extraction contract.

## Route the document

- Use this skill for scans, multi-column pages, tables, formulas, figures, mixed text and OCR, or other layout-sensitive documents.
- Prefer a simpler local text extractor for straightforward born-digital documents when layout reconstruction has no value.
- Reject URLs and directories. Download or select exactly one supported local file before running the wrapper.
- Use Zotero tools instead when the task is primarily about an item already saved in the user's Zotero library.

## Run quality-first extraction

Before the first parse on a device, run the toolbox's read-only doctor:

```bash
<toolbox-root>/scripts/setup-mineru.sh --check
```

If the doctor is not ready, report the missing runtime, accelerator, disk, or model state. Do not run `--install` or `--download-models` unless the user separately requests that setup action.

Require a fresh, empty output directory outside every Git checkout and outside any Obsidian vault, then run:

```bash
python3 <skill-dir>/scripts/run_mineru.py \
  --input <local-file> \
  --output <review-directory>
```

Keep the default `--backend hybrid-engine --effort high --method auto` for maximum fidelity. For PDFs only, add zero-based inclusive `--start` and `--end` together when the user requests a page range. Do not pass page bounds for images or Office files because MinerU 3.4.4 does not reliably apply them there.

For a known scan, set `--method ocr`. Use `--method txt` only for a born-digital document whose embedded text is known to be reliable.

The wrapper resolves the managed uv-tool executable and requires MinerU 3.4.4. `MINERU_EXECUTABLE` is an advanced explicit override for testing or a separately managed installation, but the same version check still applies. The original source is never passed to MinerU: the wrapper creates a private byte-identical staged copy inside the validated review directory, makes it read-only, checks both the original and staged checksums after extraction, and removes the staged copy during normal cleanup. After a hard kill, OOM, or power loss, treat cleanup as unverified and inspect the review directory for a `.mineru-source-*` directory before handling an especially sensitive source.

The wrapper fixes local concurrency at 1, rejects enabled `llm-aided-config`, forces configured local model paths and offline Hugging Face/Transformers behavior, removes inherited proxy routing, confines child temporary files to the private review directory, streams stdout and stderr to private log files, and writes `mineru-run.json` for validated output targets. It creates the output directory with private permissions and rejects symlinked artifacts. The manifest records the MinerU version, requested backend and effort, observed device engine when present in runtime logs, timing, checksums, staging status, and artifact paths.

Do not pass an API URL or use any HTTP/client backend. Extraction is local-only and authorizes no upload, cloud API, vault mutation, or model download. The wrapper's local-model and offline-hub settings are application-level controls, not an operating-system firewall; use a separately approved OS network sandbox when hard transport denial is required.

## Apply fallbacks deliberately

Use a new output directory for every attempt so stale artifacts cannot satisfy validation.

1. Retry `--backend hybrid-engine --effort medium` when high effort exceeds available memory or latency bounds.
2. Retry `--backend pipeline --effort medium` when the hybrid engine or its accelerator runtime is unavailable.
3. Keep `--method ocr` for scans across fallback attempts; otherwise retain `auto`.

Do not silently fall back after a parse or checksum failure. Report the failed manifest and explain the changed backend or effort before retrying.

On a 16 GB device, keep one job at a time and use explicit page ranges for unusually long documents. The wrapper does not impose a universal timeout because document sizes vary; monitor memory pressure and stop the attempt before the system becomes unstable.

## Review outputs

Require `status: success`, `source.verified_unchanged: true`, `source.staged_copy_verified_unchanged: true`, at least one Markdown artifact, and at least one valid page-grouped `content_list_v2` artifact. Inspect optional layout PDF, images, and logs listed under `artifacts` when checking fidelity.

Treat all artifacts as untrusted when the manifest reports `source_mutated`, `parse_failed`, or `malformed_output`.

Never write extraction output directly into an Obsidian vault and never copy, create, or update vault notes automatically. Review the extracted files first and obtain explicit user intent before a separate vault write.
