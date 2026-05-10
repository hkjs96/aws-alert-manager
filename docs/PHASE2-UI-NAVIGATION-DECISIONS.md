# Phase2 UI Navigation & Filter Design Decisions

> Created: 2026-04-10
> Status: PENDING (decide after backend integration with real data)

## 1. GlobalFilterBar vs Page-level Filter Duplication

### Current State
- TopBar has GlobalFilterBar (Customer / Account / Service)
- Dashboard, Resources, Alarms each have their own Customer/Account filters
- Duplicate functionality → user confusion

### Options

| Option | Description | Pros | Cons |
|--------|-------------|------|------|
| A. Remove global | Page-level filters only | Simple, pages independent | Filter resets on navigation |
| B. Remove page-level | Global only + pages keep Type/Search | Context persists, MSP pattern | Global state management needed |
| C. Keep both | Maintain current, clarify roles | No code change | Duplication continues |

### Decision Criteria
- 10+ customers → Option B (global context essential)
- 3-5 customers → Option A (page-level sufficient)
- Decide after real data testing

### Current Action
- No code changes. Decide after backend integration.


## 2. Settings Tab Restructuring

### Problem
- "Settings" is too vague → Customer mgmt, Account onboarding, Threshold policies all in one page
- Users can't predict what's inside "Settings"

### Proposals

```
Current:
  Dashboard | Resources | Alarms | Settings
                                    ├── Customer List
                                    ├── Account Registry
                                    └── Default Thresholds

Proposal A — Separate Accounts page:
  Dashboard | Resources | Alarms | Accounts | Settings
                                    ├── Customer CRUD        Settings:
                                    ├── Account connect/test   ├── Threshold Policies
                                    └── Region management      └── General (notifications etc)

Proposal B — Customer-centric:
  Dashboard | Resources | Alarms | Customers | Settings
                                    ├── Customer CRUD        Settings:
                                    ├── Linked Accounts        ├── Threshold Policies
                                    └── Customer overrides     └── General

Proposal C — Administration (rename + keep tabs):
  Dashboard | Resources | Alarms | Administration
                                    ├── Customers (tab)
                                    ├── Accounts (tab)
                                    ├── Threshold Policies (tab)
                                    └── General Settings (tab)
```

### Analysis

Proposal A (Separate Accounts):
- Account onboarding is a key workflow → better accessibility as standalone menu
- Settings becomes purely policy/config → clearer meaning
- Con: 5 menu items

Proposal B (Customer-centric):
- Fits MSP business model (customer is top-level entity)
- Natural flow: Customer → Accounts → Threshold overrides
- Con: Viewing all accounts across customers becomes harder

Proposal C (Administration rename):
- Minimal change: "Settings" → "Administration" + keep tab structure
- Meaning is clearer ("manage" vs "configure")
- Con: Still many features in one page

### Recommendation
- Short-term: Proposal C (rename to Administration) — minimal code change
- Mid-term: Proposal A (separate Accounts) — when multi-account scales up
- Long-term: Proposal B (Customer-centric) — when 50+ customers, platform core promotion


## 3. TopBar Composition

### Current
```
[Logo] [GlobalFilterBar: Customer | Account | Service] [User Avatar]
```

### Proposals (after filter role clarification)
```
Option 1: Keep global context
[Logo] [Customer select] [Account select] ─── [Service switcher] [Avatar]

Option 2: Remove global context
[Logo] ─── [Service switcher slot] [Avatar]
(Filters handled per-page)

Option 3: Hybrid
[Logo] [Customer select only] ─── [Service switcher] [Avatar]
(Account/Type/Search per-page)
```

### Deferred Because
- Service switcher (Alarm Manager / 24x7 Monitoring / FinOps) is post-Phase2
- Customer selection's global impact scope depends on backend integration
- Can't judge with 3 mock customers


## 4. Decision Timeline

| When | Decision | Trigger |
|------|----------|---------|
| Backend API integration complete | GlobalFilterBar keep/remove | Real data UX testing |
| 10+ customers | Settings → Administration rename | Menu complexity increase |
| Multi-account scaling | Separate Accounts page | Account onboarding frequency |
| 24x7 monitoring service added | Service switcher introduction | 2+ services |


## 5. Data Model: Customer → Project → Account Hierarchy

### Current Model (flat)
```
Customer (customer_id, name, provider)
  └── Account (account_id, customer_id, role_arn, regions)
```

### Proposed Model (3-tier hierarchy)
```
Customer (고객사)
  └── Project / Service (프로젝트 단위)
        ├── Production Account (환경: prod)
        ├── Staging Account (환경: staging)
        └── Development Account (환경: dev)
```

### Example
```
Acme Corp (Customer)
  ├── Payment Service (Project)
  │     ├── prod: 882311440092 (us-east-1)
  │     └── staging: 440911228833 (us-west-2)
  └── Analytics Platform (Project)
        ├── prod: 112233445566 (ap-northeast-2)
        └── dev: 998877665544 (us-east-1)
```

### New Entity: Project
```typescript
interface Project {
  project_id: string;
  customer_id: string;
  name: string;           // e.g. "Payment Service"
  description?: string;
  environment_tags?: string[];  // e.g. ["prod", "staging", "dev"]
}

// Account gets a project_id field
interface Account {
  account_id: string;
  customer_id: string;
  project_id?: string;     // NEW — links to Project
  environment?: string;    // NEW — "prod" | "staging" | "dev"
  name: string;
  role_arn: string;
  regions: string[];
  connection_status: "connected" | "failed" | "untested";
}
```

### Filter Cascade
```
Customer → Project → Account (Environment) → Resource Type → Search
```

### UI Impact
- Sidebar: Dashboard | Resources | Alarms | Customers (with Projects + Accounts inside)
- Settings: Threshold Policies + General only
- GlobalFilterBar: Customer → Project → Account cascade
- Resources/Alarms page filters: inherit from global or override locally

### Threshold Override Hierarchy (updated)
```
Priority (highest first):
1. Resource-level override (specific resource, specific metric)
2. Project-level override (all resources in project)
3. Customer-level override (all resources for customer)
4. System default (HARDCODED_DEFAULTS)
```

### Implementation Notes
- Backend: Add `projects` DynamoDB table, add `project_id` to accounts table
- Frontend: Add Project entity to types, update Customers page with nested Projects
- Migration: Existing accounts without project_id → assign to "Default" project per customer
- This is a significant change — implement as separate Spec when ready
