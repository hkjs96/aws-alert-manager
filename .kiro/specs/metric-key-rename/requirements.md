# Requirements Document

## Introduction

The AWS Monitoring Engine uses abbreviated internal metric keys (e.g., `"CPU"`, `"Memory"`, `"ELB5XX"`) in hardcoded alarm definitions (`_*_ALARMS`), `HARDCODED_DEFAULTS`, `_METRIC_DISPLAY`, and threshold tag resolution. These internal keys differ from the actual CloudWatch metric names (e.g., `"CPUUtilization"`, `"mem_used_percent"`, `"HTTPCode_ELB_5XX_Count"`), causing three concrete problems:

1. **Duplicate alarm creation**: A tag `Threshold_CPUUtilization=10` creates a dynamic alarm instead of overriding the hardcoded CPU alarm, because `"CPUUtilization"` does not match the hardcoded key `"CPU"`.
2. **Unintuitive tag names**: Users must learn internal key names (`Threshold_CPU`, `Threshold_FreeMemoryGB`) instead of using CloudWatch metric names directly (`Threshold_CPUUtilization`, `Threshold_FreeableMemory`).
3. **Unnecessary complexity**: The `_metric_name_to_key()` mapping function exists solely to bridge the gap between CloudWatch names and internal keys.

This feature renames all `"metric"` fields in alarm definitions to match their `"metric_name"` (CloudWatch metric name) exactly, eliminating the indirection layer. A legacy fallback mapping ensures existing alarms with old `metric_key` values in `AlarmDescription` continue to be matched during the transition period.

## Glossary

- **Alarm_Manager**: The module `common/alarm_manager.py` responsible for creating, syncing, and deleting CloudWatch alarms.
- **Tag_Resolver**: The module `common/tag_resolver.py` responsible for resolving threshold values from tags, environment variables, and hardcoded defaults.
- **Daily_Monitor**: The Lambda handler `daily_monitor/lambda_handler.py` that collects metrics and compares them against thresholds.
- **Hardcoded_Alarm_Defs**: The lists `_EC2_ALARMS`, `_RDS_ALARMS`, `_ALB_ALARMS`, `_NLB_ALARMS`, `_TG_ALARMS` in Alarm_Manager that define default alarm configurations.
- **HARDCODED_DEFAULTS**: The dictionary in `common/__init__.py` mapping metric keys to default threshold values.
- **Metric_Key**: The `"metric"` field value in a Hardcoded_Alarm_Def entry, used as the canonical identifier for threshold lookup, tag matching, and alarm metadata.
- **Metric_Name**: The `"metric_name"` field value in a Hardcoded_Alarm_Def entry, representing the actual CloudWatch metric name.
- **METRIC_DISPLAY**: The dictionary `_METRIC_DISPLAY` in Alarm_Manager mapping Metric_Key to display name, direction, and unit for alarm naming.
- **Legacy_Metric_Key**: An old-format Metric_Key (e.g., `"CPU"`, `"Memory"`, `"ELB5XX"`) stored in existing alarm `AlarmDescription` metadata.
- **Metric_Name_To_Key**: The function `_metric_name_to_key()` in Alarm_Manager that maps CloudWatch metric names to internal keys.
- **Resolve_Metric_Key**: The function `_resolve_metric_key()` in Alarm_Manager that extracts the Metric_Key from alarm metadata with fallback.
- **Disk_Path_Metric**: A Disk metric with a path suffix, e.g., `"disk_used_percent_root"` (new) or `"Disk_root"` (legacy).

## Requirements

### Requirement 1: Rename EC2 Hardcoded Alarm Definition Keys

**User Story:** As a developer, I want EC2 alarm definition keys to match CloudWatch metric names, so that tag-based threshold overrides work without a translation layer.

#### Acceptance Criteria

1. THE Alarm_Manager SHALL use `"CPUUtilization"` as the Metric_Key for the EC2 CPU alarm definition (previously `"CPU"`).
2. THE Alarm_Manager SHALL use `"mem_used_percent"` as the Metric_Key for the EC2 Memory alarm definition (previously `"Memory"`).
3. THE Alarm_Manager SHALL use `"disk_used_percent"` as the Metric_Key for the EC2 Disk alarm definition (previously `"Disk"`).
4. THE Alarm_Manager SHALL use `"StatusCheckFailed"` as the Metric_Key for the EC2 StatusCheckFailed alarm definition (unchanged).

### Requirement 2: Rename RDS Hardcoded Alarm Definition Keys

