# Orphan Alarm Cleanup Fix — Bugfix Design

## Overview

`_cleanup_orphan_alarms` in `daily_monitor/lambda_handler.py` incorrectly identifies alive resources for MQ, APIGW (HTTP/WebSocket), and ACM resource types due to ID format mismatches between alarm TagNames and the `_find_alive_*` functions. The fix moves alive-check responsibility into each collector module via a new `resolve_alive_ids(tag_names)` method on `CollectorProtocol`, so each collector owns both ID creation (in `collect_monitored_resources`) and ID verification (in `resolve_alive_ids`). This eliminates the hardcoded `alive_checkers` dict and duplicate boto3 client singletons from `lambda_handler.py`.

## Glossary

- **Bug_Condition (C)**: The condition where alarm TagNames use a format (MQ suffix, APIGW composite, ACM domain) that the corresponding `_find_alive_*` function cannot match against AWS API results
- **Property (P)**: Each collector's `resolve_alive_ids` correctly maps TagNames back to AWS resource identifiers and returns the original TagNames for resources that exist
- **Preservation**: All existing resource types (EC2, RDS, ELB, TG, ElastiCache, NAT, Lambda, VPN, Backup, CLB, OpenSearch) continue to correctly identify alive/orphan resources
- **`_shorten_elb_resource_id()`**: Function in `common/alarm_naming.py` that produces the TagName embedded in alarm names — the "short ID" that `resolve_alive_ids` must reverse-map
- **`_COLLECTOR_MODULES`**: List in `lambda_handler.py` of all collector modules, already used for resource collection and metric processing
- **`resolve_alive_ids(tag_names)`**: New method on `CollectorProtocol` that accepts a set of TagNames (as extracted from alarm names) and returns the subset whose underlying AWS resources still exist

## Bug Details

### Bug Condition

The bug manifests when `_cleanup_orphan_alarms` extracts TagNames from alarm names and passes them to `_find_alive_*` functions that expect a different ID format. Three resource types are affected:

1. **MQ**: Alarm TagName = `broker-name-1` (instance ID with `-1`/`-2` suffix), but `_find_alive_mq_brokers` compares against `BrokerName` (no suffix)
2. **APIGW**: Alarm TagName = `api-name/api-id` (composite), but `_find_alive_apigw_apis` checks `api.get("name")` and `api["ApiId"]` individually — neither matches the composite
3. **ACM**: Alarm TagName = `e2e-test.internal` (domain name from Name tag), but `_find_alive_acm_certificates` calls `describe_certificate(CertificateArn=domain_name)` — a domain is not a valid ARN

**Formal Specification:**
```
FUNCTION isBugCondition(resource_type, tag_name)
  INPUT: resource_type of type str, tag_name of type str
  OUTPUT: boolean

  IF resource_type == "MQ":
    RETURN tag_name matches pattern "{broker_name}-{1|2}"
           AND broker_name exists in AWS (list_brokers)
           AND _find_alive_mq_brokers({tag_name}) returns empty set
  
  IF resource_type == "APIGW":
    RETURN tag_name matches pattern "{api_name}/{api_id}"
           AND api exists in AWS (get_apis by api_id)
           AND _find_alive_apigw_apis({tag_name}) returns empty set
  
  IF resource_type == "ACM":
    RETURN tag_name is a domain name (not an ARN)
           AND a matching ISSUED certificate exists in AWS
           AND _find_alive_acm_certificates({tag_name}) returns empty set
  
  RETURN false  -- other resource types are not affected
END FUNCTION
```

### Examples

