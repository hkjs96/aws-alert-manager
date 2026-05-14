# /deploy

Run verification before any deployment.

## 1. Backend Tests

```bash
cd backend && pytest tests/ -x -q --tb=short
```

## 2. Frontend Checks

Run when frontend files changed:

```bash
cd frontend && npx vitest --run && npx tsc --noEmit
```

## 3. Deployment

Ask for explicit confirmation before deploying.

Backend stack template:

```text
infrastructure/backend/template.yaml
```

Backend source packages are built from `backend/`.
