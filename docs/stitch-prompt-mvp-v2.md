# Stitch MVP v2 — Design Revision Prompts

Based on v1 design review against Phase1 backend code. Apply these changes to the existing design.

---

## Revision 1: Resource Detail Page

```
Revise the Resource Detail page with these changes. Keep the existing layout structure.

HEADER: Keep as-is (ID, Type, Account, Region, Monitoring toggle). Good.

ALARM CONFIGURATION TABLE — Add columns and fix data:

New column order:
| Monitor (toggle) | Metric | CW Metric Name (gray mono) | Threshold (input) | Unit | Direction | Severity (read-only badge) | State | Current Value |

Changes:
1. Add "CW Metric Name" column: shows actual CloudWatch metric name in gray monospace (e.g., "CPUUtilization", "mem_used_percent", "disk_used_percent"). Engineers need this.

2. Add "Severity" column: read-only outline badge. Auto-assigned, not editable.
   SEV-1 (red outline) = StatusCheckFailed, HealthyHostCount
   SEV-3 (amber outline) = CPU, Memory, Disk
   SEV-5 (gray outline) = RequestCount, Connections

3. Fix StatusCheckFailed threshold: change from 1 to 0 (alarm triggers when > 0)

4. Disk rows: show multiple rows for different mount paths:
   Disk Usage (/)     — 80 — Percent — ▲
   Disk Usage (/data) — 80 — Percent — ▲
   Disk Usage (/opt)  — 85 — Percent — ▲

5. Direction must vary by metric type:
   ▲ (up arrow, red) = high is bad: CPU, Memory, Disk, ELB5XX, Errors, Connections
   ▼ (down arrow, blue) = low is bad: FreeMemoryGB, FreeStorageGB, HealthyHostCount, TunnelState

6. Add "Source" badge after Severity: "System" (gray), "Customer" (blue), "Custom" (purple)
   Shows where the threshold value comes from.

CUSTOM METRIC SECTION — Enhance:
- "Add Custom Metric" button opens an inline form with:
  - Metric name: autocomplete dropdown (populated from CloudWatch list_metrics API, excludes hardcoded metrics)
  - Each option shows: "MetricName (Namespace)" e.g., "CommitLatency (AWS/RDS)"
  - Also allows free text input for metrics not yet in CloudWatch
  - Threshold: number input
  - Direction: dropdown (▲ Greater Than / ▼ Less Than), default ▲
  - Unit: auto-filled from CloudWatch, or manual input
- Validation indicator:
  ✅ "Metric found: CommitLatency (AWS/RDS, DBInstanceIdentifier)" — green
  ⚠️ "Metric not found in CloudWatch. Alarm will be INSUFFICIENT_DATA." — amber
- Below the add form, show existing custom alarms as a small table:
  | Metric | Namespace | Threshold | Dir | State | Source (Tag/UI) | Actions |

RESOURCE TYPE VARIATIONS:
Show a note that the metrics table changes based on resource type. Example for RDS:
| [ON] | CPU | CPUUtilization | [80] | % | ▲ | SEV-3 | OK | 15% |
| [ON] | Free Memory | FreeableMemory | [2] | GB | ▼ | SEV-3 | OK | 4.2GB |
| [ON] | Free Storage | FreeStorageSpace | [10] | GB | ▼ | SEV-3 | OK | 45GB |
| [ON] | Connections | DatabaseConnections | [100] | Count | ▲ | SEV-5 | OK | 23 |
| [ON] | Read Latency | ReadLatency | [0.02] | s | ▲ | SEV-4 | OK | 0.003s |
| [ON] | Write Latency | WriteLatency | [0.02] | s | ▲ | SEV-4 | OK | 0.005s |

Keep: Recent Events section, Resource Health Map, Save/Reset buttons, unsaved changes indicator.
```


---

## Revision 2: Resources List Page

