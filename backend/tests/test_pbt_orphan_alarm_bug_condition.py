"""
Bug Condition Exploration Test — MQ/APIGW/ACM TagName Mismatch

Property 1: Bug Condition — MQ/APIGW/ACM TagName Mismatch
Validates: Requirements 1.1, 1.2, 1.3

These tests verify that the collector-based `resolve_alive_ids` correctly handles
TagName formats that the old `_find_alive_*` functions could not match:
- MQ: TagName with `-1`/`-2` suffix → strip suffix, match base broker name
- APIGW: Composite `name/id` TagName → split and match by ApiId
- ACM: Domain name TagName → match against ISSUED certificate domains
- EC2 control: TagName = InstanceId → direct match (not affected by bug)
"""

import datetime
import os

import boto3
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from moto import mock_aws

from common.collectors import mq as mq_collector
from common.collectors import apigw as apigw_collector
from common.collectors import acm as acm_collector
from common.collectors import ec2 as ec2_collector


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _import_issued_cert(acm_client, domain: str, days_valid: int = 365) -> str:
    """Import a self-signed cert into ACM so it gets ISSUED status."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.datetime.now(datetime.timezone.utc)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, domain),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=days_valid))
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    resp = acm_client.import_certificate(
        Certificate=cert_pem, PrivateKey=key_pem,
    )
    return resp["CertificateArn"]


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_lru_caches():
    """Clear all lru_cache singletons before each test so moto mocks take effect."""
    mq_collector._get_mq_client.cache_clear()
    acm_collector._get_acm_client.cache_clear()
    apigw_collector._get_apigw_client.cache_clear()
    apigw_collector._get_apigwv2_client.cache_clear()
    ec2_collector._get_ec2_client.cache_clear()
    yield
    mq_collector._get_mq_client.cache_clear()
    acm_collector._get_acm_client.cache_clear()
    apigw_collector._get_apigw_client.cache_clear()
    apigw_collector._get_apigwv2_client.cache_clear()
    ec2_collector._get_ec2_client.cache_clear()


@pytest.fixture(autouse=True)
def _set_aws_env(monkeypatch):
    """Set dummy AWS credentials for moto."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


# ──────────────────────────────────────────────
# Bug Condition Tests (NOW EXPECTED TO PASS with fix)
# ──────────────────────────────────────────────


@mock_aws
def test_mq_single_instance_tagname_mismatch():
    """MQ SINGLE_INSTANCE: TagName 'my-broker-1' should be recognized as alive
    when broker 'my-broker' exists.

    Fixed: resolve_alive_ids strips '-1' suffix and matches base broker name.

    **Validates: Requirements 1.1**
    """
    client = boto3.client("mq", region_name="us-east-1")
    client.create_broker(
        BrokerName="my-broker",
        DeploymentMode="SINGLE_INSTANCE",
        EngineType="ACTIVEMQ",
        EngineVersion="5.17.6",
        HostInstanceType="mq.t3.micro",
        PubliclyAccessible=False,
        AutoMinorVersionUpgrade=True,
        Users=[{"Username": "admin", "Password": "Admin12345678!"}],
    )

    # TagName format from _broker_instance_ids: "my-broker-1"
    alive = mq_collector.resolve_alive_ids({"my-broker-1"})
    assert alive == {"my-broker-1"}, (
        f"Expected {{'my-broker-1'}} but got {alive}. "
        "resolve_alive_ids should strip '-1' suffix and match base broker name"
    )


@mock_aws
def test_mq_active_standby_tagname_mismatch():
    """MQ ACTIVE_STANDBY: TagNames 'ha-broker-1' and 'ha-broker-2' should be
    recognized as alive when broker 'ha-broker' exists.

    Fixed: resolve_alive_ids strips suffix and matches base broker name.

    **Validates: Requirements 1.1**
    """
    client = boto3.client("mq", region_name="us-east-1")
    client.create_broker(
        BrokerName="ha-broker",
        DeploymentMode="ACTIVE_STANDBY_MULTI_AZ",
        EngineType="ACTIVEMQ",
        EngineVersion="5.17.6",
        HostInstanceType="mq.t3.micro",
        PubliclyAccessible=False,
        AutoMinorVersionUpgrade=True,
        Users=[{"Username": "admin", "Password": "Admin12345678!"}],
    )

    alive = mq_collector.resolve_alive_ids({"ha-broker-1", "ha-broker-2"})
    assert alive == {"ha-broker-1", "ha-broker-2"}, (
        f"Expected {{'ha-broker-1', 'ha-broker-2'}} but got {alive}. "
        "resolve_alive_ids should strip suffix and match base broker name"
    )


@mock_aws
def test_apigw_http_composite_tagname_mismatch():
    """APIGW HTTP: TagName 'my-api/{api_id}' should be recognized as alive
    when the v2 HTTP API exists.

    Fixed: resolve_alive_ids splits composite TagName and matches by ApiId.

    **Validates: Requirements 1.2**
    """
    v2_client = boto3.client("apigatewayv2", region_name="us-east-1")
    resp = v2_client.create_api(
        Name="my-api",
        ProtocolType="HTTP",
    )
    api_id = resp["ApiId"]

    # TagName format from _shorten_elb_resource_id: "my-api/{api_id}"
    composite_tag = f"my-api/{api_id}"
    alive = apigw_collector.resolve_alive_ids({composite_tag})
    assert alive == {composite_tag}, (
        f"Expected {{'{composite_tag}'}} but got {alive}. "
        "resolve_alive_ids should split composite and match by ApiId"
    )


@mock_aws
def test_acm_domain_tagname_mismatch():
    """ACM: TagName 'e2e-test.internal' (domain name) should be recognized as alive
    when a matching ISSUED certificate exists.

    Fixed: resolve_alive_ids matches domain names against ISSUED certificate domains.

    **Validates: Requirements 1.3**
    """
    client = boto3.client("acm", region_name="us-east-1")
    _import_issued_cert(client, "e2e-test.internal")

    # TagName format from _shorten_elb_resource_id: domain name from Name tag
    alive = acm_collector.resolve_alive_ids({"e2e-test.internal"})
    assert alive == {"e2e-test.internal"}, (
        f"Expected {{'e2e-test.internal'}} but got {alive}. "
        "resolve_alive_ids should match domain names against ISSUED certs"
    )


# ──────────────────────────────────────────────
# Control Test (SHOULD PASS — EC2 is not affected)
# ──────────────────────────────────────────────


@mock_aws
def test_ec2_control_alive_check_works():
    """EC2 control: resolve_alive_ids correctly identifies alive instances.

    This test confirms EC2 is NOT affected by the bug — TagName matches
    InstanceId directly.

    **Validates: Requirements 1.1 (control)**
    """
    ec2 = boto3.client("ec2", region_name="us-east-1")
    resp = ec2.run_instances(
        ImageId="ami-12345678",
        MinCount=1,
        MaxCount=1,
        InstanceType="t2.micro",
    )
    instance_id = resp["Instances"][0]["InstanceId"]

    alive = ec2_collector.resolve_alive_ids({instance_id})
    assert alive == {instance_id}, (
        f"Expected {{'{instance_id}'}} but got {alive}. "
        "EC2 should NOT be affected by the bug"
    )
