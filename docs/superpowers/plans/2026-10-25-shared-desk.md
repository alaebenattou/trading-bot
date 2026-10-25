# Shared Trading Desk Implementation Plan

> Execute natively in this session, following the user's instruction to proceed.

**Goal:** Two admins can request analyses and share saved reports.
**Architecture:** Flask/Jinja, SQLite, one serial queue runner spawning isolated engine processes.
**Tech Stack:** Python, Flask, Werkzeug, markdown-it-py, SQLite, pytest.
**Spec:** docs/superpowers/specs/2026-10-25-shared-desk-design.md

## Global constraints
- Exactly two provisioned admins; no registration or committed credentials.
- Server environment holds OpenRouter key; no trading execution.
- Preserve upstream engine APIs and license.

## Review focus
- Anonymous access and missing CSRF must fail.
- Invalid ticker/date/model and full queue must not enqueue jobs.
- Both admins can read reports; generated HTML must remain inert.
- Failed, timed-out and interrupted jobs must have recoverable visible status.
- Installing the package must include templates/static files.

## Tasks
- [x] Write failing HTTP tests for setup/auth, login throttling, CSRF, shared jobs, validation, safe rendering and report download.
- [x] Implement `tradingagents/web/store.py` for SQLite and provisioning, `app.py` for authenticated routes, `worker.py` for isolated graph execution, and `__main__.py` for setup/serve commands. Verify HTTP tests.
- [x] Build responsive login/dashboard/new-run/report/settings templates and local static CSS/JS. Verify rendered pages at desktop and mobile sizes.
- [x] Add optional web dependencies, package assets, Docker service and setup/deployment docs. Run focused tests, full upstream suite, lint and package checks; review diff, commit and push to origin/main.

## Verification and decisions
- User instructed us to proceed with the integrated Python approach and remaining implementation choices. Work executed natively; no design approval pause.
- 31 new web/worker tests pass. Full suite: 1,392 passed, 1 optional Bedrock skip, 1 integration deselection, 100 subtests passed. Upstream socket tests require unsandboxed local socket permissions; the unrestricted run passed.
- Ruff and git diff whitespace checks pass. Wheel includes seven templates and two static assets; installed-wheel login/static smoke passes without local secrets.
- Chromium checks passed for both admins and routes at 1440, 768, and 375px, with mobile logout, no horizontal overflow, and no JavaScript errors.
- Independent reviewer found a shutdown orphan risk. Added child termination/reaping, queue join, SIGTERM handling, conditional report completion, and real subprocess regression tests. Reviewer confirmed no remaining important findings.
- Provisioned two local accounts with random unique passwords in an ignored, owner-only file. No default credentials in source, no model key configured, and no paid model calls made.
- Docker configuration is supplied; Docker is unavailable here, so the image was not built. Live deployment and real-provider validation remain future operator steps.
