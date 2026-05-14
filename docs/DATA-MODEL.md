# Data Model

This document defines the model/entity vocabulary used by the frontend,
backend, DynamoDB, and CloudWatch-derived data.

## Entity Relationship Overview

```text
Customer 1 --- N Account
Account  1 --- N Resource        (derived from CloudWatch/account metadata)
Resource 1 --- N Alarm           (derived from CloudWatch alarms)
Resource 1 --- N AlarmConfig     (derived from CloudWatch alarm settings)
Customer 1 --- N ThresholdOverride
BulkOperation 1 --- 1 JobStatus
JobStatus 1 --- N JobResult
```

CloudWatch-derived entities are not fully persisted by this application. They
are reconstructed from AWS APIs and alarm metadata.

## Naming Policy

API JSON and backend persistence fields use `snake_case`.

Frontend-only option DTOs may use camelCase only when explicitly mapped, for
example:

```ts
interface AccountOption {
  id: string;
  name: string;
  customerId: string;
}
```

Do not introduce alternate names for the same contract field.

## Customer

Persistent entity in `CUSTOMERS_TABLE`.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `customer_id` | string | yes | Primary identifier. Created from customer `code`. |
| `name` | string | yes | Display name. |
| `provider` | `"aws" | "azure" | "gcp"` | yes | Current backend behavior defaults to `aws`. |
| `account_count` | number | yes | Calculated on list response from AccountsTable. |
| `created_at` | string | no | ISO timestamp from backend create flow. |

Frontend interface: `frontend/types/index.ts::Customer`.

## Account

Persistent entity in `ACCOUNTS_TABLE`.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `customer_id` | string | yes | Partition key / customer owner. |
| `account_id` | string | yes | AWS account id. |
| `name` | string | yes | Display name. |
| `role_arn` | string | yes | Role assumed by backend operations. |
| `regions` | string[] | yes | Target AWS regions. |
| `connection_status` | `"connected" | "failed" | "untested"` | yes | Updated by account test flow. |
| `last_tested_at` | string | no | ISO timestamp. |
| `created_at` | string | no | ISO timestamp from backend create flow. |

Frontend interface: `frontend/types/index.ts::Account`.

## Resource

CloudWatch-derived API entity.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string | yes | Resource id or tag name used by alarms. |
| `name` | string | yes | Display name. Currently often same as `id`. |
| `type` | string | yes | One of the supported resource types listed below. |
| `account` | string | yes | AWS account id parsed from alarm ARN. |
| `region` | string | yes | AWS region parsed from alarm ARN. |
| `monitoring` | boolean | yes | Whether resource is monitored. |
| `alarms` | object | yes | `{critical: number, warning: number}`. |
| `alarm_count` | number | no | Backend detail response includes count. |

Frontend interface: `frontend/types/index.ts::Resource`.

## Supported Resource Types and Alarm Registry

The supported type list must stay synchronized across:

- `backend/common/__init__.py::SUPPORTED_RESOURCE_TYPES`
- `frontend/lib/constants.ts::SUPPORTED_RESOURCE_TYPES`
- `backend/common/alarm_registry.py::_HARDCODED_METRIC_KEYS`
- `backend/common/alarm_registry.py::_NAMESPACE_MAP`
- `backend/common/alarm_registry.py::_DIMENSION_KEY_MAP`

Backend code supports 29 resource types. Frontend primary workflows currently
expose the smaller MVP list: `EC2`, `RDS`, `S3`, `Lambda`, `ALB`.

Backend registry table:

