# Stitch Prompts — Alarm Manager Web App (English)

Use these prompts in order. Each builds on the previous.

---

## Prompt 0: Design System Tokens

```
Design system for a light-theme AWS monitoring alarm management web app.

Colors:
- Background: #ffffff (main content), #f8fafc (sidebar, card surfaces)
- Accent: #2563eb (primary actions, active nav, links)
- Text: #1e293b (primary), #64748b (secondary), #94a3b8 (tertiary/placeholder)
- Alarm state badges:
  OK = #16a34a (green bg, white text)
  ALARM = #dc2626 (red bg, white text)
  INSUFFICIENT = #d97706 (amber bg, white text)
  DISABLED = #9ca3af (gray bg, white text)
  MUTED = #7c3aed (purple bg, white text, with mute icon)
- Severity badges (outline style, colored border + text, white bg):
  SEV-1 = #dc2626 border+text (red outline, "SEV-1 Critical")
  SEV-2 = #ea580c border+text (orange outline, "SEV-2 High")
  SEV-3 = #d97706 border+text (amber outline, "SEV-3 Medium")
  SEV-4 = #2563eb border+text (blue outline, "SEV-4 Low")
  SEV-5 = #6b7280 border+text (gray outline, "SEV-5 Info")
  Severity is assigned per metric based on business impact when in ALARM state. Auto-assigned from system defaults, read-only in Phase 1 UI. Override capability planned for Phase 2.
- Borders: #e2e8f0
- Hover: #f1f5f9 (table rows, sidebar items)

Typography:
- UI text: system-ui, -apple-system, sans-serif (Inter if available)
- Resource IDs, metric values, thresholds: JetBrains Mono, monospace
- Font sizes: 12px (small labels), 14px (body/table), 16px (headings), 24px (stat cards)

Components:
- Cards: white bg, border #e2e8f0, shadow-sm, rounded-lg (8px)
- Toggle switches: 44x24px, blue (#2563eb) when ON, gray (#d1d5db) when OFF, with text label beside
- Tables: white bg, alternating rows (#ffffff / #f8fafc), sticky header with #f1f5f9 bg, 1px bottom border per row
- Buttons: Primary = blue bg white text, Secondary = white bg blue border, Destructive = red outline
- Badges/Pills: rounded-full, px-2.5 py-0.5, font-medium text-xs
- Filter chips: removable tags with X button, light blue bg (#eff6ff) blue text
- Sparklines: 80x24px inline SVG, blue (#2563eb) line, no axes

Generate a design token reference sheet showing: color swatches, alarm state badges, severity badges (5 levels, outline style), toggle switch states, button variants, table row styles, filter chips, and sparkline example.

Tech: React + TypeScript + Tailwind CSS.
```

---

## Prompt 1: App Shell

```
[CONTEXT] App shell for "Alarm Manager" — AWS monitoring alarm management web app. Use the established design system.

[LAYOUT]
TOP BAR (h-14, white bg, border-b border-slate-200, fixed top):
- Left: text logo "Alarm Manager" in #2563eb, font-semibold text-lg
- Center: 3 cascading dropdown selectors in a row —
  Customer → Account (filtered by customer) → Service/Project (filtered by account)
  Each dropdown: white bg, border, rounded-md, w-48, placeholder text in gray
- Right: Bell icon with red count badge (top-right), User avatar circle (32px) + chevron-down

LEFT SIDEBAR (w-60, collapsible to w-16, #f8fafc bg, border-r, fixed left, below top bar):
- Toggle button at bottom to collapse/expand
- Nav items with lucide-react icons, 14px labels:
  Dashboard (Home), Resources (Server), Alarms (Bell),
  Mute Rules (VolumeX), Coverage (BarChart3), Import (Upload),
  Templates (Copy), Audit Log (History),
  Sync Status (RefreshCw), Settings (Settings2)
- Active state: blue-600 left border (3px), blue-50 bg, blue-600 icon+text
- Hover state: slate-100 bg
- Collapsed: icon only centered, tooltip on hover showing label
- Divider line before Settings

MAIN CONTENT: remaining space right of sidebar, below top bar, white bg, p-6

[STATES]
- Sidebar expanded (default)
- Sidebar collapsed (icon-only)
- Dropdown open state for each global filter
- Show "Dashboard" placeholder in main content

Tech: React + TypeScript + Tailwind CSS + lucide-react icons.
```


