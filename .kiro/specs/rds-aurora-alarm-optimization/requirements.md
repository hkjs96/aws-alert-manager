# Requirements Document

## Introduction

Optimize RDS and Aurora alarm definitions in the AWS Monitoring Engine along three axes of differentiation, plus improve threshold logic for memory/storage metrics:

1. **RDS vs Aurora separation** — Aurora instances expose different metrics than regular RDS (e.g., `FreeLocalStorage` instead of `FreeStorageSpace`, `AuroraReplicaLagMaximum` instead of `ReadLatency`/`WriteLatency`). This is already implemented in the prior `aurora-rds-monitoring` spec.
2. **Aurora Provisioned vs Serverless v2 separation** — Serverless v2 instances (`db.serverless` instance class) do NOT publish the `FreeLocalStorage` metric (confirmed via E2E test, KI-006). The engine must skip that alarm for Serverless v2 instances instead of leaving it in perpetual `INSUFFICIENT_DATA`.
3. **Writer vs Reader separation** — `AuroraReplicaLagMaximum` is only published on the primary/writer instance when reader instances exist in the cluster. Single-writer clusters without readers do not publish this metric (confirmed via E2E test, KI-007). `AuroraReplicaLag` is only published on reader instances. The engine must conditionally create lag alarms based on instance role.
4. **Percentage-based memory thresholds** — The current `FreeableMemory` alarm uses an absolute GB threshold (e.g., `HARDCODED_DEFAULTS["FreeMemoryGB"] = 2.0`), which does not scale across instance sizes. A `db.r6g.large` (16 GB) with 2 GB free = 12.5% free, while Serverless v2 at 0.5 ACU (~1 GB total) can never have 2 GB free. The engine should support percentage-based thresholds relative to total instance memory capacity.

This spec builds on the existing `aurora-rds-monitoring` spec which established the `AuroraRDS` resource type, `_AURORA_RDS_ALARMS`, and the collector classification logic.

## Glossary

- **Monitoring_Engine**: The AWS Monitoring Engine system comprising Daily Monitor and Remediation Handler Lambdas
- **Alarm_Manager**: The `common/alarm_manager.py` module responsible for alarm CRUD, sync, and definitions
- **RDS_Collector**: The `common/collectors/rds.py` module that collects RDS and Aurora instance information
- **Daily_Monitor**: The Lambda function that runs daily to scan resources, sync alarms, and check metrics
- **Instance_Class**: The DB instance class string (e.g., `db.r6g.large`, `db.serverless`) from `describe_db_instances`
- **Serverless_v2**: An Aurora instance with instance class `db.serverless`, which uses Aurora Capacity Units (ACU) instead of fixed compute
- **Provisioned_Instance**: An Aurora instance with a fixed instance class (e.g., `db.r6g.large`, `db.r7g.xlarge`), not `db.serverless`
- **Writer_Instance**: The primary Aurora instance in a cluster that handles write operations; publishes `AuroraReplicaLagMaximum` only when reader instances exist
- **Reader_Instance**: An Aurora replica instance that handles read operations; publishes `AuroraReplicaLag`
- **ACU**: Aurora Capacity Unit; 1 ACU ≈ 2 GiB memory. Serverless v2 minimum is 0.5 ACU (~1 GiB)
- **FreeLocalStorage**: CloudWatch metric for Aurora provisioned instances reporting available local storage in bytes; not published by Serverless v2 (KI-006)
- **AuroraReplicaLagMaximum**: CloudWatch metric reporting maximum replication lag across all readers; published on the writer instance only when readers exist (KI-007)
- **AuroraReplicaLag**: CloudWatch metric reporting replication lag on individual reader instances
- **HARDCODED_DEFAULTS**: The fallback threshold dictionary in `common/__init__.py`
- **DBInstanceClass**: The `DBInstanceClass` field from `describe_db_instances` API response
- **IsClusterWriter**: Boolean field from `describe_db_instances` indicating whether the instance is the cluster writer

