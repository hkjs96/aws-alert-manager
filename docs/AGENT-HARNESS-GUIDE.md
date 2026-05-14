# Agent Harness Guide

This document preserves the useful content from `message.txt` and `message2.txt`
as a project guide.

## Why This Exists

AI agents often fail in two predictable ways during long engineering work:

1. Context anxiety: the agent tries to finish early as context grows, leaving
   TODOs, stubs, or partial behavior behind.
2. Self-evaluation blind spots: the agent over-trusts its own implementation and
   reports success without independently checking the result.

The mitigation is a harness: a workflow that separates planning, implementation,
and evaluation so quality is measured against explicit criteria instead of a
general "looks done" judgment.

## Harness Roles

| Role | Responsibility |
| --- | --- |
| Planner | Converts a high-level request into a bounded sprint contract. |
| Generator | Implements only the agreed scope. |
| Evaluator | Audits behavior, tests, and diff scope before work is accepted. |

This project usually runs those roles through process discipline rather than
separate agents: define the contract, make the change, then verify the result.

## Quality Criteria

Must-pass criteria:

- No stub functions or unresolved TODOs in the requested behavior.
- Existing behavior is preserved unless the user explicitly requested a change.
- API request and response contracts remain synchronized between backend,
  frontend types, and documentation.
- Backend tests, frontend type checks, and relevant unit tests are run.
- `git diff --name-only` and `git diff --stat` are reviewed for unexpected files.

Should-pass criteria:

- Error cases are handled intentionally.
- Empty states and backend failures do not crash routine frontend pages.
- UI behavior is checked from the user's workflow, not only from code inspection.
- New abstractions are added only when they remove real complexity.

## Sprint Contract Checklist

Before substantial work, define:

- Allowed files or directories to change.
- Files or areas that must not change.
- Existing behavior that must be preserved.
- Core invariants for the feature.
- RED-stage expected failure or current failing behavior.
- GREEN-stage verification command and passing output.
- Full regression command, usually `python scripts/verify_all.py`.
- Diff audit checklist.
- Failure rule: any out-of-contract change is treated as a failed sprint unless
  the user approves the expanded scope.

## Evaluator Checklist

An evaluator should verify:

- The implementation satisfies every completion condition.
- No unrelated files changed.
- Existing tests still pass or failures are clearly unrelated and reported.
- New behavior has focused test coverage when risk justifies it.
- Runtime behavior is checked for user-facing flows.
- The final report names what passed, what failed, and what risk remains.

## Recovery Rules

- If the same approach fails twice, change the approach instead of repeatedly
  patching symptoms.
- If the same bug recurs, inspect the source path deeply before editing again.
- If a change grows past the original scope, stop and re-confirm scope.
- If full verification fails on a pre-existing issue, report the exact failing
  test and do not silently change unrelated behavior.

## Project Application

For this repository, the harness maps to these concrete rules:

- Frontend-backend API JSON is the contract. Update backend handlers, frontend
  TypeScript interfaces, API docs, data model docs, workflow docs, and tests
  together.
- Backend code lives under `backend/`; backend deploy infrastructure lives under
  `infrastructure/backend/`.
- Disposable validation stacks live under `infrastructure/test-stacks/`.
- Server-rendered frontend list/dashboard pages should render safe fallback
  states for routine backend failures instead of producing Amplify/Next.js 500s.
- `scripts/verify_all.py` prints diff audit data before running tests.

## Report Format

Use this when closing a substantial task:

1. Changed files.
2. Where contract or regression rules were updated.
3. Verification commands and results.
4. Known failures that were not fixed.
5. Remaining risk.