- **MQ**: Alarm `[MQ] my-broker MqCPU >=80% (TagName: my-broker-1)` → TagName `my-broker-1` → `_find_alive_mq_brokers({"my-broker-1"})` checks `BrokerName == "my-broker-1"` → no match (actual BrokerName is `my-broker`) → alive broker's alarm deleted as orphan
- **APIGW HTTP**: Alarm `[APIGW] my-api ApiLatency >=5s (TagName: my-api/abc123)` → TagName `my-api/abc123` → `_find_alive_apigw_apis({"my-api/abc123"})` checks `api.get("name") == "my-api/abc123"` and `api["ApiId"] == "my-api/abc123"` → no match → alive API's alarm never recognized
- **ACM**: Alarm `[ACM] e2e-test.internal DaysToExpiry <=30d (TagName: e2e-test.internal)` → TagName `e2e-test.internal` → `_find_alive_acm_certificates({"e2e-test.internal"})` calls `describe_certificate(CertificateArn="e2e-test.internal")` → ClientError (invalid ARN) → alive cert's alarm deleted as orphan
- **EC2 (not affected)**: Alarm `[EC2] my-server CPU >=80% (TagName: i-0abc123)` → TagName `i-0abc123` → `_find_alive_ec2_instances({"i-0abc123"})` → correct match → no bug

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- EC2 alive check: `describe_instances` with instance IDs, excluding terminated/shutting-down
- RDS/AuroraRDS/DocDB alive check: `describe_db_instances` with DB identifier
- ELB/ALB/NLB/TG alive check: `describe_load_balancers`/`describe_target_groups` with ARNs, non-ARN IDs treated as alive
- ElastiCache alive check: `describe_cache_clusters` with cluster ID
- NAT Gateway alive check: `describe_nat_gateways` excluding deleted/deleting
- Lambda alive check: `get_function` with function name
- VPN alive check: `describe_vpn_connections` excluding deleted/deleting
- Backup alive check: `describe_backup_vault` with vault name
- CLB alive check: `describe_load_balancers` (classic) with LB name
- OpenSearch alive check: `describe_domains` excluding deleted domains
- Unknown resource types: log warning and skip orphan cleanup
- Batch deletion: delete orphan alarms in batches of 100

**Scope:**
All inputs that do NOT involve MQ, APIGW (HTTP/WS), or ACM resource types should be completely unaffected by this fix. The refactoring from `alive_checkers` dict to collector-based `resolve_alive_ids` must produce identical results for all existing resource types.

## Hypothesized Root Cause

Based on the bug analysis, the root cause is an **ID format mismatch** between alarm TagNames and the alive-checker functions:

1. **MQ Suffix Mismatch**: `_broker_instance_ids()` in `mq.py` appends `-1`/`-2` to BrokerName for CW dimension purposes. `_shorten_elb_resource_id()` passes this through unchanged (MQ is not ALB/NLB/TG). But `_find_alive_mq_brokers()` compares against `BrokerName` from `list_brokers` which has no suffix.

2. **APIGW Composite ID Mismatch**: `_shorten_elb_resource_id()` produces `{api_name}/{api_id}` for HTTP/WS APIs. But `_find_alive_apigw_apis()` checks `api.get("name")` and `api["ApiId"]` as separate values — neither equals the composite `name/id` string.

3. **ACM Domain-as-ARN Mismatch**: `_shorten_elb_resource_id()` returns the `Name` tag (domain name) for ACM. But `_find_alive_acm_certificates()` passes this domain name directly to `describe_certificate(CertificateArn=...)`, which expects an ARN, not a domain name.

4. **Architectural Root Cause**: The `alive_checkers` dict in `lambda_handler.py` is maintained separately from the collectors that define how resource IDs are created. This separation means the alive-check logic doesn't know about the ID transformations applied by `_shorten_elb_resource_id()`. Moving alive-check into each collector eliminates this knowledge gap.

## Correctness Properties

Property 1: Bug Condition — MQ TagName Resolution

_For any_ set of MQ alarm TagNames with `-1` or `-2` suffix where the base broker name (suffix stripped) exists in AWS `list_brokers`, the MQ collector's `resolve_alive_ids` SHALL return those TagNames in the alive set.

**Validates: Requirements 2.1**

Property 2: Bug Condition — APIGW Composite TagName Resolution

_For any_ set of APIGW alarm TagNames in `{api_name}/{api_id}` composite format where the API exists in AWS (REST by name, v2 by ApiId), the APIGW collector's `resolve_alive_ids` SHALL return those TagNames in the alive set.