| Type | Namespace(s) | Primary dimension | Hardcoded metric keys |
| --- | --- | --- | --- |
| `ACM` | `AWS/CertificateManager` | `CertificateArn` | `DaysToExpiry` |
| `ALB` | `AWS/ApplicationELB` | `LoadBalancer` | `ELB4XX`, `HTTPCode_ELB_5XX_Count`, `RequestCount`, `TargetConnectionError`, `TargetResponseTime` |
| `APIGW` | `AWS/ApiGateway` | `ApiName` | `Api4XXError`, `Api4xx`, `Api5XXError`, `Api5xx`, `ApiLatency`, `WsConnectCount`, `WsExecutionError`, `WsIntegrationError`, `WsMessageCount` |
| `AuroraRDS` | `AWS/RDS` | `DBInstanceIdentifier` | `ACUUtilization`, `CPUUtilization`, `DatabaseConnections`, `FreeLocalStorage`, `FreeableMemory`, `ReaderReplicaLag`, `ReplicaLag`, `ServerlessDatabaseCapacity` |
| `Backup` | `AWS/Backup` | `BackupVaultName` | `BackupJobsAborted`, `BackupJobsFailed` |
| `CLB` | `AWS/ELB` | `LoadBalancerName` | `CLB4XX`, `CLB5XX`, `CLBBackend4XX`, `CLBBackend5XX`, `CLBUnHealthyHost`, `SpilloverCount`, `SurgeQueueLength` |
| `CloudFront` | `AWS/CloudFront` | `DistributionId` | `CF4xxErrorRate`, `CF5xxErrorRate`, `CFBytesDownloaded`, `CFRequests` |
| `DX` | `AWS/DX` | `ConnectionId` | `ConnectionState` |
| `DocDB` | `AWS/DocDB` | `DBInstanceIdentifier` | `CPUUtilization`, `DatabaseConnections`, `FreeableMemory` |
| `DynamoDB` | `AWS/DynamoDB` | `TableName` | `DDBReadCapacity`, `DDBSystemErrors`, `DDBWriteCapacity`, `ThrottledRequests` |
| `EC2` | `AWS/EC2`, `CWAgent` | `InstanceId` | `CPUUtilization`, `StatusCheckFailed`, `disk_used_percent`, `mem_used_percent` |
| `ECS` | `AWS/ECS` | `ServiceName` | `EcsCPU`, `EcsMemory` |
| `EFS` | `AWS/EFS` | `FileSystemId` | `BurstCreditBalance`, `EFSClientConnections`, `PercentIOLimit` |
| `ElastiCache` | `AWS/ElastiCache` | `CacheClusterId` | `CPUUtilization`, `CurrConnections`, `EngineCPU`, `Evictions`, `SwapUsage` |
| `Lambda` | `AWS/Lambda` | `FunctionName` | `Duration`, `Errors` |
| `MQ` | `AWS/AmazonMQ` | `Broker` | `HeapUsage`, `JobSchedulerStoreUsage`, `MqCPU`, `StoreUsage` |
| `MSK` | `AWS/Kafka` | `Cluster Name` | `ActiveControllerCount`, `BytesInPerSec`, `OffsetLag`, `UnderReplicatedPartitions` |
| `NAT` | `AWS/NATGateway` | `NatGatewayId` | `ErrorPortAllocation`, `PacketsDropCount` |
| `NLB` | `AWS/NetworkELB` | `LoadBalancer` | `ActiveFlowCount`, `NewFlowCount`, `ProcessedBytes`, `TCP_Client_Reset_Count`, `TCP_Target_Reset_Count` |
| `OpenSearch` | `AWS/ES` | `DomainName` | `ClusterIndexWritesBlocked`, `ClusterStatusRed`, `ClusterStatusYellow`, `JVMMemoryPressure`, `MasterCPU`, `MasterJVMMemoryPressure`, `OSFreeStorageSpace`, `OsCPU` |
| `RDS` | `AWS/RDS` | `DBInstanceIdentifier` | `CPUUtilization`, `ConnectionAttempts`, `DatabaseConnections`, `FreeStorageSpace`, `FreeableMemory`, `ReadLatency`, `WriteLatency` |
| `Route53` | `AWS/Route53` | `HealthCheckId` | `HealthCheckStatus` |
| `S3` | `AWS/S3` | `BucketName` | `S34xxErrors`, `S35xxErrors`, `S3BucketSizeBytes`, `S3NumberOfObjects` |
| `SNS` | `AWS/SNS` | `TopicName` | `SNSMessagesPublished`, `SNSNotificationsFailed` |
| `SQS` | `AWS/SQS` | `QueueName` | `SQSMessagesSent`, `SQSMessagesVisible`, `SQSOldestMessage` |
| `SageMaker` | `AWS/SageMaker` | `EndpointName` | `SMCPU`, `SMInvocationErrors`, `SMInvocations`, `SMModelLatency` |
| `TG` | `AWS/ApplicationELB`, `AWS/NetworkELB` | `TargetGroup` | `HealthyHostCount`, `RequestCountPerTarget`, `TargetResponseTime`, `UnHealthyHostCount` |
| `VPN` | `AWS/VPN` | `VpnId` | `TunnelState` |
| `WAF` | `AWS/WAFV2` | `WebACL` | `WAFAllowedRequests`, `WAFBlockedRequests`, `WAFCountedRequests` |

Global service note:

- `CloudFront` and `Route53` metrics are read from `us-east-1`.
- `WAF` is currently in the supported list, but only `CloudFront` and `Route53`
  are explicitly mapped in `_GLOBAL_SERVICE_REGION`. Treat WAF region behavior
  as implementation-sensitive and verify before changing alarm action routing.

Target group note:

- `TG` attached to an NLB excludes ALB-only metrics:
  `RequestCountPerTarget` and `TargetResponseTime`.
- `TG` with `TargetType=alb` returns no default alarm definitions because AWS
  does not publish the expected host count metrics for that case.

## Alarm