---

## Prompt 2: Dashboard Page

```
[CONTEXT] Dashboard page for Alarm Manager app. Use established design system and app shell.

[LAYOUT] Single-column, scrollable. Sections stack vertically.

[COMPONENTS]
Section 1 — Stat Cards (4 cards in a row, equal width):
- "Monitored Resources": large number + small trend arrow (green up / red down)
- "Active Alarms": large number, card border turns red if > 0. Below: mini breakdown "SEV-1: 2 · SEV-2: 5 · SEV-3: 12 · SEV-4: 3 · SEV-5: 1"
- "Unmonitored Resources": large number, amber text if > 0
- "Connected Accounts": large number

Section 2 — Charts Row (2 columns):
- Left: Horizontal stacked bar "Alarms by State" (OK green / ALARM red / INSUFFICIENT amber / MUTED purple), legend below
- Right: Donut chart "Alarms by Resource Type" (top 8 types + "Other"), legend beside

Section 3 — Recent Alarm Triggers (table, last 10, auto-refresh badge):
Columns: Time (relative, e.g. "3m ago"), Customer, Account, Resource ID (mono), Type (icon+label), Metric, Severity (outline badge: SEV-1~5, read-only), State Change (pill: "OK → ALARM"), Value vs Threshold ("82.1% / 80%")

Section 4 — Quick Actions Row (3 cards):
- "Scan All Resources" with play icon, blue outline button
- "Orphan Alarms" with alert-triangle icon, count badge
- "Drift Report" with git-compare icon, count badge

Section 5 — Coverage Summary (single card):
- Big percentage "87% Coverage", small progress bar, link "View Full Report →"

[STATES]
- Loading: skeleton cards + skeleton table rows
- Empty: "No alarms configured yet" with CTA button
- Active alarms > 0: red highlight on stat card
```

---

## Prompt 3: Resources Page

```
[CONTEXT] Resources page — core data view for Alarm Manager. Use established design system.

[LAYOUT] Full-width filter bar (3 rows, collapsible via toggle) above a data table. Sticky bulk-action bar at bottom when rows checked.

[COMPONENTS]
Filter Bar (white card, p-4, mb-4, collapsible with "Filters" toggle + active count badge):

Row 1 — Context Filters:
- Customer: multi-select dropdown, placeholder "All Customers"
- Service/Project: multi-select, filtered by customer selection
- Account: multi-select, filtered by customer

Row 2 — Resource Filters:
- Resource Type: multi-select with category grouping in dropdown:
  Compute (EC2, Lambda, ECS, SageMaker), Database (RDS, AuroraRDS, DocDB, ElastiCache, DynamoDB), Network (ALB, NLB, CLB, TG, NAT, VPN, Route53, DX, CloudFront), Storage (S3, EFS, Backup), Application (APIGW, SQS, MSK, SNS, MQ), Security (WAF, ACM, OpenSearch)
- Region: multi-select
- Tag: key=value input with autocomplete
- Search: free-text, searches Resource ID and Name tag

Row 3 — Status Filters:
- Monitoring: segmented control (All / On / Off)
- Alarm State: clickable chips (All, Active Alarm, All OK, No Alarms, INSUFFICIENT, Muted)
- Severity: clickable chips (All, SEV-1, SEV-2, SEV-3, SEV-4, SEV-5)
- Metric: dropdown multi-select (CPU, Memory, Disk, etc.)

Active filter chips row: below filter bar, each chip shows "label: value" with X to remove. "Clear All" link at right.

Table (white bg, rounded-lg border):
- Checkbox column (header = select all on page)
- Columns: Customer, Account, Resource ID (monospace), Name, Type (small icon + label), Region, Monitoring (inline toggle switch), Active Alarms (count in colored badge), Highest Severity (outline badge: SEV-1 red / SEV-2 orange / SEV-3 amber / SEV-4 blue / SEV-5 gray — shows worst active alarm severity, read-only), Muted (volume-x icon if muted, gray), Tags (first 2 as chips, "+N" overflow)
- Alternating row bg, sticky header
- Sort indicator on column headers (chevron up/down)
- Pagination bar: "Showing 1-25 of 1,247" + page size selector (25/50/100) + prev/next

"Select all 47 EC2 instances" link: appears when filtered to single type and some rows checked

[STATES]
- Loading: 8 skeleton rows
- Empty: illustration + "No resources match your filters" + "Clear Filters" button
- Bulk action bar (sticky bottom, h-16, white bg, shadow-up, appears when ≥1 checked):
  Left: "23 resources selected" + "Clear" link
  Right: "Enable Monitoring" (green), "Disable Monitoring" (red outline), "Configure Alarms" (blue), "Apply Template" (outline), "Mute" (purple outline), "Export CSV" (outline)
```