**Validates: Requirements 2.2**

Property 3: Bug Condition — ACM Domain TagName Resolution

_For any_ set of ACM alarm TagNames containing domain names where a matching non-expired ISSUED certificate exists in AWS, the ACM collector's `resolve_alive_ids` SHALL return those domain names in the alive set.

**Validates: Requirements 2.3**

Property 4: Preservation — Simple Collector Alive Resolution

_For any_ set of TagNames for simple resource types (EC2, RDS, ElastiCache, NAT, Lambda, VPN, Backup, CLB, OpenSearch) where TagName equals the AWS resource identifier, the collector's `resolve_alive_ids` SHALL return the same alive set as the original `_find_alive_*` function in `lambda_handler.py`.

**Validates: Requirements 3.1, 3.2, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10**

Property 5: Preservation — ELB/ALB/NLB/TG Alive Resolution

_For any_ set of TagNames for ELB resource types (ALB, NLB, TG) where TagNames are ARNs or short IDs, the ELB collector's `resolve_alive_ids` SHALL return the same alive set as the original `_find_alive_elb_resources` function.

**Validates: Requirements 3.3**

Property 6: Preservation — Collector-Based Delegation Equivalence

_For any_ alarm map produced by `_collect_alarm_resource_ids`, the refactored `_cleanup_orphan_alarms` using collector-based `resolve_alive_ids` SHALL identify the same set of orphan alarms as the original implementation for all non-buggy resource types, and correctly identify alive resources for buggy types (MQ, APIGW, ACM).

**Validates: Requirements 2.4, 3.11, 3.12**

## Fix Implementation

### Changes Required

Assuming our root cause analysis is correct:

**File**: `common/collectors/base.py`

**Change**: Add `resolve_alive_ids` to `CollectorProtocol`

1. **Add method to Protocol**: Add `resolve_alive_ids(tag_names: set[str]) -> set[str]` to `CollectorProtocol`. This is the new interface method each collector must implement.

**File**: `common/collectors/ec2.py`

**Function**: `resolve_alive_ids`

2. **EC2 resolve_alive_ids**: Implement using existing `_get_ec2_client()`. Accept instance IDs, call `describe_instances` in batches of 200, exclude terminated/shutting-down. Same logic as current `_find_alive_ec2_instances`.

**File**: `common/collectors/rds.py`

**Function**: `resolve_alive_ids`

3. **RDS resolve_alive_ids**: Implement using existing `_get_rds_client()`. Accept DB identifiers, call `describe_db_instances` per ID. Same logic as current `_find_alive_rds_instances`. Note: DocDB uses the same RDS API, so `docdb.py` gets its own implementation too.

**File**: `common/collectors/elb.py`

**Function**: `resolve_alive_ids`

4. **ELB resolve_alive_ids**: Implement using existing `_get_elbv2_client()`. Accept ARNs and short IDs, separate into LB ARNs, TG ARNs, and other IDs (treated as alive). Same logic as current `_find_alive_elb_resources`.

**File**: `common/collectors/mq.py`

**Function**: `resolve_alive_ids`

5. **MQ resolve_alive_ids (custom)**: Strip `-1`/`-2` suffix from each TagName to get base broker name. Call `list_brokers` via existing `_get_mq_client()`. If base name found, add the original TagName (with suffix) to alive set.

**File**: `common/collectors/apigw.py`

**Function**: `resolve_alive_ids`

6. **APIGW resolve_alive_ids (custom)**: For each TagName, check if it contains `/` (composite format). If so, split into `api_name/api_id` and check v2 APIs by `ApiId`. For non-composite TagNames (REST), check by name. Use existing `_get_apigw_client()` and `_get_apigwv2_client()`.

**File**: `common/collectors/acm.py`

**Function**: `resolve_alive_ids`

7. **ACM resolve_alive_ids (custom)**: Call `list_certificates(CertificateStatuses=["ISSUED"])` + `describe_certificate` to build a set of domain names for non-expired certs. Return intersection with input TagNames. Use existing `_get_acm_client()`.

