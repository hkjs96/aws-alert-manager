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

Backend stack deploy (CLI):

```bash
python scripts/deploy-backend-stack.py            # git diff 기반 변경 아티팩트만
python scripts/deploy-backend-stack.py --all-artifacts
python scripts/deploy-backend-stack.py --changed-path backend/common/alarm_registry.py
python scripts/deploy-backend-stack.py --dry-run  # 배포 계획만 출력
```

Defaults and env-var overrides: see `guides/OPERATIONS.md`.
Backend stack template: `infrastructure/backend/template.yaml`.
Backend source packages are built from `backend/`.
