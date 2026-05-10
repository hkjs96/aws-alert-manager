# Stitch Prompt: IEP (Internal Engineer Platform)

Design a web application for an Internal Engineer Platform (IEP) — a unified portal for MSP infrastructure management services. The first service module is "Alarm Management" for AWS multi-account CloudWatch alarm configuration. The platform architecture must support adding new service modules (24x7 Monitoring & Ops, FinOps, Monthly Reports, Dashboards) without redesigning the shell.

## Users
24x7 NOC/SOC infrastructure engineers managing 50+ AWS accounts across multiple customer organizations. They work long shifts, need high information density, quick actions, and minimal clicks.

## Multi-Cloud Extensibility Note
Design primarily for AWS, but the data model should accommodate future multi-cloud support:
- "Cloud Account" concept (AWS Account / Azure Subscription / GCP Project)
- Resource types prefixed by provider internally (aws:EC2, azure:VM) but displayed cleanly in UI
- "Cloud Provider" filter available in all resource/alarm views
- For now, only AWS is active; other providers show as "coming soon"

---

## Global Shell Layout

### Top Bar (persistent across ALL service modules)
- Left: Platform logo "IEP" + current service module name with dropdown switcher
  - Service Switcher dropdown:
    - 🔔 Alarm Management (active)
    - 📊 24x7 Monitoring & Ops (coming soon)
    - 💰 FinOps (coming soon)
    - 📋 Monthly Reports (coming soon)
    - 📈 Dashboards (coming soon)
  - Each item: icon, name, one-line description, status badge
- Center: Global context filters (persist across pages AND service switch):
  - Customer dropdown (고객사)
  - Account dropdown (filtered by customer)
  - Service/Project dropdown (filtered by account)
- Right: Notification bell (count badge), User avatar + SSO menu

### Left Sidebar (changes per service module, collapsible to icon-only)

#### Platform-Level (always visible at sidebar top, separated by divider)
- 🏢 Platform Settings (gear icon)

#### Alarm Management Service Sidebar
- Dashboard (home icon)
- Resources (server icon)
- Alarms (bell icon)
- Maintenance Windows (wrench icon)
- Coverage Report (chart-bar icon)
- Bulk Import (upload icon)
- Alarm Templates (copy icon)
- Notification Routing (mail icon)
- Audit Log (history icon)
- Sync Status (refresh icon)
- Service Settings (sliders icon)

### SSO Login Page
- Corporate SSO login placeholder: company logo, "Sign in with SSO" button
- After login → platform home or last visited service

---

## Design System: Light Theme (high visibility, professional)

