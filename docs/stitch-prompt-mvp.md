# Stitch MVP Prompt: Alarm Manager (최소 단위)

Design a simple web app for managing AWS CloudWatch alarm thresholds across multiple accounts. Engineers use this to view resources and configure alarm thresholds instead of manually tagging AWS resources.

## Users
Infrastructure engineers managing AWS accounts. They need to see resources, toggle monitoring on/off, and set alarm thresholds per metric.

## Layout
- Top bar: logo "Alarm Manager" (left), Customer/Account/Service dropdowns (center), user avatar (right)
- Left sidebar: Dashboard, Resources, Alarms, Settings — collapsible to icons
- Main content area: white background

## Design
Light theme. White background, light gray (#f8fafc) sidebar. Blue (#2563eb) accent. Green=OK, Red=ALARM, Amber=INSUFFICIENT, Gray=OFF. Clean, dense tables. System sans-serif font, monospace for IDs/values.

## Pages (4 only)

### 1. Dashboard
4 stat cards: Monitored Resources, Active Alarms (red if >0), Unmonitored, Accounts.
Recent alarm triggers table (last 10): Time, Resource, Type, Metric, State, Value/Threshold.

### 2. Resources List
Filter bar: Customer, Account, Resource Type (grouped: Compute/Database/Network/Storage/App/Security — 30 AWS types), Monitoring status, free-text search.
Table: checkbox, Resource ID (mono), Name, Type (icon), Account, Region, Monitoring (toggle switch), Active Alarms (badge).
Bulk actions when selected: Enable/Disable Monitoring, Configure Alarms.
Row click → Resource Detail.

### 3. Resource Detail
Header: Resource ID, Name, Type, Account, Region. Large Monitoring ON/OFF toggle.

Alarm Config table (auto-populated by resource type):
| Toggle | Metric | Threshold | Unit | Direction | State | Current Value |
| [ON] | CPU | [80] | % | ▲ | 🟢 OK | 23% |
| [ON] | Memory | [80] | % | ▲ | 🟢 OK | 45% |
| [ON] | Disk (/) | [80] | % | ▲ | 🔴 ALARM | 82% |
| [OFF] | StatusCheck | [0] | | ▲ | ⚫ OFF | 0 |

- Toggle: enable/disable per metric
- Threshold: editable number input
- Direction: ▲ high-is-bad, ▼ low-is-bad (read-only)
- Save Changes / Reset to Defaults buttons

Custom metric section: "Add Custom Metric" button → metric name + threshold + direction.

### 4. Settings
Customer list with Add Customer form (name, code, accounts).
Account list with Add Account form (ID, name, role ARN, customer).
Default thresholds per resource type (system defaults, customer overrides).

## Tech
React + TypeScript + Tailwind CSS.
