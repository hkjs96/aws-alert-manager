# Stitch Prompt: AWS Cloud Monitoring Alarm Management Web App

Design a web application for managing AWS CloudWatch alarms across multiple accounts and customers. This is a standalone alarm management tool built for MSP (Managed Service Provider) engineers, with architecture designed to later integrate into a larger Internal Engineer Platform (IEP).

## Users
Infrastructure engineers at an MSP company managing 50+ AWS accounts across multiple customer organizations. They configure alarm thresholds, monitor alarm states, and maintain alarm health across all customer environments.

## Architecture Note
- Standalone app now, but designed to become a "service module" in a future IEP portal
- Customer/Account data model should be API-accessible for future platform integration
- Left sidebar navigation can later be nested under a service switcher
- Global filters (Customer/Account) will become platform-level shared context

---

## Layout

### Top Bar
- Left: App logo "Alarm Manager"
- Center: Global context filters (cascading):
  - Customer dropdown (고객사)
  - Account dropdown (AWS 계정, filtered by customer)
  - Service/Project dropdown (filtered by account)
  - These filters affect ALL pages and persist across navigation
- Right: Notification bell, User avatar + logout

### Left Sidebar (collapsible to icon-only)
- Dashboard (home)
- Resources (server)
- Alarms (bell)
- Mute Rules (volume-x)
- Coverage (bar-chart)
- Import (upload)
- Templates (copy)
- Notifications (mail)
- Audit Log (history)
- Sync Status (refresh)
- Settings (gear)

---

## Design System: Light Theme