- Background: White (#ffffff) main, Light gray (#f8fafc) sidebar/cards
- Surface: White cards, subtle shadow (shadow-sm), borders (#e2e8f0)
- Primary accent: Blue (#2563eb) actions/links/active states
- Text: Dark gray (#1e293b) primary, Medium gray (#64748b) secondary
- Alarm states: Green (#16a34a)=OK, Red (#dc2626)=ALARM, Amber (#d97706)=INSUFFICIENT, Gray (#9ca3af)=Disabled/Muted
- Muted state: Purple (#7c3aed) badge with mute icon (distinct from disabled gray)
- Toggle switches: Blue=ON, Gray=OFF, prominent with labels
- Tables: White bg, light gray (#f1f5f9) alternating rows, sticky headers
- Sidebar: White/very light gray, active item = blue left border + light blue bg
- Typography: Inter/system sans-serif for UI, JetBrains Mono for resource IDs and values
- Responsive: desktop-first (1920px primary), functional at 1366px
- Forms: unsaved changes indicator (orange dot), confirmation for destructive actions
- Loading: skeleton screens for tables, spinner for actions

---

## Platform-Level: Platform Settings (공통, 모든 서비스 모듈이 공유)

### Tab: Customer Management (고객사 등록/관리)

#### Customer List
- Table: Name, Code, Cloud Accounts Count, Services/Projects Count, SLA Tier, Status, Created Date
- "Add Customer" button → Customer Onboarding Wizard


#### Customer Onboarding Wizard (운영환경 정의서 웹 플로우, 4 steps)

Step 1: Customer Info
- Name, Code (short ID), Description
- Primary contact: name, email, phone
- SLA tier: Basic / Standard / Premium (affects escalation timing)
- Service/Project list (add multiple: name + description + environment tag)

Step 2: Cloud Account Registration
- Add AWS accounts (future: Azure/GCP)
- Per account: Provider (AWS default), Account ID, Account Name, Role ARN, Region, Service/Project assignment
- "Test Connection" button per account (validates AssumeRole)
- Multiple accounts, each assigned to a service/project

Step 3: Default Alarm Configuration (운영환경 정의서 핵심)
- Customer-level default thresholds for alarm management
- Resource type tabs: EC2, RDS, AuroraRDS, ALB, NLB, TG, ElastiCache, Lambda... (all 30 types)
- Per resource type:
  | Metric | System Default | Customer Override | Unit | Dir | Description |
  |--------|---------------|-------------------|------|-----|-------------|
  | CPU    | 80%           | [90]              | %    | ▲   | CPU utilization |
  | Memory | 80%           | [ ]               | %    | ▲   | Memory usage |
  | Disk   | 80%           | [85]              | %    | ▲   | Disk per path |
- Empty = use system default
- "Copy from existing customer" dropdown
- "Apply template" button (use pre-built alarm template as baseline)

Step 4: Notification & Escalation Setup
- Default notification channels for this customer:
  - SNS topic ARN(s)
  - Email addresses (future)
  - Slack channel (future, placeholder)
- Escalation policy:
  - Level 1: Notify → [channel] after [0] minutes
  - Level 2: Escalate → [channel] after [15] minutes if unacknowledged
  - Level 3: Escalate → [channel] after [30] minutes if unacknowledged
- "Skip for now" option (can configure later)

Step 5: Review & Confirm
- Summary: customer info, accounts, alarm defaults, notification setup
- "Create Customer" button
- After creation: "Go to Customer Dashboard" or "Import Resources via Excel"

#### Customer Detail Page
- Overview: info, account count, resource count, alarm summary, SLA tier
- Tabs: Accounts, Default Thresholds (editable), Services/Projects, Escalation Policy, Notification Channels
- "Export Configuration" button (download as xlsx)


### Tab: Account Management
- Table: Provider (AWS icon), Account ID, Account Name, Customer, Role ARN, Connection Status (green/red dot), Last Sync, Resource Count
- "Add Account" form, "Test Connection", Bulk import from CSV

### Tab: User Management (placeholder)
- SSO user list, role assignment (Admin / Operator / Viewer)
- Per-customer access control (who can see/edit which customer)

### Tab: Notification Channels (공통 채널 등록)
- Channel list: Name, Type (SNS/Email/Slack/PagerDuty/Webhook), Target, Status
- "Add Channel" form: type selector → type-specific config
  - SNS: Topic ARN, Region
  - Email: address list (future)
  - Slack: workspace + channel (future, placeholder)
  - PagerDuty: service key (future, placeholder)
  - Webhook: URL + headers (future, placeholder)
- Channels are reusable across notification routing rules

---

## Service Module: Alarm Management

### Page 1: Dashboard
- 4 stat cards: Total Monitored Resources (trend arrow), Active Alarms (red if >0), Unmonitored Resources, Connected Accounts
- Alarm by state: horizontal stacked bar (OK/ALARM/INSUFFICIENT/MUTED)
- Alarm by resource type: donut chart (top 10)
- Recent alarm triggers: auto-refresh table (last 10)
  - Columns: Time, Customer, Account, Resource, Type, Metric, State Change, Value vs Threshold
- Resource distribution by type: horizontal bar chart
- Quick actions: "Scan All Resources", "View Orphan Alarms", "View Drift Report"
- Alarm drift summary card: count of DB config ≠ actual CloudWatch state
- Coverage summary card: overall monitoring coverage % with link to Coverage Report


### Page 2: Resources

#### Multi-Level Filter Bar (all combinable)
Row 1 - Context: Customer (multi), Service/Project (multi), Account (multi)
Row 2 - Resource: Type (multi, category-grouped: Compute/Database/Network/Storage/Application/Security), Region (multi), Tag key-value search, Free-text search (ID/Name)
Row 3 - Alarm/Metric: Monitoring status (All/Monitored/Not Monitored), Alarm state (All/Active Alarm/All OK/No Alarms/INSUFFICIENT/Muted), Metric filter (specific metrics)
- "Clear All Filters", "Save Filter Preset" buttons
- Active filter chips (removable) above table

#### Resource Table
- Checkbox column, Columns: Customer, Account, Resource ID, Name, Type (icon), Region, Monitoring (inline toggle), Active Alarms (count badge), Muted (mute icon if muted), Key Tags (chips)
- Sort any column, Pagination 25/50/100, Row click → Resource Detail
- "Select all [type]" when filtered by single type

#### Bulk Action Bar (sticky bottom, appears when ≥1 selected)
- "23 resources selected" + "Clear"
- Buttons: Enable Monitoring, Disable Monitoring, Configure Alarms, Apply Template, Mute Alarms, Export CSV

#### Bulk Alarm Config Drawer (slide right, 480px)
- Only same-type resources. Mixed types → warning banner.
- Selective Metric Update: checkbox per metric row to choose WHICH metrics to change
  | ☐ Select | Toggle | Metric | New Threshold | Unit | Dir | Current Range |
  |----------|--------|--------|---------------|------|-----|---------------|
  | ☑        | [ON]   | CPU    | [90]          | %    | ▲   | 70~90 (23 res)|
  | ☐        | -      | Memory | -             | %    | ▲   | 75~85 (23 res)|
- Unchecked metrics keep existing per-resource values
- "Current Range": min~max across selected resources
- Override warning for resources with custom thresholds
- "Preview Changes" → per-resource diff (old→new) for selected metrics only
- "Apply Selected Metrics" with confirmation


### Page 3: Alarms (alarm-centric view)

#### Multi-Level Alarm Filter Bar (all combinable)
Row 1 - Org: Customer (multi), Service/Project (multi), Account (multi)
Row 2 - Resource & Metric: Resource type (multi, category-grouped), Resource ID/Name search, Metric (multi, grouped: Saturation/Latency/Errors/Traffic), Alarm source (Standard/Custom/Import)
Row 3 - State: Alarm state (All/ALARM/OK/INSUFFICIENT/MUTED), Threshold range, Time range (last triggered: 1h/6h/24h/7d/30d/custom)
- Active filter chips, "Clear All", "Save Preset"

#### Alarm Summary Cards (clickable → filter table)
- Total Alarms, ALARM (red), OK (green), INSUFFICIENT (amber), MUTED (purple)

#### Alarm Table
- Columns: Customer, Account, Resource ID, Resource Name, Type, Metric, Alarm Name, Threshold, Current Value, State (badge), Source (Standard/Custom/Import), Muted (icon), Last State Change, Duration
- Current value colored red if exceeding threshold
- Sort any column, Pagination 25/50/100
- Row click → Resource Detail, Alarm Config tab, metric highlighted
- Bulk actions: Mute Selected, Unmute Selected, Export

### Page 4: Resource Detail

#### Header
- Breadcrumb: Customer > Account > Type > Name
- Resource ID (mono), Name, Type icon+label, Account, Region
- Large Monitoring toggle: [🟢 ON] / [⚫ OFF]
- Mute toggle: [🔇 Muted until 2024-03-15 06:00] / [🔔 Active]
- "Last Synced: 2h ago", "Force Sync Now" button

#### Tab: Alarm Configuration (default)

##### Standard Metrics Table (auto-populated by resource type)
| Toggle | Metric | CW Metric (gray) | Dir | Threshold | Unit | State | Current | Trend |
|--------|--------|-------------------|-----|-----------|------|-------|---------|-------|
| [ON]   | CPU    | CPUUtilization    | ▲   | [80]      | %    | 🟢 OK | 23.4%   | sparkline |
| [ON]   | Memory | mem_used_percent  | ▲   | [80]      | %    | 🟢 OK | 45.2%   | sparkline |
| [ON]   | Disk / | disk_used_percent | ▲   | [80]      | %    | 🔴 ALARM | 82.1% | sparkline |
| [OFF]  | Disk /data | disk_used_percent | ▲ | [80]   | %    | ⚫ OFF | 55.3%  | sparkline |

- 30 resource types supported with type-specific metrics
- Direction: ▲ high-is-bad, ▼ low-is-bad
- Current value red if exceeding threshold
- Threshold source indicator: tiny label showing "System" / "Customer" / "Custom" origin


##### Custom/Dynamic Metrics Section
- "Add Custom Metric" button → form: Metric name, Threshold, Direction (▲/▼), Unit
  - Auto-resolves namespace/dimensions via CloudWatch list_metrics
  - Warning if metric not found: "Alarm will be INSUFFICIENT_DATA until metric data appears"
- Existing custom alarms table:
  | Metric | Namespace | Threshold | Dir | State | Current | Source | Actions |
  |--------|-----------|-----------|-----|-------|---------|--------|---------|
  | CommitLatency | AWS/RDS | 0.05 | ▲ | 🟢 OK | 0.012s | Tag | View |
  | custom_errors | CustomApp | 10 | ▲ | 🟡 INSUF | - | UI | Edit/Del |
- Source: Tag (read-only, edit via resource tag), UI (editable), Import (editable)

##### Actions (sticky bottom)
- "Save Changes" (disabled until changes), "Reset to Defaults", "Apply Customer Defaults"
- Unsaved changes indicator (orange dot)

#### Tab: Metrics
- Chart grid (2 cols), threshold line (dashed red), time range: 1h/6h/24h/7d/30d
- Click chart → expand full-width

#### Tab: Event Timeline
- Alarm state changes, threshold mods, monitoring toggles, tag changes, mute/unmute events
- Timestamp, icon, description, user. Filter by event type.

#### Tab: Alarm Comparison
- Compare thresholds with same-type resources side-by-side
- Highlight differences, "Apply this config to others" button

### Page 5: Maintenance Windows (점검 모드 / 알람 뮤트)

#### Active Maintenance Windows (top section)
- Cards showing currently active windows with countdown timer
- "End Early" button per window

#### Maintenance Window List
- Table: Name, Scope (Customer/Account/Resource), Target, Schedule, Duration, Status (Active/Scheduled/Completed), Created By
- "Create Window" button → form:

##### Create Maintenance Window Form
- Name: descriptive label
- Scope selector:
  - Customer-wide: select customer → all resources muted
  - Account-wide: select account(s) → all resources in those accounts muted
  - Resource-specific: search and select specific resources
  - Resource type: select type (e.g., all EC2 in account X)
- Schedule:
  - One-time: start datetime + duration
  - Recurring: cron pattern (e.g., every Wednesday 02:00-04:00 KST)
- Alarm behavior during window:
  - Mute notifications only (alarms still evaluate, just no SNS/notification)
  - Suppress alarms entirely (alarms set to OK during window)
- Notes: free-text for reason (e.g., "Monthly patching", "DB migration")

#### Calendar View (toggle)
- Monthly calendar showing scheduled maintenance windows as colored blocks
- Click block → view/edit details


### Page 6: Coverage Report (알람 커버리지 리포트)

#### Overall Coverage Summary
- Big number: "87% monitoring coverage" with trend
- Donut chart: Monitored vs Unmonitored resources

#### Coverage by Customer
- Table: Customer, Total Resources, Monitored, Coverage %, Trend
- Click row → drill down to that customer's coverage

#### Coverage by Resource Type (heatmap)
- Grid: rows = resource types, columns = customers (or accounts)
- Cell color: green (>90%), yellow (50-90%), red (<50%)
- Cell shows percentage

#### SRE Golden Signal Coverage
- Per resource type, show which signals are covered:
  | Type | Latency | Traffic | Errors | Saturation | Overall |
  |------|---------|---------|--------|------------|---------|
  | EC2  | -       | -       | ✅     | ✅✅✅    | 75%     |
  | RDS  | ✅✅    | -       | -      | ✅✅✅✅  | 85%     |
  | ALB  | ✅      | ✅      | ✅     | -          | 75%     |
- Helps identify monitoring gaps

#### Unmonitored Resources List
- Table of resources without Monitoring=on, grouped by customer/account
- "Enable Monitoring" bulk action

### Page 7: Bulk Import (xlsx)

#### Import Flow (3-step stepper)

Step 1: Upload
- Drag-drop .xlsx upload zone
- "Download Template" → pre-formatted xlsx:
  - Sheet per resource type, columns: Resource ID, Monitoring (on/off), metric columns with thresholds
  - Example rows with defaults, "off" = disable alarm, empty = use default
  - Instruction sheet with format guide

Step 2: Validation & Preview
- Row-by-row: ✅ Valid, ⚠️ Warning, ❌ Error
- Errors: "Resource not found", "Invalid threshold", "Unknown metric"
- Warnings: "Will overwrite existing custom config"
- Summary cards: Total/Valid/Warnings/Errors
- "Fix and Re-upload" or "Proceed with Valid Rows"

Step 3: Apply & Results
- Confirmation with count, progress bar
- Results: Resource ID, Status (Success/Failed), Details
- "Export Results" as xlsx

#### Import History
- Past imports: Date, User, File, Total/Success/Failed, Status
- Click → detailed results


### Page 8: Alarm Templates
- Table: Name, Resource Type, Metrics Count, Created By, Last Modified, Usage Count
- "Create Template": name, resource type, description, metrics config (same as Resource Detail form)
- Template detail: view/edit, see which resources use it
- "Apply Template": select resources → apply thresholds
- Pre-built: "Web Server Standard", "Database Standard", "Network Standard"

### Page 9: Notification Routing (알람 → 어디로 보낼지)

#### Routing Rules Table
- Table: Priority, Name, Conditions, Channels, Status (Active/Disabled), Actions
- Rules evaluated top-to-bottom, first match wins (or all matches, configurable)

#### Create/Edit Routing Rule
- Rule name
- Conditions (all combinable, AND logic):
  - Customer: select customer(s) or "All"
  - Account: select account(s) or "All"
  - Resource type: select type(s) or "All"
  - Alarm state: ALARM / OK / INSUFFICIENT / Any
  - Metric: select specific metrics or "All"
  - Severity: Critical / Warning / Info (mapped from alarm state + metric importance)
- Target channels (multi-select from registered Notification Channels):
  - SNS topic(s)
  - Email (future)
  - Slack channel (future)
  - PagerDuty (future)
  - Webhook (future)
- Escalation (optional):
  - Enable escalation: yes/no
  - Level 1: notify [channels] immediately
  - Level 2: escalate to [channels] after [15] min if unacknowledged
  - Level 3: escalate to [channels] after [30] min if unacknowledged
- "Test Rule" button: sends test notification to configured channels

#### Default Rule
- Catch-all rule at bottom: "All unmatched alarms → default SNS topic"
- Cannot be deleted, only edited

### Page 10: Audit Log
- Columns: Timestamp, User, Action (Created/Modified/Deleted/Toggled/Muted/Unmuted/Imported), Customer, Account, Resource, Metric, Old Value, New Value, Source (UI/API/Auto-sync/Import)
- Filter: date range, user, action type, resource type, customer, account
- Export CSV, Detail view with before/after diff


### Page 11: Sync Status (시스템 헬스)

#### System Health Overview
- Cards: Last Daily Sync (time + status), Remediation Handler (status), DLQ Messages (count, red if >0), API Health

#### Account Connection Status
- Table: Account ID, Customer, Provider, Connection Status (green/red), Last Successful Sync, Failed Syncs (24h), Resources Synced, Error Details
- "Test Connection" per account, "Retry Failed" button

#### Sync History
- Table: Timestamp, Type (Daily/Remediation/Manual/API), Accounts Processed, Resources Processed, Alarms Created/Updated/Deleted, Errors, Duration
- Click → detailed log

#### DLQ Monitor
- Current DLQ depth with chart (last 24h)
- Failed messages table: Timestamp, Account, Resource, Event Type, Error, Retry Count
- "Reprocess" per message or bulk reprocess

#### Drift Detection
- Resources where DB config ≠ actual CloudWatch alarm
- Table: Resource, Metric, Expected Threshold, Actual Threshold, Drift Type (missing/mismatch/extra)
- "Reconcile" per resource or bulk

### Page 12: Service Settings (Alarm Management 전용)

#### Tab: Default Thresholds
- Hierarchy: System Defaults → Customer Overrides → Account Overrides → Resource Tags
- Select level: System (read-only) / Customer (dropdown) / Account (dropdown)
- Resource type tabs, threshold table:
  | Metric | System Default | Customer Override | Account Override | Effective |
  |--------|---------------|-------------------|-----------------|-----------|
  | CPU    | 80%           | [90]              | [ ]             | 90%       |
- Visual indicator showing which level provides effective value

#### Tab: Resource Grouping
- Tag-based groups (e.g., "Web Servers", "Production DBs")
- Create: name + tag filter rules (Environment=prod AND Type=EC2)
- Group view: aggregate alarm status, apply config to group

#### Tab: Integrations (placeholder)
- Slack, PagerDuty, Custom Webhook cards (all "coming soon")

---

## Supported Resource Types (30 types, category-grouped)

- Compute: EC2, Lambda, ECS, SageMaker
- Database: RDS, AuroraRDS, DocDB, ElastiCache, DynamoDB
- Network: ALB, NLB, CLB, TG, NAT, VPN, Route53, DX, CloudFront
- Storage: S3, EFS, Backup
- Application: APIGW, SQS, MSK, SNS, MQ
- Security: WAF, ACM, OpenSearch

## Tech Stack Hint
React + TypeScript, Tailwind CSS, TanStack Table, Recharts, React Router (nested routes per service module for future micro-frontend), SheetJS/xlsx for import, date-fns for time handling