## Metric Availability Matrix (AWS Documentation + E2E Verification)

각 조합별 CloudWatch 메트릭 발행 여부. 근거 출처를 명시하여 추후 프로비저닝 인프라 테스트 시 검증할 항목을 식별한다.

| Metric | RDS (non-Aurora) | Aurora Prov. Writer (w/ readers) | Aurora Prov. Writer (no readers) | Aurora Prov. Reader | Serverless v2 Writer (w/ readers) | Serverless v2 Writer (no readers) | Serverless v2 Reader |
|--------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| CPUUtilization | ✅ doc | ✅ doc | ✅ doc | ✅ doc | ✅ E2E | ✅ E2E | ✅ doc |
| FreeableMemory | ✅ doc | ✅ doc | ✅ doc | ✅ doc | ✅ E2E | ✅ E2E | ✅ doc |
| DatabaseConnections | ✅ doc | ✅ doc | ✅ doc | ✅ doc | ✅ E2E | ✅ E2E | ✅ doc |
| FreeStorageSpace | ✅ doc | ❌ doc | ❌ doc | ❌ doc | ❌ doc | ❌ doc | ❌ doc |
| FreeLocalStorage | ❌ | ✅ doc | ✅ doc | ✅ doc | ❌ E2E (KI-006) | ❌ E2E (KI-006) | ❌ doc |
| ReadLatency | ✅ doc | ✅ doc | ✅ doc | ✅ doc | ✅ E2E | ✅ E2E | ✅ doc |
| WriteLatency | ✅ doc | ✅ doc | ✅ doc | ✅ doc | ✅ E2E | ✅ E2E | ✅ doc |
| AuroraReplicaLagMaximum | ❌ | ✅ doc (Primary) | ❌ E2E (KI-007) | ❌ doc | ✅ doc (Primary) | ❌ E2E (KI-007) | ❌ doc |
| AuroraReplicaLag | ❌ | ❌ doc | ❌ doc | ✅ doc (Replica) | ❌ doc | ❌ doc | ✅ doc (Replica) |
| ACUUtilization | ❌ | ❌ doc | ❌ doc | ❌ doc | ✅ E2E | ✅ E2E | ✅ doc |
| ServerlessDatabaseCapacity | ❌ | ❌ doc | ❌ doc | ❌ doc | ✅ E2E | ✅ E2E | ✅ doc |

