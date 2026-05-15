# Claude Guide

This repository uses `AGENTS.md` as the shared rulebook for all AI agents.
Read `AGENTS.md` before making changes.

## Claude-Specific Workflow

- Plan the smallest coherent change before editing.
- Preserve existing behavior unless the task explicitly changes it.
- Prefer test-backed changes over speculative refactors.
- After edits, inspect `git diff --stat` and the relevant file diffs.
- Keep commits small and focused.

## Required Context

Load additional context just in time:

- Frontend work: `frontend/CLAUDE.md`
- Backend alarm engine work: `backend/common/CLAUDE.md`
- Deployment work: `guides/OPERATIONS.md`
- Contract work: `docs/API-CONTRACT.md`, `docs/DATA-MODEL.md`,
  `docs/API-WORKFLOWS.md`

## Verification

- Backend tests run from `backend/`.
- Frontend typecheck runs from `frontend/` with `npx tsc --noEmit`.
- Backend Lambda code changes must follow the deployment rule in `AGENTS.md`
  and `guides/OPERATIONS.md`.
