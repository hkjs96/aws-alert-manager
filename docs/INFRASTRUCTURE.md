# Infrastructure

Infrastructure is split by lifecycle and ownership.

## Directories

| Path | Purpose |
| --- | --- |
| `infrastructure/backend/` | Deployable backend AWS stack. |
| `infrastructure/test-stacks/` | Disposable validation and experiment stacks. |
| `infrastructure/frontend/` | Frontend deployment notes and hosting decisions. |

## Rules

- Backend application code stays under `backend/`.
- Backend deployment templates stay under `infrastructure/backend/`.
- Test stacks must not be treated as production deployment templates.
- Frontend deployment is infrastructure conceptually, but tool-required files may
  stay at root or under `frontend/` when Amplify or another host requires it.