```
Revise the Resources List page with these changes.

TABLE — Add/fix columns:
1. Add "Customer" column after checkbox (shows customer name, needed for multi-customer view)
2. Fix resource type labels: use exact Phase1 types, not generic:
   EC2, RDS, AuroraRDS, ALB, NLB, CLB, TG, DocDB, ElastiCache, NAT, Lambda, VPN, APIGW, ACM, Backup, MQ, OpenSearch, SQS, ECS, MSK, DynamoDB, CloudFront, WAF, Route53, DX, EFS, S3, SageMaker, SNS
   (not "NET" for ALB — ALB and NLB are separate types)
3. Active Alarms badge: show severity level too. "2 SEV-1" (red), "1 SEV-3" (amber), "0 ACTIVE" (gray)

FILTER BAR — Add:
4. Add "Service/Project" dropdown between Account and Resource Type
5. Resource Type dropdown: group into categories with section headers:
   Compute: EC2, Lambda, ECS, SageMaker
   Database: RDS, AuroraRDS, DocDB, ElastiCache, DynamoDB
   Network: ALB, NLB, CLB, TG, NAT, VPN, Route53, DX, CloudFront
   Storage: S3, EFS, Backup
   Application: APIGW, SQS, MSK, SNS, MQ
   Security: WAF, ACM, OpenSearch

BOTTOM STATS — Keep as-is. Total Monitored, Active Alarms, Sync Status, Coverage are good.

Keep: bulk action bar, pagination, Export CSV, Sync Resources button.
```

---

## Revision 3: Settings Page

```
Revise the Settings page with these changes.

ALARM THRESHOLD OVERRIDES section:
1. Resource type tabs: show ALL 30 types (scrollable horizontal tabs), not just EC2/RDS/Lambda/S3
   Full list: EC2, RDS, AuroraRDS, ALB, NLB, CLB, TG, DocDB, ElastiCache, NAT, Lambda, VPN, APIGW, ACM, Backup, MQ, OpenSearch, SQS, ECS, MSK, DynamoDB, CloudFront, WAF, Route53, DX, EFS, S3, SageMaker, SNS

2. Metric cards: use actual Phase1 hardcoded metrics per type. For EC2 tab:
   - CPUUtilization (> 80%)
   - mem_used_percent (> 80%)
   - disk_used_percent (> 80%)
   - StatusCheckFailed (> 0)
   NOT "DiskWriteOps" — that's not a Phase1 hardcoded metric.

3. Each metric card should show:
   - Metric name + CW metric name
   - Comparison direction (> or <)
   - System default value
   - Customer overrides list with values
   - "Add Override" button

ACCOUNT REGISTRY:
4. Add "Test Connection" button per account row (validates AssumeRole)

CUSTOMER LIST:
5. Keep as-is. Simple form is fine for MVP. Wizard can come later.

Keep: overall layout with Customer List (left) + Account Registry (right) + Threshold Overrides (bottom).
```

---

## Revision 4: Design System Reference

```
Add to the design system reference:

SEVERITY BADGES (new, outline style):
- SEV-1: red outline (#dc2626 border + text), white bg, "SEV-1"
- SEV-2: orange outline (#ea580c), "SEV-2"
- SEV-3: amber outline (#d97706), "SEV-3"
- SEV-4: blue outline (#2563eb), "SEV-4"
- SEV-5: gray outline (#6b7280), "SEV-5"
These are read-only badges, not interactive.

SOURCE BADGES (new):
- "System": gray bg (#f1f5f9), gray text
- "Customer": blue bg (#eff6ff), blue text
- "Custom": purple bg (#f5f3ff), purple text

DIRECTION ICONS:
- ▲ (up arrow): red/orange tint — "high is bad" (GreaterThan)
- ▼ (down arrow): blue tint — "low is bad" (LessThan)

Remove "NEW ALARM" button from sidebar — alarms are created per-resource, not globally.

Keep: all existing status pills, toggle switches, button variants, typography, color system.
```