**User Story:** As a developer, I want RDS alarm definition keys to match CloudWatch metric names, so that threshold tags use intuitive CloudWatch names.

#### Acceptance Criteria

1. THE Alarm_Manager SHALL use `"CPUUtilization"` as the Metric_Key for the RDS CPU alarm definition (previously `"CPU"`).
2. THE Alarm_Manager SHALL use `"FreeableMemory"` as the Metric_Key for the RDS FreeMemory alarm definition (previously `"FreeMemoryGB"`), retaining the `transform_threshold` lambda that converts GB to bytes.
3. THE Alarm_Manager SHALL use `"FreeStorageSpace"` as the Metric_Key for the RDS FreeStorage alarm definition (previously `"FreeStorageGB"`), retaining the `transform_threshold` lambda that converts GB to bytes.
4. THE Alarm_Manager SHALL use `"DatabaseConnections"` as the Metric_Key for the RDS Connections alarm definition (previously `"Connections"`).
5. THE Alarm_Manager SHALL use `"ReadLatency"` as the Metric_Key for the RDS ReadLatency alarm definition (unchanged).
6. THE Alarm_Manager SHALL use `"WriteLatency"` as the Metric_Key for the RDS WriteLatency alarm definition (unchanged).

### Requirement 3: Rename ALB Hardcoded Alarm Definition Keys

**User Story:** As a developer, I want ALB alarm definition keys to match CloudWatch metric names, so that tag names are consistent with CloudWatch.

#### Acceptance Criteria

1. THE Alarm_Manager SHALL use `"RequestCount"` as the Metric_Key for the ALB RequestCount alarm definition (unchanged).
2. THE Alarm_Manager SHALL use `"HTTPCode_ELB_5XX_Count"` as the Metric_Key for the ALB 5XX alarm definition (previously `"ELB5XX"`).
3. THE Alarm_Manager SHALL use `"TargetResponseTime"` as the Metric_Key for the ALB TargetResponseTime alarm definition (unchanged).

### Requirement 4: Rename NLB Hardcoded Alarm Definition Keys

**User Story:** As a developer, I want NLB alarm definition keys to match CloudWatch metric names, so that tag names are consistent with CloudWatch.

#### Acceptance Criteria

1. THE Alarm_Manager SHALL use `"ProcessedBytes"` as the Metric_Key for the NLB ProcessedBytes alarm definition (unchanged).
2. THE Alarm_Manager SHALL use `"ActiveFlowCount"` as the Metric_Key for the NLB ActiveFlowCount alarm definition (unchanged).
3. THE Alarm_Manager SHALL use `"NewFlowCount"` as the Metric_Key for the NLB NewFlowCount alarm definition (unchanged).
4. THE Alarm_Manager SHALL use `"TCP_Client_Reset_Count"` as the Metric_Key for the NLB TCPClientReset alarm definition (previously `"TCPClientReset"`).
5. THE Alarm_Manager SHALL use `"TCP_Target_Reset_Count"` as the Metric_Key for the NLB TCPTargetReset alarm definition (previously `"TCPTargetReset"`).

### Requirement 5: Rename TG Hardcoded Alarm Definition Keys

**User Story:** As a developer, I want TG alarm definition keys to match CloudWatch metric names, so that tag names are consistent with CloudWatch.

#### Acceptance Criteria

1. THE Alarm_Manager SHALL use `"HealthyHostCount"` as the Metric_Key for the TG HealthyHostCount alarm definition (unchanged).
2. THE Alarm_Manager SHALL use `"UnHealthyHostCount"` as the Metric_Key for the TG UnHealthyHostCount alarm definition (unchanged).
3. THE Alarm_Manager SHALL use `"RequestCountPerTarget"` as the Metric_Key for the TG RequestCountPerTarget alarm definition (unchanged).
4. THE Alarm_Manager SHALL use `"TargetResponseTime"` as the Metric_Key for the TG TargetResponseTime alarm definition (previously `"TGResponseTime"`).

### Requirement 6: Update HARDCODED_DEFAULTS Keys

**User Story:** As a developer, I want HARDCODED_DEFAULTS to use CloudWatch metric names as keys, so that threshold fallback lookup is consistent with the renamed Metric_Keys.

#### Acceptance Criteria

