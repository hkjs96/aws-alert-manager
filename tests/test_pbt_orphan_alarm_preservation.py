"""
Preservation Property Tests — Simple Collector Alive Resolution

Property 4: Preservation — Simple Collector Alive Resolution
**Validates: Requirements 3.1, 3.2, 3.4, 3.5, 3.7, 3.9**

These tests verify that each collector's `resolve_alive_ids` correctly identifies
alive resources and excludes dead/non-existent ones using moto mocks.

After the refactor (task 9.2), the old `_find_alive_*` functions no longer exist.
These tests now validate the collector implementations directly:
- Alive resources are found
- Dead/non-existent resources are excluded
- Empty input returns empty set
"""

import io
import zipfile

import boto3
import pytest
from moto import mock_aws

from common.collectors import ec2 as ec2_collector
from common.collectors import rds as rds_collector
from common.collectors import clb as clb_collector
from common.collectors import elasticache as elasticache_collector
from common.collectors import lambda_fn as lambda_fn_collector
from common.collectors import backup as backup_collector


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_all_lru_caches():
    """Clear all lru_cache singletons before each test so moto mocks take effect."""
    ec2_collector._get_ec2_client.cache_clear()
    rds_collector._get_rds_client.cache_clear()
    clb_collector._get_elb_client.cache_clear()
    elasticache_collector._get_elasticache_client.cache_clear()
    lambda_fn_collector._get_lambda_client.cache_clear()
    backup_collector._get_backup_client.cache_clear()
    yield
    ec2_collector._get_ec2_client.cache_clear()
    rds_collector._get_rds_client.cache_clear()
    clb_collector._get_elb_client.cache_clear()
    elasticache_collector._get_elasticache_client.cache_clear()
    lambda_fn_collector._get_lambda_client.cache_clear()
    backup_collector._get_backup_client.cache_clear()