**근거 범례:**
- `✅ E2E` — aurora-rds-test 스택(2026-03-25)에서 `list_metrics` API로 직접 확인
- `✅ doc` — AWS 공식 문서 기준 ([Aurora CloudWatch Metrics](https://docs.aws.amazon.com/AmazonRDS/latest/AuroraUserGuide/Aurora.AuroraMonitoring.Metrics.html))
- `❌ E2E` — E2E 테스트에서 메트릭 미발행 확인 (KI-006, KI-007)
- `❌ doc` — AWS 공식 문서에서 해당 인스턴스 유형/역할에 미발행 명시

**미검증 항목 (프로비저닝 인프라 테스트 시 확인 필요):**
- Aurora Provisioned Writer/Reader의 FreeLocalStorage 실제 발행 여부
- Aurora Provisioned Writer (with readers)의 AuroraReplicaLagMaximum 실제 발행 여부
- Aurora Provisioned Reader의 AuroraReplicaLag 실제 발행 여부
- Serverless v2 Reader의 ACUUtilization, AuroraReplicaLag 실제 발행 여부

## Requirements

### Requirement 1: Collector Enrichment with Instance Metadata

**User Story:** As a monitoring operator, I want the collector to capture Aurora instance metadata (instance class, writer/reader role), so that the alarm manager can make conditional alarm decisions.

#### Acceptance Criteria

1. WHEN the RDS_Collector collects an AuroraRDS instance, THE RDS_Collector SHALL store the `DBInstanceClass` value in the resource tags under the key `_db_instance_class`
2. WHEN the RDS_Collector collects an AuroraRDS instance, THE RDS_Collector SHALL store the `IsClusterWriter` boolean (from the `DBClusterMembers` of the associated cluster, or from the instance metadata) as a string `"true"` or `"false"` in the resource tags under the key `_is_cluster_writer`
3. WHEN the RDS_Collector collects an AuroraRDS instance with `DBInstanceClass` equal to `db.serverless`, THE RDS_Collector SHALL store `_is_serverless_v2` with value `"true"` in the resource tags
4. WHEN the RDS_Collector collects an AuroraRDS instance with `DBInstanceClass` not equal to `db.serverless`, THE RDS_Collector SHALL store `_is_serverless_v2` with value `"false"` in the resource tags
5. WHEN the RDS_Collector collects a regular RDS instance (non-Aurora), THE RDS_Collector SHALL not add `_is_cluster_writer` or `_is_serverless_v2` metadata tags


### Requirement 2: Skip FreeLocalStorage Alarm for Serverless v2

**User Story:** As a monitoring operator, I want the engine to skip the `FreeLocalStorage` alarm for Aurora Serverless v2 instances, so that no alarm is created for a metric that is never published (KI-006).

#### Acceptance Criteria

1. WHEN the Alarm_Manager generates alarm definitions for an AuroraRDS instance with `_is_serverless_v2` tag equal to `"true"`, THE Alarm_Manager SHALL exclude the `FreeLocalStorageGB` alarm definition from the returned list
2. WHEN the Alarm_Manager generates alarm definitions for an AuroraRDS instance with `_is_serverless_v2` tag equal to `"false"` or absent, THE Alarm_Manager SHALL include the `FreeLocalStorageGB` alarm definition in the returned list
3. WHEN the Alarm_Manager skips the `FreeLocalStorageGB` alarm for a Serverless v2 instance, THE Alarm_Manager SHALL log the skip reason at info level including the instance identifier

### Requirement 3: Conditional ReplicaLag Alarm Based on Instance Role

**User Story:** As a monitoring operator, I want the engine to create the correct replication lag alarm based on whether the instance is a writer or reader, so that no alarm is created for a metric that is not published on that instance role (KI-007).

#### Acceptance Criteria

1. WHEN the Alarm_Manager generates alarm definitions for an AuroraRDS writer instance (`_is_cluster_writer` = `"true"`), THE Alarm_Manager SHALL include the `AuroraReplicaLagMaximum` alarm (metric key `ReplicaLag`) in the returned list
2. WHEN the Alarm_Manager generates alarm definitions for an AuroraRDS reader instance (`_is_cluster_writer` = `"false"`), THE Alarm_Manager SHALL exclude the `AuroraReplicaLagMaximum` alarm and instead include an `AuroraReplicaLag` alarm (new metric key `ReaderReplicaLag`)
3. THE Alarm_Manager SHALL configure the `AuroraReplicaLag` reader alarm with namespace `AWS/RDS`, dimension key `DBInstanceIdentifier`, comparison `GreaterThanThreshold`, stat `Maximum`, and metric key `ReaderReplicaLag`
4. THE Monitoring_Engine SHALL include a `ReaderReplicaLag` entry in `HARDCODED_DEFAULTS` with the same default value as `ReplicaLag` (2000000.0 microseconds)
5. THE Alarm_Manager SHALL register a display entry in `_METRIC_DISPLAY` for `ReaderReplicaLag` mapped to `("AuroraReplicaLag", ">", "μs")`

### Requirement 4: Writer-Only Cluster Detection for ReplicaLag Skip

**User Story:** As a monitoring operator, I want the engine to skip the `AuroraReplicaLagMaximum` alarm on writer instances that have no readers in the cluster, so that no alarm is created for a metric that is not published in single-writer configurations (KI-007).

#### Acceptance Criteria

1. WHEN the RDS_Collector collects an AuroraRDS writer instance, THE RDS_Collector SHALL determine the number of instances in the associated DB cluster by inspecting the `DBClusterMembers` list from `describe_db_clusters`
2. WHEN the RDS_Collector determines that the cluster has only one member (writer-only), THE RDS_Collector SHALL store `_has_readers` with value `"false"` in the resource tags
3. WHEN the RDS_Collector determines that the cluster has more than one member, THE RDS_Collector SHALL store `_has_readers` with value `"true"` in the resource tags
4. WHEN the Alarm_Manager generates alarm definitions for an AuroraRDS writer instance with `_has_readers` = `"false"`, THE Alarm_Manager SHALL exclude the `ReplicaLag` (AuroraReplicaLagMaximum) alarm definition from the returned list
5. WHEN the Alarm_Manager skips the `ReplicaLag` alarm for a writer-only cluster, THE Alarm_Manager SHALL log the skip reason at info level

### Requirement 5: Percentage-Based FreeableMemory Threshold

**User Story:** As a monitoring operator, I want to define FreeableMemory thresholds as a percentage of total instance memory, so that the alarm scales correctly across different instance sizes and Serverless v2 ACU configurations.

#### Acceptance Criteria

1. WHEN an AuroraRDS or RDS instance has a `Threshold_FreeMemoryPct` tag with a numeric value between 0 and 100, THE Alarm_Manager SHALL interpret the value as a percentage of total instance memory
2. WHEN the `Threshold_FreeMemoryPct` tag is present, THE Alarm_Manager SHALL calculate the absolute byte threshold as `(pct / 100) * total_memory_bytes` and use the result as the CloudWatch alarm threshold for `FreeableMemory`
3. WHEN both `Threshold_FreeMemoryGB` and `Threshold_FreeMemoryPct` tags are present, THE Alarm_Manager SHALL use `Threshold_FreeMemoryPct` (percentage takes precedence over absolute)
4. THE Monitoring_Engine SHALL include a `FreeMemoryPct` entry in `HARDCODED_DEFAULTS` with a default value of 20.0 (percent)
5. IF the `Threshold_FreeMemoryPct` tag value is not a valid number between 0 and 100 (exclusive), THEN THE Alarm_Manager SHALL log a warning and fall back to the absolute GB threshold (`Threshold_FreeMemoryGB` or `HARDCODED_DEFAULTS["FreeMemoryGB"]`)

### Requirement 6: Instance Memory Capacity Lookup

**User Story:** As a monitoring operator, I want the engine to determine the total memory capacity of each DB instance, so that percentage-based thresholds can be calculated accurately.

#### Acceptance Criteria

1. WHEN the RDS_Collector collects a provisioned RDS or AuroraRDS instance, THE RDS_Collector SHALL determine the total memory capacity in bytes from the `DBInstanceClass` and store it in the resource tags under the key `_total_memory_bytes`
2. WHEN the RDS_Collector collects a Serverless v2 instance, THE RDS_Collector SHALL calculate the maximum memory capacity as `max_acu * 2 * 1073741824` bytes (2 GiB per ACU) using the `ServerlessV2ScalingConfiguration.MaxCapacity` from the DB cluster, and store it in the resource tags under the key `_total_memory_bytes`
3. THE RDS_Collector SHALL maintain an internal mapping of common DB instance classes to their memory capacity in bytes (e.g., `db.r6g.large` = 16 GiB, `db.r6g.xlarge` = 32 GiB)
4. IF the instance class is not found in the internal mapping, THEN THE RDS_Collector SHALL log a warning and omit the `_total_memory_bytes` tag, causing the alarm to fall back to absolute GB threshold
5. WHEN `_total_memory_bytes` is not available for an instance, THE Alarm_Manager SHALL fall back to the absolute GB threshold (`Threshold_FreeMemoryGB` or `HARDCODED_DEFAULTS["FreeMemoryGB"]`) and log a warning

### Requirement 7: Serverless v2 Specific Alarms

**User Story:** As a monitoring operator, I want Serverless v2 instances to have ACU-related alarms, so that capacity utilization is monitored for auto-scaling instances.

#### Acceptance Criteria

1. WHEN the Alarm_Manager generates alarm definitions for an AuroraRDS Serverless v2 instance, THE Alarm_Manager SHALL include an `ACUUtilization` alarm with namespace `AWS/RDS`, metric name `ACUUtilization`, dimension key `DBInstanceIdentifier`, comparison `GreaterThanThreshold`, and stat `Average`
2. WHEN the Alarm_Manager generates alarm definitions for an AuroraRDS Serverless v2 instance, THE Alarm_Manager SHALL include a `ServerlessDatabaseCapacity` alarm with namespace `AWS/RDS`, metric name `ServerlessDatabaseCapacity`, dimension key `DBInstanceIdentifier`, comparison `GreaterThanThreshold`, and stat `Average`
3. WHEN the Alarm_Manager generates alarm definitions for a non-Serverless v2 AuroraRDS instance, THE Alarm_Manager SHALL exclude `ACUUtilization` and `ServerlessDatabaseCapacity` alarms
4. THE Monitoring_Engine SHALL include `ACUUtilization` in `HARDCODED_DEFAULTS` with a default value of 80.0 (percent)
5. THE Monitoring_Engine SHALL include `ServerlessDatabaseCapacity` in `HARDCODED_DEFAULTS` with a default value equal to the cluster's `MaxCapacity` ACU (resolved at alarm creation time from `_max_acu` tag)
6. THE Alarm_Manager SHALL register display entries in `_METRIC_DISPLAY` for `ACUUtilization` mapped to `("ACUUtilization", ">", "%")` and `ServerlessDatabaseCapacity` mapped to `("ServerlessDatabaseCapacity", ">", "ACU")`

### Requirement 8: Collector Enrichment with Serverless v2 Cluster Metadata

**User Story:** As a monitoring operator, I want the collector to capture Serverless v2 scaling configuration, so that ACU-based thresholds and memory calculations are accurate.

#### Acceptance Criteria

1. WHEN the RDS_Collector collects a Serverless v2 AuroraRDS instance, THE RDS_Collector SHALL query `describe_db_clusters` for the associated cluster and store the `ServerlessV2ScalingConfiguration.MaxCapacity` value as a string in the resource tags under the key `_max_acu`
2. WHEN the RDS_Collector collects a Serverless v2 AuroraRDS instance, THE RDS_Collector SHALL store the `ServerlessV2ScalingConfiguration.MinCapacity` value as a string in the resource tags under the key `_min_acu`
3. IF the `describe_db_clusters` call fails, THEN THE RDS_Collector SHALL log an error and omit the `_max_acu` and `_min_acu` tags

### Requirement 9: Aurora Metric Collection for Reader Instances

**User Story:** As a monitoring operator, I want the Daily Monitor to collect the correct replication lag metric based on instance role, so that threshold comparisons use the right data.

#### Acceptance Criteria

1. WHEN collecting metrics for an AuroraRDS reader instance (`_is_cluster_writer` = `"false"`), THE RDS_Collector SHALL query `AuroraReplicaLag` (not `AuroraReplicaLagMaximum`) from CloudWatch and return the value under key `ReaderReplicaLag`
2. WHEN collecting metrics for an AuroraRDS writer instance with readers (`_has_readers` = `"true"`), THE RDS_Collector SHALL query `AuroraReplicaLagMaximum` from CloudWatch and return the value under key `ReplicaLag`
3. WHEN collecting metrics for an AuroraRDS writer instance without readers (`_has_readers` = `"false"`), THE RDS_Collector SHALL skip the `AuroraReplicaLagMaximum` metric query

### Requirement 10: Aurora Metric Collection for Serverless v2 Instances

**User Story:** As a monitoring operator, I want the Daily Monitor to collect Serverless v2 specific metrics, so that ACU utilization is tracked.

#### Acceptance Criteria

1. WHEN collecting metrics for an AuroraRDS Serverless v2 instance, THE RDS_Collector SHALL query `ACUUtilization` from CloudWatch namespace `AWS/RDS` and return the value under key `ACUUtilization`
2. WHEN collecting metrics for an AuroraRDS Serverless v2 instance, THE RDS_Collector SHALL query `ServerlessDatabaseCapacity` from CloudWatch namespace `AWS/RDS` and return the value under key `ServerlessDatabaseCapacity`
3. WHEN collecting metrics for an AuroraRDS Serverless v2 instance, THE RDS_Collector SHALL skip the `FreeLocalStorage` metric query

### Requirement 11: Alarm Definition Routing by Instance Variant

**User Story:** As a monitoring operator, I want the alarm manager to select the correct alarm definition set based on the combination of instance class and role, so that each Aurora variant gets precisely the alarms that match its published metrics.

#### Acceptance Criteria

1. THE Alarm_Manager SHALL support four AuroraRDS alarm variants determined by `resource_tags`:
   - Aurora Provisioned Writer (with readers): CPU, FreeMemoryGB, Connections, FreeLocalStorageGB, ReplicaLag
   - Aurora Provisioned Writer (without readers): CPU, FreeMemoryGB, Connections, FreeLocalStorageGB
   - Aurora Provisioned Reader: CPU, FreeMemoryGB, Connections, FreeLocalStorageGB, ReaderReplicaLag
   - Aurora Serverless v2 (writer or reader): CPU, FreeMemoryGB, Connections, ACUUtilization, ServerlessDatabaseCapacity, plus ReplicaLag/ReaderReplicaLag based on role and reader presence
2. WHEN `_get_alarm_defs()` is called with resource type `AuroraRDS`, THE Alarm_Manager SHALL inspect `resource_tags` to determine the instance variant and return the appropriate filtered alarm list
3. THE Alarm_Manager SHALL pass `resource_tags` to `_get_alarm_defs()` for all AuroraRDS alarm definition lookups

### Requirement 12: Steering Documentation and Known Issues Update

**User Story:** As a developer, I want the alarm-rules steering document and known issues to reflect the new alarm variants, so that future development follows the updated rules.

#### Acceptance Criteria

1. THE Monitoring_Engine SHALL update the AuroraRDS section of the `alarm-rules.md` steering document to include the new metric keys: `ReaderReplicaLag`, `ACUUtilization`, `ServerlessDatabaseCapacity`
2. THE Monitoring_Engine SHALL update `KNOWN-ISSUES.md` entries KI-006 and KI-007 to reference the engine's active mitigation (alarm skip) instead of the current passive workaround (`TreatMissingData` + manual `off` tag)
3. THE Monitoring_Engine SHALL add the new metric keys to the `_metric_name_to_key()` mapping: `AuroraReplicaLag` → `ReaderReplicaLag`, `ACUUtilization` → `ACUUtilization`, `ServerlessDatabaseCapacity` → `ServerlessDatabaseCapacity`

### Requirement 13: Remediation Handler Delete Event Aurora Alarm Cleanup (KI-008)

**User Story:** As a monitoring operator, I want the Remediation Handler to reliably delete Aurora alarms when an Aurora instance is deleted, even when `describe_db_instances` fails because the instance no longer exists.

#### Acceptance Criteria

1. WHEN the Remediation_Handler receives a `DeleteDBInstance` CloudTrail event and `_resolve_rds_aurora_type()` fails (returns `"RDS"` fallback), THE Remediation_Handler SHALL search for alarms with both `"RDS"` and `"AuroraRDS"` prefixes for the given `db_instance_id`
2. WHEN the Remediation_Handler deletes alarms for a deleted RDS event, THE Remediation_Handler SHALL call `delete_alarms_for_resource()` for both `"RDS"` and `"AuroraRDS"` resource types to ensure no orphan alarms remain
3. THE Remediation_Handler SHALL log a warning when falling back to dual-prefix search due to `_resolve_rds_aurora_type()` failure
