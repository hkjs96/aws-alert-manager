# Requirements Document

## Introduction

Add Aurora RDS as a new monitored resource type ("AuroraRDS") to the AWS Monitoring Engine. Aurora instances share the `AWS/RDS` CloudWatch namespace and the same RDS API surface (CreateDBInstance, DeleteDBInstance, etc.) as regular RDS, but expose Aurora-specific metrics such as `FreeLocalStorage` and `AuroraReplicaLagMaximum`. The existing RDS collector must distinguish Aurora from non-Aurora instances by inspecting the `Engine` field (values containing "aurora"), and route them as separate resource types so that alarm definitions, metric collection, and orphan cleanup are handled independently.

## Glossary

- **Monitoring_Engine**: The AWS Monitoring Engine system comprising Daily Monitor and Remediation Handler Lambdas
- **RDS_Collector**: The existing `common/collectors/rds.py` module that collects RDS instance information
- **Aurora_Collector**: The new or extended collector logic that collects Aurora RDS instances (Engine field containing "aurora")
- **Alarm_Manager**: The `common/alarm_manager.py` module responsible for alarm CRUD, sync, and definitions
- **Daily_Monitor**: The Lambda function that runs daily to scan resources, sync alarms, and check metrics
- **Remediation_Handler**: The Lambda function that reacts to CloudTrail lifecycle events in real time
- **HARDCODED_DEFAULTS**: The fallback threshold dictionary in `common/__init__.py`
- **SUPPORTED_RESOURCE_TYPES**: The list of supported resource type strings in `common/__init__.py`
- **AuroraRDS**: The new resource type identifier string used in alarm naming, alarm definitions, and resource classification
- **DBInstanceIdentifier**: The CloudWatch dimension key used for both RDS and Aurora RDS instance-level metrics

## Requirements

### Requirement 1: Aurora Instance Identification

**User Story:** As a monitoring operator, I want the system to automatically distinguish Aurora instances from regular RDS instances, so that each type receives the correct set of alarms.

#### Acceptance Criteria

1. WHEN the RDS_Collector enumerates DB instances, THE RDS_Collector SHALL classify instances whose `Engine` field contains the substring "aurora" (case-insensitive) as resource type "AuroraRDS"
2. WHEN the RDS_Collector enumerates DB instances, THE RDS_Collector SHALL classify instances whose `Engine` field does not contain the substring "aurora" as resource type "RDS"
3. THE RDS_Collector SHALL support all Aurora engine variants including "aurora", "aurora-mysql", and "aurora-postgresql" by matching on the "aurora" substring
4. WHEN an Aurora instance has `Monitoring=on` tag (case-insensitive), THE RDS_Collector SHALL include the instance in the returned resource list with type "AuroraRDS"
5. WHEN an Aurora instance has status "deleting" or "deleted", THE RDS_Collector SHALL skip the instance and log the skip reason

### Requirement 2: Aurora RDS Alarm Definitions

**User Story:** As a monitoring operator, I want Aurora-specific default alarms to be created automatically, so that Aurora instances are monitored with the correct metrics and thresholds from the standard metrics reference.

#### Acceptance Criteria

1. THE Alarm_Manager SHALL define a new `_AURORA_RDS_ALARMS` list containing alarm definitions for the following metrics: CPUUtilization, FreeableMemory, DatabaseConnections, FreeLocalStorage, AuroraReplicaLagMaximum
2. WHEN the resource type is "AuroraRDS", THE Alarm_Manager SHALL return the `_AURORA_RDS_ALARMS` definitions from `_get_alarm_defs()`
3. THE Alarm_Manager SHALL configure the CPUUtilization alarm with namespace "AWS/RDS", dimension key "DBInstanceIdentifier", comparison "GreaterThanThreshold", and stat "Average"
4. THE Alarm_Manager SHALL configure the FreeableMemory alarm with namespace "AWS/RDS", dimension key "DBInstanceIdentifier", comparison "LessThanThreshold", a `transform_threshold` converting GB to bytes (multiplier 1073741824), and stat "Average"
5. THE Alarm_Manager SHALL configure the DatabaseConnections alarm with namespace "AWS/RDS", dimension key "DBInstanceIdentifier", comparison "GreaterThanThreshold", and stat "Average"
6. THE Alarm_Manager SHALL configure the FreeLocalStorage alarm with namespace "AWS/RDS", dimension key "DBInstanceIdentifier", comparison "LessThanThreshold", a `transform_threshold` converting GB to bytes (multiplier 1073741824), and stat "Average"
7. THE Alarm_Manager SHALL configure the AuroraReplicaLagMaximum alarm with namespace "AWS/RDS", dimension key "DBInstanceIdentifier", comparison "GreaterThanThreshold", stat "Maximum", and metric key "ReplicaLag"

