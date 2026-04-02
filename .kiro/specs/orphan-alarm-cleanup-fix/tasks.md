# Implementation Plan

- [x] 1. Write bug condition exploration test
  - **Property 1: Bug Condition** — MQ/APIGW/ACM TagName Mismatch
  - **CRITICAL**: This test MUST FAIL on unfixed code — failure confirms the bug exists
  - **DO NOT attempt to fix the test or the code when it fails**
  - **NOTE**: This test encodes the expected behavior — it will validate the fix when it passes after implementation
  - **GOAL**: Surface counterexamples that demonstrate the bug exists for MQ, APIGW, and ACM resource types
  - **Scoped PBT Approach**: Scope the property to concrete failing cases:
    - MQ: Create moto MQ broker `my-broker` (SINGLE_INSTANCE), call `_find_alive_mq_brokers({"my-broker-1"})` → expect `{"my-broker-1"}` but get `set()` on unfixed code
    - MQ ACTIVE_STANDBY: Create broker `ha-broker` (ACTIVE_STANDBY_MULTI_AZ), call `_find_alive_mq_brokers({"ha-broker-1", "ha-broker-2"})` → expect both alive but get `set()`
    - APIGW HTTP: Create v2 HTTP API `my-api` with id `abc123`, call `_find_alive_apigw_apis({"my-api/abc123"})` → expect `{"my-api/abc123"}` but get `set()`
    - ACM: Create ACM cert for `e2e-test.internal`, call `_find_alive_acm_certificates({"e2e-test.internal"})` → expect `{"e2e-test.internal"}` but get `set()`
    - EC2 control: Create EC2 instance, call `_find_alive_ec2_instances({instance_id})` → expect alive (should PASS, confirming EC2 is not affected)
  - Use moto mocks for AWS services
  - Run test on UNFIXED code
  - **EXPECTED OUTCOME**: MQ/APIGW/ACM assertions FAIL (proves the bug exists), EC2 control PASSES
  - Document counterexamples found to understand root cause
  - Mark task complete when test is written, run, and failure is documented
  - Test file: `tests/test_pbt_orphan_alarm_bug_condition.py`
  - _Requirements: 1.1, 1.2, 1.3_

- [x] 2. Write preservation property tests (BEFORE implementing fix)
  - **Property 2: Preservation** — Simple Collector Alive Resolution Equivalence
  - **IMPORTANT**: Follow observation-first methodology
  - Observe behavior on UNFIXED code for non-buggy resource types (EC2, RDS, ElastiCache, NAT, Lambda, VPN, Backup, CLB, OpenSearch)
  - Write property-based tests using Hypothesis that generate random resource IDs and verify:
    - EC2: `resolve_alive_ids` matches `_find_alive_ec2_instances` for random instance IDs (mix of alive/terminated/nonexistent)
    - RDS: `resolve_alive_ids` matches `_find_alive_rds_instances` for random DB identifiers
    - ELB: `resolve_alive_ids` matches `_find_alive_elb_resources` for random ARNs and short IDs
    - ElastiCache: `resolve_alive_ids` matches `_find_alive_elasticache_clusters`
    - NAT: `resolve_alive_ids` matches `_find_alive_nat_gateways`
    - Lambda: `resolve_alive_ids` matches `_find_alive_lambda_functions`
    - VPN: `resolve_alive_ids` matches `_find_alive_vpn_connections`
    - Backup: `resolve_alive_ids` matches `_find_alive_backup_vaults`
    - CLB: `resolve_alive_ids` matches `_find_alive_clb_load_balancers`
    - OpenSearch: `resolve_alive_ids` matches `_find_alive_opensearch_domains`
  - Property-based testing generates many test cases for stronger preservation guarantees
  - **NOTE**: These tests compare the NEW `resolve_alive_ids` against the OLD `_find_alive_*` functions, so both must exist when these tests first run. Write the `resolve_alive_ids` implementations (tasks 3–8) first, then run these tests BEFORE the refactor (task 9) removes the old functions.
  - Run tests on UNFIXED code (before refactor of `_cleanup_orphan_alarms`)
  - **EXPECTED OUTCOME**: Tests PASS (confirms baseline behavior is preserved)
  - Mark task complete when tests are written, run, and passing on unfixed code
  - Test file: `tests/test_pbt_orphan_alarm_preservation.py`
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10_