---

## Prompt 3-B: Bulk Alarm Config Drawer

```
[CONTEXT] Slide-out drawer triggered from Resources page "Configure Alarms" bulk action. Use established design system.

[LAYOUT] Right-side drawer, w-[520px], white bg, shadow-xl, overlay on left. Header + scrollable content + sticky footer.

[COMPONENTS]
Header: "Configure Alarms for 23 EC2 Instances" + close X button

Warning banner (conditional, amber bg): "Select resources of the same type to configure alarms in bulk" — shown when mixed types selected, drawer content disabled.

Selective Metric Update Table:
| ☐ Select | Toggle | Metric Name      | New Threshold | Unit | Dir | Current Range        |
|----------|--------|------------------|---------------|------|-----|----------------------|
| ☑        | [ON]   | CPU Utilization  | [90]          | %    | ▲   | 70~90 across 23 res  |
| ☐        | —      | Memory           | —             | %    | ▲   | 75~85 across 23 res  |
| ☑        | [ON]   | Disk (all paths) | [85]          | %    | ▲   | 80~80 across 23 res  |
| ☐        | —      | Status Check     | —             |      | ▲   | 0~0 across 23 res    |

- "Select" checkbox: only checked metrics will be changed. Unchecked = keep existing per-resource values.
- "Select All" checkbox in header row
- Unchecked rows: grayed out, inputs disabled
- "Current Range" column: shows min~max threshold across selected resources in gray text
- Direction: ▲ = high is bad (GreaterThan), ▼ = low is bad (LessThan)

Override warning (conditional): "⚠ 5 of 23 resources have custom thresholds for CPU that will be overwritten"

Sticky footer:
- "Preview Changes" secondary button → expands a diff section showing per-resource old→new for selected metrics only
- "Apply Selected Metrics" primary button → confirmation modal: "Update CPU and Disk thresholds for 23 EC2 instances?"

[STATES]
- Mixed types: warning banner, content disabled
- No metrics selected: Apply button disabled
- Preview expanded: scrollable diff list below table
```

---

## Prompt 4: Resource Detail — Header + Tabs Shell

