# Scheduling

Read this only for the operation selected by SKILL.md. Resolve every `scripts/`
path from the parent skill directory, not from this references directory.

For delivery requirements and the baseline/status contract, read
[incremental digests](incremental-digest.md) before creating or updating a schedule.
The lifecycle guards referenced below are in that document.

## Automation

Only after `status` proves a complete baseline, create a Codex automation that invokes the incremental digest lifecycle daily at 08:30 in `America/New_York`. The automation prompt must retain every claim, renewal, fallback, acknowledgment, failure, and final-status guard above. If an automation scheduler is unavailable, report the 08:30 task as **not deployed**; do not substitute an OS cron job or claim that scheduling succeeded.