### Requirement 3: HARDCODED_DEFAULTS and SUPPORTED_RESOURCE_TYPES Registration

**User Story:** As a monitoring operator, I want Aurora-specific metrics to have sensible fallback thresholds, so that alarms are created with correct defaults even without tag overrides.

#### Acceptance Criteria

1. THE Monitoring_Engine SHALL include "AuroraRDS" in the `SUPPORTED_RESOURCE_TYPES` list
2. THE Monitoring_Engine SHALL include a `FreeLocalStorageGB` entry in `HARDCODED_DEFAULTS` with a default value of 10.0 (GB)
3. THE Monitoring_Engine SHALL include a `ReplicaLag` entry in `HARDCODED_DEFAULTS` with a default value of 2000000.0 (microseconds)
4. THE Monitoring_Engine SHALL reuse existing `HARDCODED_DEFAULTS` entries for shared metrics: "CPU" (80.0), "FreeMemoryGB" (2.0), and "Connections" (100.0)

### Requirement 4: Aurora RDS Metric Collection

**User Story:** As a monitoring operator, I want the system to collect Aurora-specific CloudWatch metrics, so that threshold comparisons use the correct data.

#### Acceptance Criteria

1. WHEN collecting metrics for an AuroraRDS instance, THE Aurora_Collector SHALL query the following CloudWatch metrics from namespace "AWS/RDS" with dimension "DBInstanceIdentifier": CPUUtilization, FreeableMemory, DatabaseConnections, FreeLocalStorage, AuroraReplicaLagMaximum
2. WHEN the FreeableMemory metric value is retrieved, THE Aurora_Collector SHALL convert the value from bytes to GB before returning the result under key "FreeMemoryGB"
3. WHEN the FreeLocalStorage metric value is retrieved, THE Aurora_Collector SHALL convert the value from bytes to GB before returning the result under key "FreeLocalStorageGB"
4. WHEN the AuroraReplicaLagMaximum metric value is retrieved, THE Aurora_Collector SHALL return the raw value (microseconds) under key "ReplicaLag"
5. WHEN the CPUUtilization metric value is retrieved, THE Aurora_Collector SHALL return the value under key "CPU"
6. WHEN the DatabaseConnections metric value is retrieved, THE Aurora_Collector SHALL return the value under key "Connections"
7. IF no metric data is available for any individual metric, THEN THE Aurora_Collector SHALL skip that metric and log the skip at info level
8. IF no metric data is available for all metrics, THEN THE Aurora_Collector SHALL return None

### Requirement 5: Alarm Name and Metadata Display

**User Story:** As a monitoring operator, I want Aurora RDS alarms to be clearly distinguishable from regular RDS alarms, so that I can identify the resource type at a glance.

#### Acceptance Criteria

1. THE Alarm_Manager SHALL use resource type prefix "[AuroraRDS]" in alarm names for Aurora instances
2. THE Alarm_Manager SHALL include `"resource_type": "AuroraRDS"` in the AlarmDescription JSON metadata
3. THE Alarm_Manager SHALL register display entries in `_METRIC_DISPLAY` for Aurora-specific metrics: FreeLocalStorageGB mapped to ("FreeLocalStorage", "<", "GB") and ReplicaLag mapped to ("AuroraReplicaLagMaximum", ">", "μs")
4. THE Alarm_Manager SHALL use "DBInstanceIdentifier" as the dimension key in `_build_dimensions()` for resource type "AuroraRDS", producing the same dimension structure as regular RDS

### Requirement 6: Daily Monitor Integration

**User Story:** As a monitoring operator, I want the Daily Monitor to process Aurora instances alongside other resource types, so that alarms are synced and metrics are checked daily.

#### Acceptance Criteria

1. THE Daily_Monitor SHALL include the Aurora collector module in `_COLLECTOR_MODULES` so that Aurora instances are scanned during the daily run
2. WHEN the Daily_Monitor encounters a resource with type "AuroraRDS", THE Daily_Monitor SHALL invoke `sync_alarms_for_resource()` with resource type "AuroraRDS"
3. WHEN the Daily_Monitor encounters a resource with type "AuroraRDS", THE Daily_Monitor SHALL invoke the Aurora collector's `get_metrics()` for threshold comparison

### Requirement 7: Orphan Alarm Cleanup for Aurora RDS

**User Story:** As a monitoring operator, I want orphan alarms for deleted Aurora instances to be cleaned up automatically, so that stale alarms do not persist.

