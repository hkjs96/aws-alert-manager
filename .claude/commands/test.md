# /test

Run project tests for the requested scope.

## Backend

```bash
cd backend && pytest tests/ -x -q --tb=short
```

Specific backend module:

```bash
cd backend && pytest tests/test_{module}.py -x -v --tb=short
```

## Frontend

```bash
cd frontend && npx vitest --run --reporter=verbose
```

Type check:

```bash
cd frontend && npx tsc --noEmit
```
