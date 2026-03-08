---
name: mailatlas-maintainer
description: Maintain the MailAtlas email-ingestion project in /Users/chiragagrawal/Documents/workspace/newsletter. Use when working on parser behavior, HTML/PDF export, docs and site previews, CLI demos, parser API demos, or release-readiness tasks for MailAtlas.
---

# MailAtlas Maintainer

Use this skill when the task is specifically about the MailAtlas repo.

## Repo

- Default repo: `/Users/chiragagrawal/Documents/workspace/newsletter`
- Before promising a commit, check whether `.git/` exists. This workspace may not be initialized as a git repo yet.

## Product Guardrails

- Position MailAtlas as email ingestion for AI agents and data applications.
- Treat filesystem plus SQLite as the default implementation, not the product identity.
- Do not lead public copy with `local-first`.
- Do not make briefing generation the primary story.

## Core Validation

1. Run the Python tests:
   `.tmp-verify-312b/bin/python -m unittest discover -s tests -v`
2. Rebuild docs when site or README-facing behavior changes:
   `cd site && npm run build`
3. For landing/docs review, serve `site/dist` and inspect the actual pages:
   `python3 -m http.server 8766 --bind 127.0.0.1 -d site/dist`
4. Use `scripts/chrome_capture.sh` for screenshots instead of ad hoc Chrome commands.

## Deterministic Demos

- CLI demo script:
  `scripts/demo_cli.sh`
- Parser API demo script:
  `scripts/demo_parser_api.sh`

The demo scripts default to the synthetic inline-chart fixture and write outputs under `/tmp` so they stay out of the repo.

## PDF Export Notes

- PDF export depends on Chrome or Chromium.
- Keep `--virtual-time-budget=3000` in the renderer so inline assets load before print.
- Do not reintroduce `--user-data-dir`; it hangs Chrome in this environment.
- If the direct installed CLI fails only under the Codex sandbox, rerun the same `mailatlas export` command with escalation before treating it as a product bug.

## Fixtures And Regressions

- Keep `data/fixtures/atlas-inline-chart.eml` visibly rendered. Do not replace it with a transparent placeholder.
- If HTML export writes to a custom `--out` path, verify asset references are rewritten relative to the export destination.
- Parser-only demos should use `parse_eml(...)` and not rely on the storage layer.

## Reporting

- When demoing CLI behavior, show the exact command, the input fixture, and the generated output path.
- When demoing parser behavior, show the `parse_eml(...)` snippet and the parsed JSON shape.
