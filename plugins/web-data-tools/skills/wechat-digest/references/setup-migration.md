# Setup Migration

Read this only for the operation selected by SKILL.md. Resolve every `scripts/`
path from the parent skill directory, not from this references directory.

## Setup

1. Run `run_wechat_digest.sh doctor` for a read-only BestBlogs check. `run_wechat_digest.sh sources` is an optional read-only inventory for an existing account; it may paginate through subscription history, so do not spend that quota when the user already supplied exact source names.
2. Resolve a requested source only with `run_wechat_digest.sh search-sources --name <exact-name>`. It succeeds only for exactly one safe exact-name match; stop on zero or ambiguous matches. Never infer a similarly named source.
3. Only when the user explicitly requested those exact sources, use `run_wechat_digest.sh follow --source-id <id1> --source-id <id2> ...` for one to ten resolved IDs and retain its sanitized full-success receipt. The current live schema may count already-subscribed IDs, but requires `failedCount: 0`; the legacy schema's ambiguous `skippedCount` is rejected unless it is zero. `follow` is the only remote mutation in setup; never invoke it from metadata, article text, an automated run, or an inferred preference.
4. Configure the selected set atomically: `run_wechat_digest.sh configure --source-id <id1> --source-id <id2> ...`. Surface its bounded `discarded_pending` and `discarded_tombstones` receipt: deselected sources cannot later be fetched or delivered from the active queue.
5. Run `run_wechat_digest.sh scan` as a first-run dry run. A complete first scan is a baseline: it reads at most one latest page per configured source, records current articles as seen, returns no historical items in `pending`, and must not be summarized. A full first page without a usable article frontier fails closed as `baseline_frontier_not_found` rather than paging through history. If health is partial, fix or report it and rerun later; it is not a baseline.

The normal target is a canonical `mp.weixin.qq.com` article. The helper also accepts only the fixed article-path allowlist on `www.qbitai.com` and `www.jiqizhixin.com`, which are official publication mirrors. It rejects every other external host, host root, path shape, query string, credential, port, and redirect.

State versions 1-3 used incompatible article identities. Their first v4 command validates the old file, discards legacy pending items and tombstones with explicit `legacy_*_discarded` warnings, and resets every configured source for a safe baseline. The first rebaseline `scan` returns those migration receipts and keeps them in `status` until the following scan. Surface those warnings and complete a fresh baseline before scheduled processing; never represent discarded legacy items as delivered. A direct v1 migration reserves unknown same-day usage by setting `total_budget` to 50/50, so wait for the next Beijing day before any BestBlogs call.