1. THE HARDCODED_DEFAULTS dictionary SHALL use `"CPUUtilization"` as the key for the CPU default threshold (previously `"CPU"`).
2. THE HARDCODED_DEFAULTS dictionary SHALL use `"mem_used_percent"` as the key for the Memory default threshold (previously `"Memory"`).
3. THE HARDCODED_DEFAULTS dictionary SHALL use `"disk_used_percent"` as the key for the Disk default threshold (previously `"Disk"`).
4. THE HARDCODED_DEFAULTS dictionary SHALL use `"FreeableMemory"` as the key for the FreeMemory default threshold (previously `"FreeMemoryGB"`).
5. THE HARDCODED_DEFAULTS dictionary SHALL use `"FreeStorageSpace"` as the key for the FreeStorage default threshold (previously `"FreeStorageGB"`).
6. THE HARDCODED_DEFAULTS dictionary SHALL use `"DatabaseConnections"` as the key for the Connections default threshold (previously `"Connections"`).
7. THE HARDCODED_DEFAULTS dictionary SHALL use `"HTTPCode_ELB_5XX_Count"` as the key for the ELB5XX default threshold (previously `"ELB5XX"`).
8. THE HARDCODED_DEFAULTS dictionary SHALL use `"TCP_Client_Reset_Count"` as the key for the TCPClientReset default threshold (previously `"TCPClientReset"`).
9. THE HARDCODED_DEFAULTS dictionary SHALL use `"TCP_Target_Reset_Count"` as the key for the TCPTargetReset default threshold (previously `"TCPTargetReset"`).
10. THE HARDCODED_DEFAULTS dictionary SHALL use `"TargetResponseTime"` as the key for the TargetResponseTime default threshold (unchanged, but `"TGResponseTime"` entry removed).
11. THE HARDCODED_DEFAULTS dictionary SHALL retain unchanged keys: `"StatusCheckFailed"`, `"RequestCount"`, `"HealthyHostCount"`, `"ProcessedBytes"`, `"ActiveFlowCount"`, `"NewFlowCount"`, `"ReadLatency"`, `"WriteLatency"`, `"UnHealthyHostCount"`, `"RequestCountPerTarget"`.

### Requirement 7: Update METRIC_DISPLAY Mapping

**User Story:** As a developer, I want METRIC_DISPLAY to be keyed by CloudWatch metric names, so that alarm name formatting uses the correct display values after the key rename.

#### Acceptance Criteria

1. THE METRIC_DISPLAY dictionary SHALL be re-keyed so that each entry uses the CloudWatch metric name as its key (matching the new Metric_Key values).
2. WHEN a Metric_Key that was renamed is looked up in METRIC_DISPLAY, THE Alarm_Manager SHALL return the same display name, direction, and unit as before the rename.
3. THE METRIC_DISPLAY dictionary SHALL remove the separate `"TGResponseTime"` entry, since TG now uses `"TargetResponseTime"` as its Metric_Key (same as ALB).

### Requirement 8: Update Tag_Resolver Disk Prefix Pattern

**User Story:** As a developer, I want the Disk threshold tag prefix to match the new CloudWatch-based Metric_Key, so that disk path tags are consistent.

#### Acceptance Criteria

1. THE Tag_Resolver SHALL recognize `Threshold_disk_used_percent_{path}` as the tag pattern for disk path thresholds (previously `Threshold_Disk_{path}`).
2. THE Tag_Resolver `get_threshold` function SHALL use `"disk_used_percent"` as the base metric for disk path fallback to environment variables and HARDCODED_DEFAULTS (previously `"Disk"`).
3. THE Tag_Resolver `get_disk_thresholds` function SHALL scan for tags with prefix `Threshold_disk_used_percent_` (previously `Threshold_Disk_`).
4. WHEN a `Threshold_disk_used_percent_root` tag is set to `85`, THE Tag_Resolver SHALL return `85.0` as the threshold for the `/` path.

### Requirement 9: Update Daily_Monitor Threshold Comparison Keys

**User Story:** As a developer, I want the daily monitor to use CloudWatch metric names for threshold comparison, so that the comparison logic is consistent with the renamed keys.

#### Acceptance Criteria

1. THE Daily_Monitor `_process_resource` function SHALL use `"FreeableMemory"` and `"FreeStorageSpace"` as the metric names for the less-than threshold comparison (previously `"FreeMemoryGB"` and `"FreeStorageGB"`).
2. WHEN a metric value for `"FreeableMemory"` is below the threshold, THE Daily_Monitor SHALL send an alert.
3. WHEN a metric value for `"FreeStorageSpace"` is below the threshold, THE Daily_Monitor SHALL send an alert.

### Requirement 10: Remove Metric_Name_To_Key Function

**User Story:** As a developer, I want to remove the `_metric_name_to_key()` translation function, so that the codebase has no unnecessary indirection between CloudWatch names and internal keys.