- [x] 3. Add `resolve_alive_ids` to `CollectorProtocol` in base.py
  - Add `resolve_alive_ids(tag_names: set[str]) -> set[str]` method signature to `CollectorProtocol` in `common/collectors/base.py`
  - This is the new interface method each collector must implement
  - _Requirements: 2.4_

- [x] 4. Implement `resolve_alive_ids` for MQ collector (custom — strip suffix)
  - File: `common/collectors/mq.py`
  - Strip `-1`/`-2` suffix from each TagName to get base broker name
  - Call `list_brokers` via existing `_get_mq_client()`
  - If base name found in broker list, add the original TagName (with suffix) to alive set
  - Handle both SINGLE_INSTANCE (`-1` only) and ACTIVE_STANDBY (`-1`, `-2`) suffixes
  - _Bug_Condition: isBugCondition(MQ, tag_name) where tag_name = "{broker_name}-{1|2}"_
  - _Expected_Behavior: strip suffix, match base name, return original TagName as alive_
  - _Requirements: 2.1_

- [x] 5. Implement `resolve_alive_ids` for APIGW collector (custom — split composite)
  - File: `common/collectors/apigw.py`
  - For each TagName containing `/`, split into `{api_name}/{api_id}` and check v2 APIs by `ApiId`
  - For non-composite TagNames (REST), check by name against REST APIs
  - Use existing `_get_apigw_client()` and `_get_apigwv2_client()`
  - _Bug_Condition: isBugCondition(APIGW, tag_name) where tag_name = "{api_name}/{api_id}"_
  - _Expected_Behavior: split composite, match by api_id for v2 or by name for REST, return original TagName_
  - _Requirements: 2.2_

- [x] 6. Implement `resolve_alive_ids` for ACM collector (custom — domain matching)
  - File: `common/collectors/acm.py`
  - Call `list_certificates(CertificateStatuses=["ISSUED"])` + `describe_certificate` to build set of domain names for non-expired certs
  - Return intersection of input TagNames with alive domain names
  - Use existing `_get_acm_client()`
  - _Bug_Condition: isBugCondition(ACM, tag_name) where tag_name is a domain name (not ARN)_
  - _Expected_Behavior: match domain names against ISSUED certs, return alive domains_
  - _Requirements: 2.3_

- [x] 7. Implement `resolve_alive_ids` for simple collectors
  - Add `resolve_alive_ids(tag_names: set[str]) -> set[str]` to each simple collector module
  - Logic is moved directly from the corresponding `_find_alive_*` function in `lambda_handler.py`
  - Each uses its existing boto3 client singleton
  - Files and logic:
    - `common/collectors/ec2.py`: `describe_instances` in batches of 200, exclude terminated/shutting-down, individual fallback on `InvalidInstanceID.NotFound`
    - `common/collectors/rds.py`: `describe_db_instances` per ID, `DBInstanceNotFound` → orphan
    - `common/collectors/docdb.py`: same RDS API as rds.py (`describe_db_instances` per ID)
    - `common/collectors/elb.py`: separate LB ARNs, TG ARNs, other IDs (treated as alive); `describe_load_balancers`/`describe_target_groups`
    - `common/collectors/elasticache.py`: `describe_cache_clusters` per ID, `CacheClusterNotFound` → orphan
    - `common/collectors/natgw.py`: `describe_nat_gateways` in batches of 200, exclude deleted/deleting
    - `common/collectors/lambda_fn.py`: `get_function` per name, `ResourceNotFoundException` → orphan
    - `common/collectors/vpn.py`: `describe_vpn_connections` with IDs, exclude deleted/deleting
    - `common/collectors/backup.py`: `describe_backup_vault` per name, `ResourceNotFoundException` → orphan
    - `common/collectors/clb.py`: `describe_load_balancers` per name, `LoadBalancerNotFound` → orphan (use `AccessPointNotFound` for classic ELB)
    - `common/collectors/opensearch.py`: `describe_domains` in batches of 5, exclude deleted
  - _Preservation: each resolve_alive_ids must produce identical results to the original _find_alive_* function_
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10_