```
[CONTEXT] Resource Detail page header and tab navigation. Use established design system.

[LAYOUT] Full-width header section + tab bar. Tab content area below.

[COMPONENTS]
Breadcrumb: "Acme Corp > 123456789012 > EC2 > prod-web-01" — clickable segments, gray text, blue on hover

Header Row (flex, items-center, gap-4):
- Resource ID: "i-0abc123def456" in monospace, medium text
- Name: "prod-web-01" in semibold
- Type badge: EC2 icon + "EC2" label in slate pill
- Account: "123456789012" in small gray
- Region: "us-east-1" in small gray

Controls Row (flex, items-center, gap-4, mt-3):
- Monitoring toggle (large, 52x28px): green "● Monitoring ON" or gray "○ Monitoring OFF"
- Mute status (conditional): purple banner "🔇 Muted — rule: '배포 점검' until 06:00 [View Rule →]"
- Spacer
- "Last Synced: 2h ago" gray text
- "Force Sync" outline button with refresh icon

Tab Bar (border-b, mt-4):
- Tabs: "Alarm Config" (default active), "Metrics", "Timeline", "Compare"
- Active: blue text + blue bottom border (2px)
- Inactive: gray text, hover blue

[STATES]
- Monitoring ON vs OFF (toggle color change)
- Muted vs Active (purple banner visible/hidden)
- Each tab active state
```


---

## Prompt 4-B: Resource Detail — Alarm Config Tab

```
[CONTEXT] "Alarm Config" tab inside Resource Detail page. Use established design system.

[LAYOUT] Two sections stacked: Standard Metrics table + Custom Metrics section. Sticky action bar at bottom.

[COMPONENTS]
Section: Standard Metrics (auto-populated by resource type)
Table columns:
| Toggle | Metric | CW Metric (gray mono) | Dir | Threshold (input) | Unit | Severity (read-only badge) | State (pill) | Current Value | Source (badge) | Trend (sparkline) |

Example rows for EC2:
| [ON]  | CPU          | CPUUtilization    | ▲ | [80]  | % | SEV-3      | 🟢 OK    | 23.4% | System   | ↗ sparkline |
| [ON]  | Memory       | mem_used_percent  | ▲ | [80]  | % | SEV-3      | 🟢 OK    | 45.2% | Customer | → sparkline |
| [ON]  | Disk (/)     | disk_used_percent | ▲ | [80]  | % | SEV-3      | 🔴 ALARM | 82.1% | Custom   | ↗ sparkline |
| [OFF] | Disk (/data) | disk_used_percent | ▲ | [80]  | % | SEV-3      | ⚫ OFF   | 55.3% | System   | → sparkline |
| [ON]  | Status Check | StatusCheckFailed | ▲ | [0]   |   | SEV-1      | 🟢 OK    | 0     | System   | → sparkline |

- Toggle: switch ON/OFF per metric (OFF = alarm disabled)
- Threshold: inline number input, editable
- Direction: ▲ icon (high-is-bad) or ▼ icon (low-is-bad), non-editable
- Severity: read-only outline badge (SEV-1 red / SEV-2 orange / SEV-3 amber / SEV-4 blue / SEV-5 gray). Auto-assigned from system defaults. Not editable in Phase 1.
- State: colored status pill (OK green, ALARM red, INSUFFICIENT amber, OFF gray)
- Current Value: monospace, colored red if exceeding threshold
- Source badge: "System" (slate), "Customer" (blue), "Custom" (purple) — shows where threshold comes from
- Trend: tiny sparkline (80x24px) showing last 1h

Section: Custom / Dynamic Metrics
- "Add Custom Metric" button (blue outline, plus icon)
  → Inline form row appears: Metric name (text input), Threshold (number), Direction (▲/▼ dropdown), Unit (text), Save/Cancel
  → Note below: "Metric must exist in CloudWatch. Auto-resolves namespace via list_metrics API."
- Existing custom alarms table:
  | Metric | Namespace | Threshold | Dir | State | Current | Source | Actions |
  | CommitLatency | AWS/RDS | 0.05 | ▲ | 🟢 OK | 0.012s | Tag | (view only) |
  | custom_errors | CustomApp | 10 | ▲ | 🟡 INSUF | — | UI | Edit / Delete |
- Source "Tag" = read-only (edit via resource tag), "UI"/"Import" = editable

Sticky Action Bar (bottom, white bg, border-t, p-4):
- Left: unsaved changes indicator (orange dot + "Unsaved changes" text) — hidden when clean
- Right: "Reset to Defaults" (outline), "Apply Customer Defaults" (outline), "Save Changes" (blue primary, disabled when clean)

[STATES]
- Clean (no changes): Save disabled, no indicator
- Dirty (changes made): orange dot, Save enabled
- Saving: spinner on Save button
- Metric OFF: row slightly grayed, state shows ⚫ OFF
```