**Files**: `common/collectors/elasticache.py`, `natgw.py`, `lambda_fn.py`, `vpn.py`, `backup.py`, `clb.py`, `opensearch.py`, `docdb.py`

8. **Simple collectors resolve_alive_ids**: Each implements its own `resolve_alive_ids` using its existing boto3 client singleton. Logic is moved directly from the corresponding `_find_alive_*` function in `lambda_handler.py`.

**File**: `daily_monitor/lambda_handler.py`

**Function**: `_cleanup_orphan_alarms`

9. **Build resource_type → collector mapping**: Derive a `dict[str, module]` from `_COLLECTOR_MODULES` by calling `collect_monitored_resources` type field or by building a static mapping. Since collectors produce resources with a `type` field, we can build a `_RESOURCE_TYPE_TO_COLLECTOR` dict statically (mapping resource type strings to collector modules).

10. **Refactor `_cleanup_orphan_alarms`**: Replace `alive_checkers` dict with collector lookup. For each `rtype` in `alarm_map`, find the collector module from `_RESOURCE_TYPE_TO_COLLECTOR`, call `collector.resolve_alive_ids(resource_ids)`.

11. **Remove duplicate boto3 singletons**: Delete `_get_mq_client`, `_get_acm_client`, `_get_apigw_client`, `_get_apigwv2_client`, `_get_lambda_client`, `_get_backup_client`, `_get_classic_elb_client`, `_get_opensearch_client`, `_get_elasticache_client` from `lambda_handler.py`. Keep `_get_cw_client`, `_get_ec2_client`, `_get_rds_client`, `_get_elb_client` only if still used by other functions in `lambda_handler.py`.

12. **Remove `_find_alive_*` functions**: Delete all `_find_alive_*` functions and their helpers (`_check_ec2_individually`, `_check_elb_arns`, `_check_tg_arns`) from `lambda_handler.py`.

13. **Handle type aliases**: The `alive_checkers` dict has aliases like `NATGateway` → `_find_alive_nat_gateways` and `AuroraRDS`/`DocDB` → `_find_alive_rds_instances`. The `_RESOURCE_TYPE_TO_COLLECTOR` mapping must include these aliases:
    - `AuroraRDS` → `rds_collector` (RDS and AuroraRDS share the same RDS API)
    - `DocDB` → `docdb_collector`
    - `NATGateway` → `natgw_collector` (legacy alias for `NAT`)
    - `ELB` → `elb_collector` (legacy alias, same as ALB/NLB/TG)

## Testing Strategy

### Validation Approach

The testing strategy follows a two-phase approach: first, surface counterexamples that demonstrate the bug on unfixed code, then verify the fix works correctly and preserves existing behavior.

### Exploratory Bug Condition Checking

**Goal**: Surface counterexamples that demonstrate the bug BEFORE implementing the fix. Confirm or refute the root cause analysis. If we refute, we will need to re-hypothesize.

**Test Plan**: Write tests that call the existing `_find_alive_*` functions with TagNames in the format produced by `_shorten_elb_resource_id()`, using moto-mocked AWS services with actual resources present. Run these tests on the UNFIXED code to observe failures.

**Test Cases**:
1. **MQ Suffix Test**: Create an MQ broker `my-broker`, call `_find_alive_mq_brokers({"my-broker-1"})` → expect empty set (will fail to find alive broker on unfixed code)
2. **APIGW Composite Test**: Create an HTTP API `my-api` with id `abc123`, call `_find_alive_apigw_apis({"my-api/abc123"})` → expect empty set (will fail on unfixed code)
3. **ACM Domain Test**: Create an ACM cert for `e2e-test.internal`, call `_find_alive_acm_certificates({"e2e-test.internal"})` → expect empty set (will fail on unfixed code)
4. **EC2 Control Test**: Create an EC2 instance `i-abc`, call `_find_alive_ec2_instances({"i-abc"})` → expect `{"i-abc"}` (should pass on unfixed code, confirming EC2 is not affected)