#### Acceptance Criteria

1. THE Daily_Monitor SHALL register "AuroraRDS" in the `alive_checkers` map of `_cleanup_orphan_alarms()`, using the same `_find_alive_rds_instances()` function (Aurora instances use the same `describe_db_instances` API)
2. WHEN the `_classify_alarm()` function encounters an alarm with prefix "[AuroraRDS]", THE Daily_Monitor SHALL classify the alarm under resource type "AuroraRDS"
3. WHEN an AuroraRDS alarm references a DB instance that no longer exists, THE Daily_Monitor SHALL delete the orphan alarm

### Requirement 8: Alarm Search Compatibility

**User Story:** As a monitoring operator, I want alarm search to find Aurora RDS alarms correctly, so that sync and delete operations work for Aurora instances.

#### Acceptance Criteria

1. WHEN searching for alarms belonging to an AuroraRDS resource, THE Alarm_Manager SHALL search with prefix "[AuroraRDS] " and filter by suffix "({db_instance_id})"
2. THE Alarm_Manager SHALL include "AuroraRDS" in the default type_prefixes fallback list within `_find_alarms_for_resource()` when no resource_type is specified

### Requirement 9: Remediation Handler Aurora Support

**User Story:** As a monitoring operator, I want the Remediation Handler to correctly identify Aurora instances from CloudTrail events, so that real-time alarm management works for Aurora resources.

#### Acceptance Criteria

1. WHEN a CreateDBInstance CloudTrail event is received for an Aurora engine, THE Remediation_Handler SHALL resolve the resource type to "AuroraRDS"
2. WHEN a DeleteDBInstance CloudTrail event is received for an Aurora instance, THE Remediation_Handler SHALL resolve the resource type to "AuroraRDS" and delete associated alarms
3. WHEN a ModifyDBInstance CloudTrail event is received for an Aurora instance, THE Remediation_Handler SHALL resolve the resource type to "AuroraRDS" and re-sync alarms
4. WHEN an AddTagsToResource or RemoveTagsFromResource CloudTrail event is received for an Aurora instance, THE Remediation_Handler SHALL resolve the resource type to "AuroraRDS"
5. THE Remediation_Handler SHALL determine whether an RDS event targets an Aurora instance by querying `describe_db_instances` and checking the Engine field for the "aurora" substring

### Requirement 10: Tag-Based Threshold Override for Aurora

**User Story:** As a monitoring operator, I want to override Aurora alarm thresholds via tags, so that I can customize monitoring per instance.

#### Acceptance Criteria

1. WHEN an AuroraRDS instance has a `Threshold_CPU` tag, THE Alarm_Manager SHALL use the tag value as the CPUUtilization alarm threshold instead of the hardcoded default
2. WHEN an AuroraRDS instance has a `Threshold_FreeMemoryGB` tag, THE Alarm_Manager SHALL use the tag value (in GB) as the FreeableMemory alarm threshold
3. WHEN an AuroraRDS instance has a `Threshold_FreeLocalStorageGB` tag, THE Alarm_Manager SHALL use the tag value (in GB) as the FreeLocalStorage alarm threshold
4. WHEN an AuroraRDS instance has a `Threshold_ReplicaLag` tag, THE Alarm_Manager SHALL use the tag value as the AuroraReplicaLagMaximum alarm threshold
5. WHEN an AuroraRDS instance has a `Threshold_Connections` tag, THE Alarm_Manager SHALL use the tag value as the DatabaseConnections alarm threshold
6. THE Alarm_Manager SHALL support dynamic alarms for AuroraRDS via `Threshold_*` tags for metrics not in the hardcoded list, using `list_metrics` API resolution within the "AWS/RDS" namespace

### Requirement 11: TypedDict and Type Annotations Update

**User Story:** As a developer, I want the type annotations to reflect the new AuroraRDS resource type, so that code is self-documenting and type-safe.

#### Acceptance Criteria

1. THE Monitoring_Engine SHALL include "AuroraRDS" as a valid value in the `type` field comment of the `ResourceInfo` TypedDict
2. THE Monitoring_Engine SHALL include "AuroraRDS" as a valid value in the `resource_type` field comment of the `AlertMessage` TypedDict
3. THE Monitoring_Engine SHALL include "AuroraRDS" as a valid value in the `resource_type` field comment of the `RemediationAlertMessage` TypedDict
4. THE Monitoring_Engine SHALL include "AuroraRDS" as a valid value in the `resource_type` field comment of the `LifecycleAlertMessage` TypedDict