---

## Prompt 4-C: Resource Detail — Metrics Tab

```
[CONTEXT] "Metrics" tab inside Resource Detail. Use established design system.

[LAYOUT] Time range selector at top, then 2-column grid of metric charts.

[COMPONENTS]
Time Range: segmented control — 1h | 6h | 24h (default) | 7d | 30d

Chart Grid (2 columns, gap-4):
Each chart card (white bg, border, rounded-lg, p-4):
- Header: metric name (left), current value in large text (right, red if exceeding threshold)
- Chart area (h-48): line chart with blue line, dashed red horizontal line for threshold
- X-axis: time labels, Y-axis: value labels with unit
- Click card → expands to full-width with more detail

[STATES]
- Loading: skeleton chart placeholders
- No data: "No metric data available" in chart area
- Threshold exceeded: current value in red, chart area has faint red bg above threshold line
```

---

## Prompt 4-D: Resource Detail — Timeline Tab

```
[CONTEXT] "Timeline" tab inside Resource Detail. Use established design system.

[LAYOUT] Filter row at top, vertical timeline below.

[COMPONENTS]
Filter: event type chips (All, State Changes, Threshold Mods, Toggles, Mute/Unmute, Tag Changes)

Timeline (vertical, left-aligned):
Each event:
- Left: timestamp (gray, small, "2024-03-15 14:23 KST")
- Icon circle: colored by type (red=alarm trigger, green=resolved, blue=config change, purple=mute, gray=tag)
- Content: one-line description + optional detail
  Examples:
  - "CPU alarm → ALARM (82.1% exceeded 80%)" with red icon
  - "CPU threshold changed: 80% → 90% by admin@company.com" with blue icon
  - "Monitoring enabled by admin@company.com" with green icon
  - "Muted by rule '배포 점검'" with purple icon

[STATES]
- Loading: skeleton timeline items
- Empty: "No events recorded for this resource"
- Filtered: only matching event types shown
```


---

## Prompt 5: Alarms Page

```
[CONTEXT] Alarms page — alarm-centric view. Use established design system. Reuse the same filter bar + data table pattern from the Resources page.

[LAYOUT] Summary cards row → filter bar (3 rows) → data table. Same pattern as Resources.

[COMPONENTS]
Summary Cards (5 cards, clickable → auto-applies state filter):
- Total Alarms (slate), ALARM count (red card), OK count (green card), INSUFFICIENT (amber card), MUTED (purple card)
- Clicked card gets blue ring outline, corresponding filter chip appears

Filter Bar — same 3-row collapsible pattern as Resources. Differences:
Row 1: Customer (multi), Service/Project (multi), Account (multi) — same
Row 2: Resource type (multi, grouped), Resource ID/Name search, Metric (multi, grouped by: Saturation/Latency/Errors/Traffic), Source (Standard/Custom/Import chips)
Row 3: Alarm state (All/ALARM/OK/INSUFFICIENT/MUTED chips), Severity (All/SEV-1/SEV-2/SEV-3/SEV-4/SEV-5 chips), Time range (last triggered: 1h/6h/24h/7d/30d)

Table — same style as Resources. Different columns:
Customer, Account, Resource ID (mono), Resource Name, Type (icon), Metric Name, Alarm Name, Threshold, Current Value (red if exceeding), Severity (read-only outline badge), State (colored pill), Source (badge), Muted (icon), Last State Change (relative time), Duration in State

- Row click → navigates to Resource Detail page, Alarm Config tab, with that metric row highlighted/scrolled-to
- Bulk actions: Mute Selected (purple), Unmute Selected (outline), Export CSV (outline)

[STATES]
- Same as Resources: loading skeleton, empty state, bulk action bar
- Summary card active (clicked): blue ring + filter applied
```