@pytest.fixture(autouse=True)
def _set_aws_env(monkeypatch):
    """Set dummy AWS credentials for moto."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


# ──────────────────────────────────────────────
# EC2 Preservation
# ──────────────────────────────────────────────


@mock_aws
def test_ec2_preservation_mixed_alive_and_nonexistent():
    """EC2: resolve_alive_ids finds alive instances and excludes non-existent IDs.

    **Validates: Requirements 3.1**
    """
    ec2 = boto3.client("ec2", region_name="us-east-1")
    resp = ec2.run_instances(ImageId="ami-12345678", MinCount=2, MaxCount=2,
                             InstanceType="t2.micro")
    alive_ids = {inst["InstanceId"] for inst in resp["Instances"]}
    nonexistent_ids = {"i-0000000000000dead", "i-0000000000000beef"}
    all_ids = alive_ids | nonexistent_ids

    result = ec2_collector.resolve_alive_ids(all_ids)

    assert alive_ids <= result
    assert nonexistent_ids.isdisjoint(result)


@mock_aws
def test_ec2_preservation_empty_input():
    """EC2: Empty input returns empty set.

    **Validates: Requirements 3.1**
    """
    result = ec2_collector.resolve_alive_ids(set())
    assert result == set()


@mock_aws
def test_ec2_preservation_terminated_instances():
    """EC2: Terminated instances are excluded.

    **Validates: Requirements 3.1**
    """
    ec2 = boto3.client("ec2", region_name="us-east-1")
    resp = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1,
                             InstanceType="t2.micro")
    instance_id = resp["Instances"][0]["InstanceId"]
    ec2.terminate_instances(InstanceIds=[instance_id])

    result = ec2_collector.resolve_alive_ids({instance_id})
    # terminated instances should be excluded
    assert instance_id not in result


# ──────────────────────────────────────────────
# RDS Preservation
# ──────────────────────────────────────────────


@mock_aws
def test_rds_preservation_mixed_alive_and_nonexistent():
    """RDS: resolve_alive_ids finds alive DB instances and excludes non-existent.

    **Validates: Requirements 3.2**
    """
    rds = boto3.client("rds", region_name="us-east-1")
    rds.create_db_instance(
        DBInstanceIdentifier="my-db-1",
        DBInstanceClass="db.t3.micro",
        Engine="mysql",
        MasterUsername="admin",
        MasterUserPassword="password123",
    )
    rds.create_db_instance(
        DBInstanceIdentifier="my-db-2",
        DBInstanceClass="db.t3.micro",
        Engine="mysql",
        MasterUsername="admin",
        MasterUserPassword="password123",
    )

    alive_ids = {"my-db-1", "my-db-2"}
    nonexistent_ids = {"ghost-db-1", "ghost-db-2"}
    all_ids = alive_ids | nonexistent_ids

    result = rds_collector.resolve_alive_ids(all_ids)

    assert alive_ids <= result
    assert nonexistent_ids.isdisjoint(result)


@mock_aws
def test_rds_preservation_empty_input():
    """RDS: Empty input returns empty set.

    **Validates: Requirements 3.2**
    """
    result = rds_collector.resolve_alive_ids(set())
    assert result == set()


# ──────────────────────────────────────────────
# CLB Preservation
# ──────────────────────────────────────────────


@mock_aws
def test_clb_preservation_mixed_alive_and_nonexistent():
    """CLB: resolve_alive_ids finds alive CLBs and excludes non-existent names.

    **Validates: Requirements 3.4**
    """
    elb = boto3.client("elb", region_name="us-east-1")
    elb.create_load_balancer(
        LoadBalancerName="my-clb-1",
        Listeners=[{
            "Protocol": "HTTP",
            "LoadBalancerPort": 80,
            "InstanceProtocol": "HTTP",
            "InstancePort": 80,
        }],
        AvailabilityZones=["us-east-1a"],
    )
    elb.create_load_balancer(
        LoadBalancerName="my-clb-2",
        Listeners=[{
            "Protocol": "HTTP",
            "LoadBalancerPort": 80,
            "InstanceProtocol": "HTTP",
            "InstancePort": 80,
        }],
        AvailabilityZones=["us-east-1a"],
    )

    alive_ids = {"my-clb-1", "my-clb-2"}
    nonexistent_ids = {"ghost-clb-1"}
    all_ids = alive_ids | nonexistent_ids

    result = clb_collector.resolve_alive_ids(all_ids)

    assert alive_ids <= result
    assert nonexistent_ids.isdisjoint(result)


@mock_aws
def test_clb_preservation_empty_input():
    """CLB: Empty input returns empty set.

    **Validates: Requirements 3.4**
    """
    result = clb_collector.resolve_alive_ids(set())
    assert result == set()


# ──────────────────────────────────────────────
# ElastiCache Preservation
# ──────────────────────────────────────────────


@mock_aws
def test_elasticache_preservation_mixed_alive_and_nonexistent():
    """ElastiCache: resolve_alive_ids finds alive clusters and excludes non-existent.

    **Validates: Requirements 3.5**
    """
    client = boto3.client("elasticache", region_name="us-east-1")
    client.create_cache_cluster(
        CacheClusterId="my-cache-1",
        Engine="redis",
        CacheNodeType="cache.t3.micro",
        NumCacheNodes=1,
    )

    alive_ids = {"my-cache-1"}
    nonexistent_ids = {"ghost-cache-1", "ghost-cache-2"}
    all_ids = alive_ids | nonexistent_ids

    result = elasticache_collector.resolve_alive_ids(all_ids)

    assert alive_ids <= result
    assert nonexistent_ids.isdisjoint(result)


@mock_aws
def test_elasticache_preservation_empty_input():
    """ElastiCache: Empty input returns empty set.

    **Validates: Requirements 3.5**
    """
    result = elasticache_collector.resolve_alive_ids(set())
    assert result == set()


# ──────────────────────────────────────────────
# Lambda Preservation
# ──────────────────────────────────────────────


@mock_aws
def test_lambda_preservation_mixed_alive_and_nonexistent():
    """Lambda: resolve_alive_ids finds alive functions and excludes non-existent.

    **Validates: Requirements 3.7**
    """
    # Create a minimal Lambda deployment package
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("lambda_function.py", "def handler(event, context): pass")
    zip_content = zip_buffer.getvalue()

    # Create IAM role for Lambda (moto requires it)
    iam = boto3.client("iam", region_name="us-east-1")
    iam.create_role(
        RoleName="lambda-role",
        AssumeRolePolicyDocument="{}",
        Path="/",
    )
    role_arn = iam.get_role(RoleName="lambda-role")["Role"]["Arn"]

    lam = boto3.client("lambda", region_name="us-east-1")
    lam.create_function(
        FunctionName="my-func-1",
        Runtime="python3.12",
        Role=role_arn,
        Handler="lambda_function.handler",
        Code={"ZipFile": zip_content},
    )
    lam.create_function(
        FunctionName="my-func-2",
        Runtime="python3.12",
        Role=role_arn,
        Handler="lambda_function.handler",
        Code={"ZipFile": zip_content},
    )

    alive_ids = {"my-func-1", "my-func-2"}
    nonexistent_ids = {"ghost-func-1"}
    all_ids = alive_ids | nonexistent_ids

    result = lambda_fn_collector.resolve_alive_ids(all_ids)

    assert alive_ids <= result
    assert nonexistent_ids.isdisjoint(result)


@mock_aws
def test_lambda_preservation_empty_input():
    """Lambda: Empty input returns empty set.

    **Validates: Requirements 3.7**
    """
    result = lambda_fn_collector.resolve_alive_ids(set())
    assert result == set()


# ──────────────────────────────────────────────
# Backup Preservation
# ──────────────────────────────────────────────


@mock_aws
def test_backup_preservation_mixed_alive_and_nonexistent():
    """Backup: resolve_alive_ids finds alive vaults and excludes non-existent.

    **Validates: Requirements 3.9**
    """
    client = boto3.client("backup", region_name="us-east-1")
    client.create_backup_vault(BackupVaultName="my-vault-1")
    client.create_backup_vault(BackupVaultName="my-vault-2")

    alive_ids = {"my-vault-1", "my-vault-2"}
    nonexistent_ids = {"ghost-vault-1"}
    all_ids = alive_ids | nonexistent_ids

    result = backup_collector.resolve_alive_ids(all_ids)

    assert alive_ids <= result
    assert nonexistent_ids.isdisjoint(result)


@mock_aws
def test_backup_preservation_empty_input():
    """Backup: Empty input returns empty set.

    **Validates: Requirements 3.9**
    """
    result = backup_collector.resolve_alive_ids(set())
    assert result == set()


# ──────────────────────────────────────────────
# All-alive and all-dead edge cases
# ──────────────────────────────────────────────


@mock_aws
def test_ec2_preservation_all_nonexistent():
    """EC2: All non-existent IDs returns empty set.

    **Validates: Requirements 3.1**
    """
    nonexistent = {"i-0000000000000aaaa", "i-0000000000000bbbb"}
    result = ec2_collector.resolve_alive_ids(nonexistent)
    assert result == set()


@mock_aws
def test_rds_preservation_all_nonexistent():
    """RDS: All non-existent IDs returns empty set.

    **Validates: Requirements 3.2**
    """
    nonexistent = {"ghost-db-a", "ghost-db-b"}
    result = rds_collector.resolve_alive_ids(nonexistent)
    assert result == set()


@mock_aws
def test_elasticache_preservation_all_nonexistent():
    """ElastiCache: All non-existent IDs returns empty set.

    **Validates: Requirements 3.5**
    """
    nonexistent = {"ghost-cache-a", "ghost-cache-b"}
    result = elasticache_collector.resolve_alive_ids(nonexistent)
    assert result == set()