#### Acceptance Criteria

1. THE Alarm_Manager SHALL remove the `_metric_name_to_key()` function entirely.
2. THE Alarm_Manager SHALL not contain any mapping from CloudWatch metric names to abbreviated internal keys (the mapping is no longer needed because Metric_Key equals Metric_Name).

### Requirement 11: Legacy Metric_Key Compatibility in Resolve_Metric_Key

**User Story:** As a developer, I want existing alarms with old metric_key values in AlarmDescription to continue being matched during sync, so that the transition does not break alarm management for already-deployed alarms.

#### Acceptance Criteria

1. THE Resolve_Metric_Key function SHALL maintain a `_LEGACY_KEY_MAP` dictionary that maps old Metric_Key values to new Metric_Key values (e.g., `"CPU"` → `"CPUUtilization"`, `"Memory"` → `"mem_used_percent"`, `"ELB5XX"` → `"HTTPCode_ELB_5XX_Count"`).
2. WHEN Resolve_Metric_Key reads a Legacy_Metric_Key from alarm metadata, THE Resolve_Metric_Key function SHALL translate the Legacy_Metric_Key to the new Metric_Key using `_LEGACY_KEY_MAP`.
3. WHEN Resolve_Metric_Key reads a current Metric_Key from alarm metadata, THE Resolve_Metric_Key function SHALL return the Metric_Key as-is.
4. IF alarm metadata contains no `metric_key` field, THEN THE Resolve_Metric_Key function SHALL fall back to using the alarm `MetricName` directly as the Metric_Key (no translation needed since Metric_Key now equals Metric_Name).

### Requirement 12: Update Sync Disk Alarm Key Matching

**User Story:** As a developer, I want sync_alarms_for_resource to match disk alarms using the new `disk_used_percent` prefix, so that disk alarm synchronization works correctly after the rename.

#### Acceptance Criteria

1. THE `_sync_disk_alarms` function SHALL identify disk alarms by checking for the `"disk_used_percent"` prefix in the metric_key (previously `"Disk"` prefix).
2. THE `_sync_disk_alarms` function SHALL construct threshold tag lookups using `disk_used_percent_{suffix}` format (previously `Disk_{suffix}`).
3. THE `_sync_off_hardcoded` function SHALL check `is_threshold_off` using the new Metric_Key format for disk metrics.

### Requirement 13: Update NLB TG Excluded Metrics Set

**User Story:** As a developer, I want the NLB TG exclusion set to use the new Metric_Key values, so that NLB-attached target groups correctly exclude ALB-only metrics.

#### Acceptance Criteria

1. THE `_NLB_TG_EXCLUDED_METRICS` set SHALL use `"TargetResponseTime"` instead of `"TGResponseTime"` (since TG Metric_Key is now `"TargetResponseTime"`).
2. THE `_NLB_TG_EXCLUDED_METRICS` set SHALL continue to include `"RequestCountPerTarget"`.

### Requirement 14: Update All Test Files

**User Story:** As a developer, I want all test files to use the new CloudWatch-based Metric_Key values, so that the test suite passes after the rename.

#### Acceptance Criteria

1. WHEN a test references a Metric_Key that was renamed, THE test SHALL use the new CloudWatch metric name.
2. WHEN a test references a `Threshold_*` tag with a renamed key, THE test SHALL use the new tag format (e.g., `Threshold_CPUUtilization` instead of `Threshold_CPU`).
3. WHEN a test references `Threshold_Disk_*` tags, THE test SHALL use `Threshold_disk_used_percent_*` format.
4. THE test suite SHALL pass with zero failures after all renames are applied.

### Requirement 15: Alarm Name Display Consistency

**User Story:** As a developer, I want alarm display names to remain human-readable after the rename, so that CloudWatch alarm names are still informative.

#### Acceptance Criteria

1. WHEN the Alarm_Manager generates an alarm name for a renamed metric, THE alarm name SHALL display the same CloudWatch metric name as before (e.g., `CPUUtilization`, `mem_used_percent`, `HTTPCode_ELB_5XX_Count`).
2. THE METRIC_DISPLAY entry for `"disk_used_percent"` SHALL produce display names with path suffixes in the same format as before (e.g., `disk_used_percent(/)`).
3. THE METRIC_DISPLAY entry for `"FreeableMemory"` SHALL display direction `<` and unit `GB`.
4. THE METRIC_DISPLAY entry for `"FreeStorageSpace"` SHALL display direction `<` and unit `GB`.