---

## Prompt 6: Mute Rules Page

```
[CONTEXT] Mute Rules page — manage CloudWatch Alarm Mute Rules. Use established design system. Alarms continue evaluating during mute, only actions (SNS notifications) are suppressed.

[LAYOUT] Active rules cards at top → rules list table → mute history table at bottom.

[COMPONENTS]
Active Mute Rules (horizontal card row, only shown when active rules exist):
Each card (purple-50 bg, purple border):
- Rule name (bold), Target summary ("All alarms in prod account")
- Countdown: "Ends in 2h 15m" with timer icon
- "Deactivate" red outline button
- Muted alarm count badge

Rules List Table:
Columns: Name, Target (alarm pattern / tag filter / customer scope), Schedule (One-time / Recurring), Next Active, Duration, Status (Active green / Scheduled blue / Expired gray pill), Created By, Actions (Edit / Delete)
- "Create Mute Rule" blue primary button above table

Create Mute Rule Form (modal or full-page):
- Name: text input
- Description: textarea (optional)
- Target alarms (radio + config):
  ○ All alarms in account(s): account multi-select
  ○ By alarm name pattern: text input with wildcard hint (e.g., "[EC2]*")
  ○ By resource tag: key=value input (e.g., Environment=staging)
  ○ By specific resources: resource search + select chips
  ○ By customer: customer dropdown → all accounts
- Schedule:
  ○ One-time: start datetime picker + end datetime picker + timezone selector
  ○ Recurring: day-of-week checkboxes + time range + duration + optional expiry date
    OR cron expression input with preview
- Reason: text input (e.g., "배포 중", "DB 마이그레이션")
- Footer: "Cancel" + "Create Rule" primary button

Mute History (collapsible section at bottom):
Table: Start, End, Rule Name, Alarms Muted Count, Created By, Reason

[STATES]
- No active rules: cards section hidden
- Creating: modal/page with form
- Rule active: green status pill + countdown in card
```


---

## Prompt 7: Settings — Customer Onboarding Wizard

```
[CONTEXT] Customer onboarding wizard inside Settings > Customers. Use established design system. This is the "운영환경 정의서" flow — registering a new customer with their default alarm configuration.

[LAYOUT] Stepper at top (5 steps) + step content below + navigation buttons at bottom.

[COMPONENTS]
Stepper: horizontal, 5 circles connected by lines. Active = blue filled, completed = green check, upcoming = gray outline.
Steps: 1.Info → 2.Accounts → 3.Alarm Defaults → 4.Notifications → 5.Review

Step 1 — Customer Info:
- Name (text), Code (short ID, text), Description (textarea)
- Primary contact: name, email, phone inputs
- SLA tier: radio (Basic / Standard / Premium)
- Services/Projects: repeatable row (name + description + environment tag), "Add Service" button

Step 2 — Account Registration:
- Repeatable account card:
  Account ID (text), Account Name (text), Role ARN (text), Region (dropdown), Service/Project (dropdown from step 1)
  "Test Connection" button per card → green check or red X result
- "Add Account" button

Step 3 — Default Alarm Configuration (핵심):
- Resource type horizontal tabs: EC2 | RDS | AuroraRDS | ALB | NLB | TG | ElastiCache | Lambda | ... (scrollable)
- Per type, threshold table:
  | Metric | System Default | Customer Override | Unit | Dir | Description |
  | CPU | 80% | [  ] | % | ▲ | CPU utilization |
  | Memory | 80% | [  ] | % | ▲ | Memory usage |
  | Disk | 80% | [  ] | % | ▲ | Disk per mount path |
  | StatusCheckFailed | 0 | [  ] | | ▲ | EC2 status check |
- Empty override = use system default (shown in gray)
- "Copy from existing customer" dropdown at top
- "Apply template" button: select pre-built template as baseline

Step 4 — Notification Setup:
- Default notification info: display text "Alarms are sent via AWS Chatbot → Slack (configured per customer site)"
- SNS topic ARN display (read-only, shows current customer's SNS topic)
- "Notification routing configuration will be available in a future update"
- "Skip" link (this step is informational only in Phase 1)

Step 5 — Review:
- Collapsible summary sections: Customer Info, Accounts (with connection status), Alarm Defaults (per type count), Notifications
- "Create Customer" primary button

[STATES]
- Step navigation: can go back, cannot skip ahead
- Connection test: loading spinner → green check / red X
- Review: all sections collapsed by default, expand on click
```

