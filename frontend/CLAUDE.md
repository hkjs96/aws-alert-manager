# Frontend Claude Guide

These rules apply to `frontend/**/*.{ts,tsx,css}`. The shared root
`../AGENTS.md` rules and the root `../CLAUDE.md` guide also apply.

## Frontend API Contract Rules

When a frontend change touches API data:

- Check `docs/API-CONTRACT.md` before changing fetch code or component props.
- Distinguish backend-supported resources from frontend-active resources.
  Backend-wide type contracts use `SUPPORTED_RESOURCE_TYPES`; UI filters,
  settings, and primary workflows currently use
  `FRONTEND_INTEGRATION_RESOURCE_TYPES`.
- Keep API JSON fields as `snake_case` until an explicit frontend DTO mapping is
  created.
- Keep UI option DTOs local and named clearly. For example, `{id, name,
  customerId}` must be mapped from `{account_id, name, customer_id}` in one
  place.
- Update `frontend/types/index.ts` or `frontend/types/api.ts` in the same change
  as any API contract change.
- Update `frontend/lib/server/data.ts` fallback objects with the same keys as
  the API contract.
- Dashboard, list, and settings Server Components must catch backend fetch
  failures and render empty or zero-state fallback data.
- Do not use `useSearchParams()` in components rendered from the root layout
  unless the Suspense/CSR bailout behavior is explicitly tested in production
  SSR.

## Next.js Rules

- Default to Server Components. Add `"use client"` only at interaction leaves.
- Do not put `"use client"` in `page.tsx` or `layout.tsx`.
- Fetch initial page data in Server Components through
  `frontend/lib/server/data.ts`.
- Client Components should use `frontend/lib/api-functions.ts` or local route
  handlers.
- Parallelize independent page data with `Promise.all()`.
- Keep API failure handling explicit. SSR pages should not crash for routine
  backend failures.
- Do not collapse every fetch failure into one "connection failed" message.
  Distinguish HTTP error responses (surface the status/backend `code`) from
  network failures, and keep "request failed" separate from a job/resource whose
  own status is `failed`. See anti-patterns AP-16. A generic message here hid a
  real backend 500 (`GET /jobs/{id}` Decimal serialization, AP-17).

## TypeScript Rules

- `strict: true` is required.
- Do not introduce `any`.
- Prefer named exports except for Next.js `page.tsx` and `layout.tsx` default
  exports.
- Keep component props narrow. Do not pass full backend records when a smaller
  DTO is enough.
- Extract shared constants to `frontend/lib/constants.ts`.

## Security Rules

- Do not expose server-only secrets with `NEXT_PUBLIC_`.
- Client props must not include credentials, role secrets, API keys, or raw
  sensitive backend records.
- Validate user-controlled payloads before sending them to backend mutation
  endpoints.

## Verification

Run these when the environment allows child processes:

```bash
npx tsc --noEmit
npm test
```

If a command fails, classify the cause as implementation bug, test bug, or local
environment issue.