CloudWatch-derived API entity.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `id` | string | yes | Same as alarm name. |
| `alarm_name` | string | yes | CloudWatch alarm name. |
| `arn` | string | yes | CloudWatch alarm ARN. |
| `account` | string | yes | AWS account id parsed from ARN. |
| `resource` | string | yes | Resource id parsed from alarm name. |
| `type` | string | yes | Resource type parsed from alarm name. |
| `metric` | string | yes | CloudWatch metric name. |
| `state` | `"ALARM" | "OK" | "INSUFFICIENT_DATA" | "OFF" | "MUTED"` | yes | CloudWatch state plus UI states. |
| `threshold` | number | no | CloudWatch threshold. |
| `severity` | string | no | Alarm tag value, defaults to `SEV-5`. |
| `time` | string | yes | State update timestamp string. |
| `value` | string or number or null | no | Current value is not fully implemented. |

Frontend interface: `frontend/types/index.ts::Alarm`.

## AlarmConfig

Resource alarm configuration DTO.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `metric_key` | string | yes | UI/config key. May include mount path suffix. |
| `metric_name` | string | yes | CloudWatch metric name. |
| `namespace` | string | yes | CloudWatch namespace. |
| `threshold` | number | yes | Alarm threshold. |
| `unit` | string | yes | Display unit. |
| `direction` | `">" | ">=" | "<" | "<="` | yes | Comparison direction. |
| `severity` | string | yes | Severity tag. |
| `source` | `"System" | "Customer" | "Custom"` | yes | Config source. |
| `state` | Alarm state | yes | Current alarm state. |
| `current_value` | number or null | yes | Latest observed value if available. |
| `monitoring` | boolean | yes | Whether metric is monitored. |
| `mount_path` | string | no | Required for disk metrics. |
| `period` | number | no | CloudWatch period seconds. |
| `evaluation_periods` | number | no | CloudWatch evaluation periods. |
| `datapoints_to_alarm` | number | no | CloudWatch datapoints to alarm. |
| `treat_missing_data` | string | no | CloudWatch missing data policy. |
| `statistic` | string | no | CloudWatch statistic. |

Frontend interface: `frontend/types/index.ts::AlarmConfig`.

## DashboardStats

Derived API DTO.

| Field | Type | Required |
| --- | --- | --- |
| `monitored_count` | number | yes |
| `active_alarms` | number | yes |
| `unmonitored_count` | number | yes |
| `account_count` | number | yes |

Do not use legacy names such as `total_resources`,
`unmonitored_resources`, or `connected_accounts`.

Frontend interface: `frontend/types/index.ts::DashboardStats`.

## AlarmSummary

Derived API DTO.

| Field | Type | Required |
| --- | --- | --- |
| `total` | number | yes |
| `alarm_count` | number | yes |
| `ok_count` | number | yes |
| `insufficient_count` | number | yes |

Backend may also include `by_state` for diagnostics, but frontend summary cards
must depend only on the fields above.

Frontend interface: `frontend/types/api.ts::AlarmSummary`.

## ThresholdOverride

Persistent entity in `THRESHOLD_OVERRIDES_TABLE` plus merged API DTO.

Stored item:

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `scope_id` | string | yes | Format: `customer_id:{customer_id}`. |
| `metric_key` | string | yes | Sort key. |
| `resource_type` | string | yes | Resource type. |
| `threshold_value` | number | yes | Customer override value. |

Merged API DTO:

| Field | Type | Required |
| --- | --- | --- |
| `metric_key` | string | yes |
| `system_default` | number | yes |
| `customer_override` | number or null | yes |
| `unit` | string | yes |
| `direction` | `">" | "<"` | yes |

Frontend interface: `frontend/types/api.ts::ThresholdOverride`.

## JobStatus

Persistent entity in `JOB_STATUS_TABLE`.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `job_id` | string | yes | Primary key. |
| `status` | `"pending" | "in_progress" | "completed" | "partial_failure" | "failed"` | yes | Job lifecycle state. |
| `total_count` | number | yes | Total work items. |
| `completed_count` | number | yes | Completed work items. |
| `failed_count` | number | yes | Failed work items. |
| `results` | JobResult[] | no | Per-resource results. |
| `created_at` | string | no | ISO timestamp. |

Frontend interface: `frontend/types/api.ts::JobStatus`.

## RecentAlarm / Event

Derived display DTO used by dashboard and resource event panels.

| Field | Type | Required |
| --- | --- | --- |
| `timestamp` | string | yes |
| `resource_id` | string | yes |
| `account` | string | yes |
| `resource_name` | string | yes |
| `resource_type` | string | yes |
| `metric` | string | yes |
| `severity` | string | yes |
| `state_change` | string | yes |
| `value` | number | yes |
| `threshold` | number | yes |

Frontend interface: `frontend/types/index.ts::RecentAlarm`.