---

## Prompt 8: Coverage Report Page

```
[CONTEXT] Coverage Report page — monitoring coverage analysis. Use established design system.

[LAYOUT] Summary at top → customer table → heatmap → unmonitored list.

[COMPONENTS]
Overall Summary (card, centered):
- Big number: "87%" with label "Monitoring Coverage"
- Donut chart beside: Monitored (green) vs Unmonitored (amber) segments
- Trend: "↑ 3% from last month" in green text

Coverage by Customer (table):
Columns: Customer, Total Resources, Monitored, Unmonitored, Coverage % (with mini progress bar in cell), Trend (arrow)
- Row click → filters heatmap and unmonitored list to that customer
- Sort by coverage % ascending to see worst first

Coverage Heatmap (resource type × customer):
- Rows: resource types (EC2, RDS, ALB, etc.)
- Columns: customers
- Cell: percentage number + background color (green >90%, amber 50-90%, red <50%, gray = no resources)
- Hover cell: tooltip "Acme Corp — EC2: 45/50 monitored (90%)"

SRE Golden Signals Coverage (table):
| Type | Latency | Traffic | Errors | Saturation | Overall |
| EC2 | — | — | ✅ StatusCheck | ✅✅✅ CPU,Mem,Disk | 75% |
| RDS | ✅✅ Read,Write | — | — | ✅✅✅✅ CPU,Mem,Storage,Conn | 85% |
- ✅ = covered by hardcoded alarm, — = available via dynamic alarm only

Unmonitored Resources (table, same style as Resources page):
- Filtered to Monitoring=off only
- Columns: Customer, Account, Resource ID, Name, Type, Region, Tags
- Bulk action: "Enable Monitoring" for selected

[STATES]
- Loading: skeleton for all sections
- 100% coverage: green celebration banner "All resources monitored!"
- Customer filter active: heatmap and unmonitored list filtered
```


---

## Prompt 9: Import Page

```
[CONTEXT] Bulk Import page — upload xlsx to configure alarms. Use established design system.

[LAYOUT] 3-step stepper at top + step content. Import history table below.

[COMPONENTS]
Stepper: 3 steps — 1.Upload → 2.Validate → 3.Apply

Step 1 — Upload:
- "Download Template" blue outline button (top right) — downloads xlsx with sheet per resource type
- Drag-drop zone (dashed border, h-48, centered icon + text):
  "Drop .xlsx file here or click to browse"
  Accepted: .xlsx only
- Template description: "Template includes one sheet per resource type. Columns: Resource ID, Monitoring (on/off), then one column per metric. Use 'off' to disable, leave empty for default."

Step 2 — Validate:
- Summary cards: Total Rows, ✅ Valid (green), ⚠️ Warnings (amber), ❌ Errors (red)
- Filter chips: Show All / Valid Only / Warnings / Errors
- Validation table:
  | Row | Status (icon) | Resource ID | Type | Details |
  | 3 | ✅ | i-abc123 | EC2 | Valid |
  | 7 | ⚠️ | i-def456 | EC2 | Will overwrite existing custom config |
  | 12 | ❌ | i-xyz789 | EC2 | Resource not found |
- Footer: "Re-upload" outline button, "Proceed with N valid rows" primary button (disabled if 0 valid)

Step 3 — Apply:
- Confirmation: "Apply alarm config to 156 resources?"
- Progress bar (blue, animated)
- Results table: Resource ID, Status (✅ Success / ❌ Failed), Details
- "Export Results" button (downloads xlsx), "View Failed Only" filter

Import History (below stepper, collapsible):
Table: Date, Uploaded By, File Name, Total Rows, Success, Failed, Status (Complete/Partial/Failed pill)
- Row click → shows detailed results of that import

[STATES]
- No file: drop zone empty
- File selected: file name + size shown, "Upload" button
- Validating: spinner
- All errors: "Proceed" disabled, "Re-upload" prominent
```

