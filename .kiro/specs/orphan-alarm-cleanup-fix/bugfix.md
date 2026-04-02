# Bugfix Requirements Document

## Introduction

`_cleanup_orphan_alarms` in `daily_monitor/lambda_handler.py` incorrectly identifies alive resources for MQ, APIGW (HTTP/WebSocket), and ACM resource types. The root cause is an ID format mismatch: alarm names contain a "short ID" produced by `_shorten_elb_resource_id()` in `common/alarm_naming.py`, but the `_find_alive_*` functions expect different ID formats. This causes alive resources' alarms to be incorrectly deleted as orphans (MQ, ACM) or alive resources to never be matched (APIGW HTTP/WS).

The proposed fix moves alive-check responsibility from hardcoded `alive_checkers` in `lambda_handler.py` into each collector module via a `resolve_alive_ids(tag_names: set[str]) -> set[str]` method on the `CollectorProtocol`, so each collector owns both ID creation and ID verification.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN an MQ broker alarm exists with TagName `broker-name-1` (instance ID with `-1`/`-2` suffix from `_broker_instance_ids()`) THEN the system fails to match it against `BrokerName` (`broker-name`) returned by `list_brokers`, causing the alive broker's alarms to be incorrectly deleted as orphans

1.2 WHEN an APIGW HTTP or WebSocket API alarm exists with TagName `api-name/api-id` (name/id format from `_shorten_elb_resource_id()`) THEN the system checks `api.get("name")` and `api["ApiId"]` individually, neither of which matches the composite `name/id` format, so the alive API's alarms are never recognized as alive

1.3 WHEN an ACM certificate alarm exists with TagName containing a domain name (e.g., `e2e-test.internal` from the Name tag via `_shorten_elb_resource_id()`) THEN the system calls `describe_certificate(CertificateArn=domain_name)` which fails because a domain name is not a valid ARN, causing the alive certificate's alarms to be incorrectly deleted as orphans

1.4 WHEN `_cleanup_orphan_alarms` runs, it uses duplicate boto3 client singletons (e.g., `_get_mq_client`, `_get_acm_client`, `_get_apigw_client`, `_get_apigwv2_client`) defined in `lambda_handler.py` that duplicate the same singletons already defined in each collector module, violating coding governance §1 and §10

### Expected Behavior (Correct)

2.1 WHEN an MQ broker alarm exists with TagName `broker-name-1` or `broker-name-2` THEN the system SHALL strip the `-1`/`-2` suffix, match the base name against `list_brokers` results, and return the original TagName as alive if the broker exists

2.2 WHEN an APIGW HTTP or WebSocket API alarm exists with TagName `api-name/api-id` THEN the system SHALL split the composite ID, match by `api_id` for v2 APIs (or by `name` for REST APIs), and return the original TagName as alive if the API exists

2.3 WHEN an ACM certificate alarm exists with TagName containing a domain name THEN the system SHALL match the domain name against `list_certificates` + `describe_certificate` results (comparing domain names, not using domain as ARN), and return the domain name as alive if a matching non-expired ISSUED certificate exists

2.4 WHEN `_cleanup_orphan_alarms` resolves alive resources THEN the system SHALL delegate to each collector module's `resolve_alive_ids()` method instead of using hardcoded `alive_checkers` dict, reusing existing collector client singletons and eliminating duplicate boto3 clients from `lambda_handler.py`

### Unchanged Behavior (Regression Prevention)

3.1 WHEN an EC2 alarm exists with TagName matching an instance ID (e.g., `i-0abc123`) THEN the system SHALL CONTINUE TO correctly identify alive/terminated instances and delete only orphan alarms

3.2 WHEN an RDS/AuroraRDS/DocDB alarm exists with TagName matching a DB identifier THEN the system SHALL CONTINUE TO correctly identify alive/deleted instances and delete only orphan alarms

3.3 WHEN an ELB/ALB/NLB/TG alarm exists with TagName matching a short ID (`name/hash`) THEN the system SHALL CONTINUE TO correctly identify alive/deleted load balancers and delete only orphan alarms

3.4 WHEN a CLB alarm exists with TagName matching a load balancer name THEN the system SHALL CONTINUE TO correctly identify alive/deleted classic load balancers and delete only orphan alarms

3.5 WHEN an ElastiCache alarm exists with TagName matching a cluster ID THEN the system SHALL CONTINUE TO correctly identify alive/deleted clusters and delete only orphan alarms

3.6 WHEN a NAT Gateway alarm exists with TagName matching a gateway ID THEN the system SHALL CONTINUE TO correctly identify alive/deleted gateways and delete only orphan alarms

3.7 WHEN a Lambda alarm exists with TagName matching a function name THEN the system SHALL CONTINUE TO correctly identify alive/deleted functions and delete only orphan alarms

3.8 WHEN a VPN alarm exists with TagName matching a connection ID THEN the system SHALL CONTINUE TO correctly identify alive/deleted connections and delete only orphan alarms

3.9 WHEN a Backup alarm exists with TagName matching a vault name THEN the system SHALL CONTINUE TO correctly identify alive/deleted vaults and delete only orphan alarms

3.10 WHEN an OpenSearch alarm exists with TagName matching a domain name THEN the system SHALL CONTINUE TO correctly identify alive/deleted domains and delete only orphan alarms

3.11 WHEN a resource type has no registered collector or alive checker THEN the system SHALL CONTINUE TO log a warning and skip orphan cleanup for that type

3.12 WHEN orphan alarms are identified THEN the system SHALL CONTINUE TO delete them in batches of 100 via CloudWatch `delete_alarms` API