- [x] 8. Unit tests for all new `resolve_alive_ids` implementations
  - Test file: `tests/test_resolve_alive_ids.py`
  - Use moto mocks for AWS services
  - Test MQ `resolve_alive_ids` with suffix stripping for SINGLE_INSTANCE and ACTIVE_STANDBY brokers
  - Test APIGW `resolve_alive_ids` with composite `name/id` format for HTTP/WS and plain name for REST
  - Test ACM `resolve_alive_ids` with domain names, including expired certs (should not be alive)
  - Test each simple collector's `resolve_alive_ids` with existing and non-existing resources
  - Test edge cases: empty input set, all alive, all dead, mixed
  - _Requirements: 2.1, 2.2, 2.3, 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9, 3.10_

- [x] 9. Refactor `_cleanup_orphan_alarms` to use collector-based resolution

  - [x] 9.1 Build `_RESOURCE_TYPE_TO_COLLECTOR` mapping and refactor `_cleanup_orphan_alarms`
    - File: `daily_monitor/lambda_handler.py`
    - Add static `_RESOURCE_TYPE_TO_COLLECTOR` dict mapping resource type strings to collector modules
    - Include all type aliases: `AuroraRDS` → `rds_collector`, `DocDB` → `docdb_collector`, `NATGateway` → `natgw_collector`, `ELB` → `elb_collector`
    - Replace `alive_checkers` dict with collector lookup: `collector.resolve_alive_ids(resource_ids)`
    - Keep warning log for unknown resource types with no registered collector
    - Keep batch deletion logic (100 alarms per batch)
    - _Bug_Condition: isBugCondition from design — MQ/APIGW/ACM TagName format mismatch_
    - _Expected_Behavior: collector-based resolve_alive_ids correctly handles all TagName formats_
    - _Preservation: identical orphan detection for all non-buggy resource types_
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 3.11, 3.12_

  - [x] 9.2 Remove duplicate boto3 singletons and `_find_alive_*` functions from lambda_handler
    - Delete `_get_mq_client`, `_get_acm_client`, `_get_apigw_client`, `_get_apigwv2_client`, `_get_lambda_client`, `_get_backup_client`, `_get_classic_elb_client`, `_get_opensearch_client`, `_get_elasticache_client` from `lambda_handler.py`
    - Keep `_get_cw_client`, `_get_ec2_client`, `_get_rds_client`, `_get_elb_client` only if still used by other functions in `lambda_handler.py`
    - Delete all `_find_alive_*` functions: `_find_alive_ec2_instances`, `_find_alive_rds_instances`, `_find_alive_elb_resources`, `_find_alive_elasticache_clusters`, `_find_alive_nat_gateways`, `_find_alive_lambda_functions`, `_find_alive_vpn_connections`, `_find_alive_apigw_apis`, `_find_alive_acm_certificates`, `_find_alive_backup_vaults`, `_find_alive_mq_brokers`, `_find_alive_clb_load_balancers`, `_find_alive_opensearch_domains`
    - Delete helper functions: `_check_ec2_individually`, `_check_elb_arns`, `_check_tg_arns`
    - _Requirements: 2.4, 1.4_

  - [x] 9.3 Verify bug condition exploration test now passes
    - **Property 1: Expected Behavior** — MQ/APIGW/ACM TagName Resolution
    - **IMPORTANT**: Re-run the SAME test from task 1 — do NOT write a new test
    - The test from task 1 encodes the expected behavior
    - When this test passes, it confirms the expected behavior is satisfied
    - Run bug condition exploration test from step 1
    - **EXPECTED OUTCOME**: Test PASSES (confirms bug is fixed)
    - _Requirements: 2.1, 2.2, 2.3_

  - [x] 9.4 Verify preservation tests still pass
    - **Property 2: Preservation** — Simple Collector Alive Resolution Equivalence
    - **IMPORTANT**: Re-run the SAME tests from task 2 — do NOT write new tests
    - Run preservation property tests from step 2
    - **EXPECTED OUTCOME**: Tests PASS (confirms no regressions)
    - Confirm all tests still pass after fix (no regressions)

- [x] 10. Checkpoint — Ensure all tests pass
  - Run full test suite: `pytest tests/ --run`
  - Ensure all tests pass, ask the user if questions arise