---

## Prompt 10: Notification Routing Page (Coming Soon placeholder)

```
[CONTEXT] Notification Routing page — placeholder for future Phase 2 feature. Use established design system.

[LAYOUT] Single centered content area within app shell.

[COMPONENTS]
Page header: "Notification Routing" title

Coming Soon Card (centered, max-w-lg):
- Mail icon (large, gray)
- Title: "Notification Routing — Coming Soon"
- Description: "Currently, alarms are delivered via AWS Chatbot → Slack (configured per customer site). Advanced notification routing with channel selection, severity-based routing, and escalation policies will be available in a future update."
- "Learn More" outline button (links to docs or roadmap)

Current Setup Info Card (below, full-width):
- Title: "Current Notification Setup"
- Table showing per-customer notification config:
  | Customer | SNS Topic | Chatbot | Slack Channel | Status |
  | Acme Corp | arn:aws:sns:... | ✅ Connected | #acme-alerts | 🟢 Active |
  | Beta Inc | arn:aws:sns:... | ✅ Connected | #beta-alerts | 🟢 Active |
- Read-only, informational

[STATES]
- Default: coming soon card + current setup table
- No customers: only coming soon card
```

---

## Prompt 11: Remaining Pages (Audit Log, Sync Status, Templates)

```
[CONTEXT] Three remaining pages for Alarm Manager. Use established design system. Reuse filter + table pattern from Resources/Alarms pages.

PAGE A — Audit Log:
Reuse filter bar + table pattern.
Filter bar: date range picker, user dropdown, action type chips (Created/Modified/Deleted/Toggled/Muted/Imported), resource type, customer, account
Table columns: Timestamp, User (avatar+name), Action (colored badge), Customer, Account, Resource ID (mono), Metric, Old Value → New Value, Source (UI/API/Sync/Import badge)
- Row click → detail drawer showing full before/after diff
- "Export CSV" button

PAGE B — Sync Status:
Section 1 — Health Cards (4):
- Last Daily Sync: timestamp + green/red status dot
- Remediation Handler: status dot + "Running"/"Error"
- DLQ Messages: count, red card if > 0
- API Health: green/red dot

Section 2 — Account Connections Table:
Account ID, Customer, Status (green/red dot), Last Sync, Failed (24h), Resources, Error Details (expandable)
"Test" and "Retry" buttons per row

Section 3 — Drift Detection Table:
Resource ID, Metric, Expected Threshold, Actual Threshold, Drift Type (Missing/Mismatch/Extra badge)
"Reconcile" button per row, "Reconcile All" bulk button

PAGE C — Templates:
Table: Name, Resource Type (badge), Metrics Count, Created By, Last Modified, Usage Count
"Create Template" button → form: name, resource type selector, description, metrics config table (same as Resource Detail alarm config table)
Template detail: view/edit metrics, "Apply to Resources" button → resource selector
Pre-built rows: "Web Server Standard", "Database Standard", "Network Standard" with lock icon (non-deletable)

[STATES]
All pages: loading skeleton, empty states with helpful CTA
```