- Background: White (#ffffff) main, Light gray (#f8fafc) sidebar/cards
- Surface: White cards, subtle shadow, borders (#e2e8f0)
- Accent: Blue (#2563eb) for actions/active states
- Text: Dark gray (#1e293b) primary, Medium gray (#64748b) secondary
- Alarm states: Green (#16a34a)=OK, Red (#dc2626)=ALARM, Amber (#d97706)=INSUFFICIENT, Gray (#9ca3af)=Disabled, Purple (#7c3aed)=Muted
- Tables: White bg, alternating light gray rows, sticky headers
- Toggle switches: Blue=ON, Gray=OFF
- Typography: System sans-serif for UI, Monospace for IDs/values
- Desktop-first (1920px), functional at 1366px

---

## Pages

### 1. Dashboard
- Stat cards: Monitored Resources, Active Alarms (red if >0), Unmonitored, Accounts
- Alarm by state: stacked bar (OK/ALARM/INSUFFICIENT/MUTED)
- Alarm by resource type: donut chart
- Recent triggers: table (Time, Customer, Account, Resource, Metric, State Change, Value vs Threshold)
- Quick actions: Scan All, Orphan Alarms, Drift Report
- Coverage summary: overall % with link to Coverage page


### 2. Resources

#### Filter Bar (all combinable, 3 rows)
Row 1: Customer (multi), Service/Project (multi), Account (multi)
Row 2: Resource type (multi, grouped: Compute/Database/Network/Storage/Application/Security), Region (multi), Tag key=value search, Free-text search
Row 3: Monitoring (All/On/Off), Alarm state (All/Active/OK/None/INSUFFICIENT/Muted), Metric filter
- Active filter chips (removable), Clear All, Save Preset

Resource types (30, category-grouped):
- Compute: EC2, Lambda, ECS, SageMaker
- Database: RDS, AuroraRDS, DocDB, ElastiCache, DynamoDB
- Network: ALB, NLB, CLB, TG, NAT, VPN, Route53, DX, CloudFront
- Storage: S3, EFS, Backup
- Application: APIGW, SQS, MSK, SNS, MQ
- Security: WAF, ACM, OpenSearch

#### Table
- Checkbox, Customer, Account, Resource ID, Name, Type (icon), Region, Monitoring (toggle), Alarms (badge), Muted (icon), Tags
- Sort any column, Pagination 25/50/100, Row click → Detail
- "Select all [type]" when single-type filtered

#### Bulk Actions (sticky bottom bar when selected)
- Count + Clear, Enable/Disable Monitoring, Configure Alarms, Apply Template, Mute, Export CSV

#### Bulk Alarm Drawer (same-type only, slide right 480px)
- Selective metric update: checkbox per metric to choose WHICH to change
  | ☐ | Toggle | Metric | New Threshold | Unit | Dir | Current Range |
  |---|--------|--------|---------------|------|-----|---------------|
  | ☑ | [ON]   | CPU    | [90]          | %    | ▲   | 70~90 (23 res)|
  | ☐ | -      | Memory | -             | %    | ▲   | 75~85 (23 res)|
- Unchecked = keep existing values per resource
- Override warning, Preview Changes (per-resource diff), Apply Selected

### 3. Alarms (alarm-centric view)

#### Filter Bar (all combinable)
Row 1: Customer (multi), Service/Project (multi), Account (multi)
Row 2: Resource type (multi), Resource search, Metric (multi, grouped: Saturation/Latency/Errors/Traffic), Source (Standard/Custom/Import)
Row 3: State (All/ALARM/OK/INSUFFICIENT/MUTED), Threshold range, Time range (1h/6h/24h/7d/30d)
- Filter chips, Clear All, Save Preset

#### Summary Cards (clickable → filter)
- Total, ALARM (red), OK (green), INSUFFICIENT (amber), MUTED (purple)

#### Table
- Customer, Account, Resource ID, Name, Type, Metric, Alarm Name, Threshold, Current Value, State, Source, Muted, Last Change, Duration
- Sort, Paginate, Row click → Resource Detail with metric highlighted
- Bulk: Mute/Unmute Selected, Export


### 4. Resource Detail

#### Header
- Breadcrumb: Customer > Account > Type > Name
- Resource ID (mono), Name, Type, Account, Region
- Monitoring toggle (large): [🟢 ON] / [⚫ OFF]
- Mute toggle: [🔇 Muted — rule: "배포 점검" until 06:00] / [🔔 Active]
- Mute info: if muted, shows which mute rule is affecting this resource + link to rule
- Last Synced, Force Sync button

#### Tab: Alarm Config (default)
Standard metrics table (auto by resource type):
| Toggle | Metric | CW Metric (gray) | Dir | Threshold | Unit | State | Current | Source | Trend |
|--------|--------|-------------------|-----|-----------|------|-------|---------|--------|-------|
| [ON]   | CPU    | CPUUtilization    | ▲   | [80]      | %    | 🟢    | 23.4%   | System | spark |
| [ON]   | Disk / | disk_used_percent | ▲   | [80]      | %    | 🔴    | 82.1%   | Custom | spark |

- Source label: System / Customer / Custom (shows threshold origin)
- 30 resource types with type-specific metrics

Custom metrics section:
- "Add Custom Metric" → Metric name, Threshold, Direction, Unit
  - Auto-resolves via CloudWatch list_metrics, warns if not found
- Existing custom alarms table: Metric, Namespace, Threshold, Dir, State, Current, Source (Tag/UI/Import), Actions
  - Tag-sourced = read-only, UI/Import = editable

Actions: Save Changes, Reset to Defaults, Apply Customer Defaults (unsaved indicator)

#### Tab: Metrics
- Chart grid (2 cols), threshold line, time range 1h/6h/24h/7d/30d

#### Tab: Timeline
- Alarm state changes, threshold mods, toggles, mute/unmute, tag changes

#### Tab: Compare
- Side-by-side thresholds with same-type resources, highlight diffs

### 5. Mute Rules (알람 뮤트 관리)

CloudWatch Alarm Mute Rules를 UI에서 관리. 뮤트 중에도 알람은 계속 평가/상태 전환되지만, 액션(SNS 알림 등)만 억제됨.

#### Active Mute Rules (top section)
- Cards showing currently active rules with remaining time countdown
- Muted alarm count per rule
- "Deactivate" button per rule

#### Mute Rules List
- Table: Name, Target (alarm name pattern / tag filter / all), Schedule Type (One-time / Recurring), Next Active, Duration, Status (Active/Scheduled/Expired), Created By
- "Create Mute Rule" button → form:

##### Create Mute Rule Form
- Name, Description
- Target alarms:
  - All alarms in account(s): select account(s)
  - By alarm name pattern: prefix match or wildcard (e.g., "[EC2]*", "[RDS] prod-*")
  - By tag filter: resource tag match (e.g., Environment=staging)
  - By resource: search and select specific resources → mute all their alarms
  - By customer: select customer → mute all alarms across their accounts
- Schedule:
  - One-time: start datetime + end datetime (timezone selector)
  - Recurring: cron expression or form (every day/week/month, specific days, duration)
  - Optional expiry date for recurring rules
- Notes: reason text (e.g., "배포 중", "DB 마이그레이션", "정기 점검")

#### Mute History
- Past mute events: Start, End, Rule Name, Alarms Muted Count, Created By, Reason

### 6. Coverage Report

- Overall: big % number + donut (Monitored vs Unmonitored)
- By customer: table (Customer, Total, Monitored, Coverage %, Trend)
- By resource type: heatmap grid (rows=types, cols=customers, cell=% with color green/yellow/red)
- SRE golden signals: per type, Latency/Traffic/Errors/Saturation coverage
- Unmonitored list: resources without Monitoring=on, bulk Enable action

### 7. Import (xlsx)

Step 1: Upload - drag-drop xlsx, Download Template (sheet per type, metric columns)
Step 2: Validate - row status (✅⚠️❌), error details, summary cards, Proceed/Re-upload
Step 3: Apply - confirmation, progress, results table, Export Results
Import History: past imports table (Date, User, File, Success/Failed)

### 8. Templates
- Table: Name, Type, Metrics, Created By, Modified, Usage Count
- Create: name, type, description, metrics config
- Apply to selected resources
- Pre-built: Web Server / Database / Network Standard

### 9. Notification Routing (알람 액션 채널 설정)

알람이 울렸을 때 어디로 알림을 보낼지 설정. CloudWatch Alarm Actions(SNS)를 UI에서 관리.

#### Tab: Channels (알림 대상 등록)
- Table: Name, Type (SNS/Email/Slack/PagerDuty/Webhook), Target, Region, Status (Connected/Error)
- "Add Channel" form:
  - SNS: Topic ARN, Region, "Test" button (sends test message)
  - Email: address list (future placeholder)
  - Slack: workspace + channel (future placeholder)
  - PagerDuty: service key (future placeholder)
  - Webhook: URL + headers (future placeholder)
- Channels are reusable across routing rules
- Per-channel test button to verify connectivity

#### Tab: Routing Rules (조건 → 채널 매핑)
- Table: Priority (drag to reorder), Name, Conditions summary, Channels, Status (Active/Disabled)
- Rules evaluated top-to-bottom, first match wins

##### Create/Edit Rule
- Name
- Conditions (AND logic, all combinable):
  - Customer: select or "All"
  - Account: select or "All"
  - Resource type: select or "All"
  - Metric: select specific metrics or "All"
  - Alarm state trigger: ALARM only / OK→ALARM / Any state change
- Target channels: multi-select from registered channels
  - Primary: always notified
  - Escalation (optional):
    - L1: notify [primary channels] immediately
    - L2: notify [escalation channels] after [15] min if unacknowledged
    - L3: notify [escalation channels] after [30] min if unacknowledged
- "Test Rule" button: simulates a matching alarm and sends test to configured channels

#### Default Rule (catch-all)
- Bottom of rule list, cannot be deleted
- "All unmatched alarms → [default SNS topic]"
- Editable: can change the default channel

#### Per-Resource Override
- On Resource Detail page, option to override routing for specific resource
- "Use custom notification" toggle → select channels directly
- Overrides routing rules for that resource only

### 10. Audit Log
- Timestamp, User, Action, Customer, Account, Resource, Metric, Old→New, Source (UI/API/Sync/Import)
- Filter: date, user, action, type, customer. Export CSV. Diff view.

### 11. Sync Status

- System health cards: Last Daily Sync, Remediation Handler, DLQ depth, API health
- Account connections: table with status, last sync, errors, Test/Retry buttons
- Sync history: table (time, type, accounts, resources, alarms CRUD, errors, duration)
- DLQ monitor: depth chart, failed messages table, Reprocess button
- Drift detection: DB vs CloudWatch mismatches, Reconcile button


### 12. Settings

#### Tab: Customers
- Table: Name, Code, Accounts, Services, SLA Tier, Status
- Customer Onboarding Wizard (4 steps):
  1. Info: Name, Code, Contact, SLA tier, Services/Projects
  2. Accounts: Add AWS accounts (ID, Name, Role ARN, Region, Test Connection)
  3. Default Alarms (운영환경 정의서): Resource type tabs, per-type threshold table
     | Metric | System Default | Customer Override | Unit | Dir |
     |--------|---------------|-------------------|------|-----|
     | CPU    | 80%           | [90]              | %    | ▲   |
     - Copy from existing customer, Apply template as baseline
  4. Review & Create
- Customer Detail: overview, tabs (Accounts, Thresholds, Resources, Alarms)
- Export config as xlsx

#### Tab: Accounts
- Table: Account ID, Name, Customer, Role ARN, Status, Last Sync, Resources
- Add Account, Test Connection, Bulk import CSV

#### Tab: Default Thresholds
- Hierarchy: System → Customer → Account → Resource Tag (highest priority)
- Level selector, Resource type tabs, threshold table with effective value indicator

#### Tab: Integrations (placeholder)
- Slack, PagerDuty, Webhook cards (coming soon)

---

## Multi-Cloud Extensibility (future-proofing, not implemented now)
- Data model includes `provider` field (default: "aws")
- Account concept generalizable: AWS Account / Azure Subscription / GCP Project
- Resource type internally prefixed (aws:EC2) but displayed clean
- "Cloud Provider" filter slot reserved in filter bars
- Only AWS active now

## Tech Stack Hint
React + TypeScript, Tailwind CSS, TanStack Table, Recharts, React Router, SheetJS/xlsx