**Expected Counterexamples**:
- MQ: `_find_alive_mq_brokers({"my-broker-1"})` returns `set()` even though broker `my-broker` exists
- APIGW: `_find_alive_apigw_apis({"my-api/abc123"})` returns `set()` even though API `abc123` exists
- ACM: `_find_alive_acm_certificates({"e2e-test.internal"})` returns `set()` (or raises ClientError) even though cert exists

### Fix Checking

**Goal**: Verify that for all inputs where the bug condition holds, the fixed `resolve_alive_ids` produces the expected behavior.

**Pseudocode:**
```
FOR ALL (resource_type, tag_names) WHERE isBugCondition(resource_type, tag_name) DO
  collector := get_collector_for_type(resource_type)
  alive := collector.resolve_alive_ids(tag_names)
  ASSERT tag_name IN alive  -- the alive resource should be recognized
END FOR
```

### Preservation Checking

**Goal**: Verify that for all inputs where the bug condition does NOT hold, the fixed `resolve_alive_ids` produces the same result as the original `_find_alive_*` function.

**Pseudocode:**
```
FOR ALL (resource_type, tag_names) WHERE NOT isBugCondition(resource_type, tag_name) DO
  original_alive := _find_alive_original(resource_type, tag_names)
  collector := get_collector_for_type(resource_type)
  new_alive := collector.resolve_alive_ids(tag_names)
  ASSERT original_alive == new_alive
END FOR
```

**Testing Approach**: Property-based testing is recommended for preservation checking because:
- It generates many tag_name combinations automatically across the input domain
- It catches edge cases (empty sets, single items, mixed alive/dead resources)
- It provides strong guarantees that behavior is unchanged for all non-buggy resource types

**Test Plan**: Observe behavior on UNFIXED code first for simple resource types (EC2, RDS, etc.), then write property-based tests capturing that behavior against the new `resolve_alive_ids` implementations.

**Test Cases**:
1. **EC2 Preservation**: Generate random instance IDs, mock some as alive/terminated, verify `ec2_collector.resolve_alive_ids` matches `_find_alive_ec2_instances`
2. **RDS Preservation**: Generate random DB identifiers, mock some as existing/not-found, verify `rds_collector.resolve_alive_ids` matches `_find_alive_rds_instances`
3. **ELB Preservation**: Generate random ARNs and short IDs, verify `elb_collector.resolve_alive_ids` matches `_find_alive_elb_resources`
4. **Simple Collector Preservation**: For each of ElastiCache, NAT, Lambda, VPN, Backup, CLB, OpenSearch — verify `resolve_alive_ids` matches the original function

### Unit Tests

- Test MQ `resolve_alive_ids` with suffix stripping for SINGLE_INSTANCE and ACTIVE_STANDBY brokers
- Test APIGW `resolve_alive_ids` with composite `name/id` format for HTTP/WS and plain name for REST
- Test ACM `resolve_alive_ids` with domain names, including expired certs (should not be alive)
- Test each simple collector's `resolve_alive_ids` with existing and non-existing resources
- Test `_RESOURCE_TYPE_TO_COLLECTOR` mapping includes all type aliases (AuroraRDS, NATGateway, ELB)
- Test `_cleanup_orphan_alarms` integration with collector-based resolution

### Property-Based Tests

- Generate random MQ broker names and suffixes, verify `resolve_alive_ids` correctly strips suffix and matches
- Generate random APIGW api names and IDs, verify composite format resolution
- Generate random domain names for ACM, verify domain-based matching
- Generate random resource IDs for simple collectors, verify preservation against original behavior

### Integration Tests

- Test full `_cleanup_orphan_alarms` flow with mixed resource types including MQ, APIGW, ACM
- Test that duplicate boto3 clients are removed (no `_get_mq_client` etc. in lambda_handler)
- Test that unknown resource types still log warning and skip
- Test batch deletion of orphan alarms (>100 alarms)
