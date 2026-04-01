"""
Unit tests for custom `resolve_alive_ids` implementations (MQ, APIGW, ACM).

The simple collectors are already covered by the preservation tests in
test_pbt_orphan_alarm_preservation.py. These tests focus on the 3 custom
implementations that handle TagName format mismatches (the bug condition).

**Validates: Requirements 2.1, 2.2, 2.3**
"""

import datetime

import boto3
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from moto import mock_aws

from common.collectors import acm as acm_collector
from common.collectors import apigw as apigw_collector
from common.collectors import mq as mq_collector


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _import_issued_cert(acm_client, domain: str, days_valid: int = 365) -> str:
    """Import a self-signed cert into ACM so it gets ISSUED status.

    Returns the certificate ARN.
    """
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
def _clear_all_lru_caches():
    """Clear all lru_cache singletons before each test so moto mocks take effect."""
    mq_collector._get_mq_client.cache_clear()
    apigw_collector._get_apigw_client.cache_clear()
    apigw_collector._get_apigwv2_client.cache_clear()
    acm_collector._get_acm_client.cache_clear()
    yield
    mq_collector._get_mq_client.cache_clear()
    apigw_collector._get_apigw_client.cache_clear()
    apigw_collector._get_apigwv2_client.cache_clear()
    acm_collector._get_acm_client.cache_clear()


@pytest.fixture(autouse=True)
def _set_aws_env(monkeypatch):
    """Set dummy AWS credentials for moto."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


# ──────────────────────────────────────────────
# MQ resolve_alive_ids tests
# ──────────────────────────────────────────────


class TestMQResolveAliveIds:
    """MQ resolve_alive_ids: strip -1/-2 suffix, match base broker name."""

    @mock_aws
    def test_single_instance_broker_alive(self):
        """SINGLE_INSTANCE broker: TagName 'my-broker-1' → alive when broker 'my-broker' exists.

        **Validates: Requirements 2.1**
        """
        client = boto3.client("mq", region_name="us-east-1")
        client.create_broker(
            BrokerName="my-broker",
            EngineType="ACTIVEMQ",
            EngineVersion="5.17.6",
            HostInstanceType="mq.t3.micro",
            DeploymentMode="SINGLE_INSTANCE",
            PubliclyAccessible=False,
            Users=[{"Username": "admin", "Password": "admin12345678"}],
        )

        result = mq_collector.resolve_alive_ids({"my-broker-1"})
        assert result == {"my-broker-1"}

    @mock_aws
    def test_active_standby_broker_alive(self):
        """ACTIVE_STANDBY broker: both '-1' and '-2' suffixed TagNames alive.

        **Validates: Requirements 2.1**
        """
        client = boto3.client("mq", region_name="us-east-1")
        client.create_broker(
            BrokerName="ha-broker",
            EngineType="ACTIVEMQ",
            EngineVersion="5.17.6",
            HostInstanceType="mq.m5.large",
            DeploymentMode="ACTIVE_STANDBY_MULTI_AZ",
            PubliclyAccessible=False,
            Users=[{"Username": "admin", "Password": "admin12345678"}],
        )

        result = mq_collector.resolve_alive_ids({"ha-broker-1", "ha-broker-2"})
        assert result == {"ha-broker-1", "ha-broker-2"}

    @mock_aws
    def test_dead_broker(self):
        """Dead broker: TagName for non-existent broker → empty set.

        **Validates: Requirements 2.1**
        """
        result = mq_collector.resolve_alive_ids({"dead-broker-1"})
        assert result == set()

    @mock_aws
    def test_mixed_alive_and_dead(self):
        """Mixed: alive broker TagNames + dead broker TagNames.

        **Validates: Requirements 2.1**
        """
        client = boto3.client("mq", region_name="us-east-1")
        client.create_broker(
            BrokerName="alive-broker",
            EngineType="ACTIVEMQ",
            EngineVersion="5.17.6",
            HostInstanceType="mq.t3.micro",
            DeploymentMode="SINGLE_INSTANCE",
            PubliclyAccessible=False,
            Users=[{"Username": "admin", "Password": "admin12345678"}],
        )

        result = mq_collector.resolve_alive_ids(
            {"alive-broker-1", "dead-broker-1", "dead-broker-2"}
        )
        assert result == {"alive-broker-1"}

    @mock_aws
    def test_no_suffix_plain_broker_name(self):
        """No suffix: TagName 'plain-broker' → alive if broker 'plain-broker' exists.

        **Validates: Requirements 2.1**
        """
        client = boto3.client("mq", region_name="us-east-1")
        client.create_broker(
            BrokerName="plain-broker",
            EngineType="ACTIVEMQ",
            EngineVersion="5.17.6",
            HostInstanceType="mq.t3.micro",
            DeploymentMode="SINGLE_INSTANCE",
            PubliclyAccessible=False,
            Users=[{"Username": "admin", "Password": "admin12345678"}],
        )

        result = mq_collector.resolve_alive_ids({"plain-broker"})
        assert result == {"plain-broker"}

    @mock_aws
    def test_empty_input(self):
        """Empty input → empty set.

        **Validates: Requirements 2.1**
        """
        result = mq_collector.resolve_alive_ids(set())
        assert result == set()


# ──────────────────────────────────────────────
# APIGW resolve_alive_ids tests
# ──────────────────────────────────────────────


class TestAPIGWResolveAliveIds:
    """APIGW resolve_alive_ids: composite name/id for HTTP, plain name for REST."""

    @mock_aws
    def test_rest_api_alive(self):
        """REST API: TagName 'my-rest-api' → alive when REST API with that name exists.

        **Validates: Requirements 2.2**
        """
        client = boto3.client("apigateway", region_name="us-east-1")
        client.create_rest_api(name="my-rest-api", description="test")

        result = apigw_collector.resolve_alive_ids({"my-rest-api"})
        assert result == {"my-rest-api"}

    @mock_aws
    def test_http_api_composite_alive(self):
        """HTTP API composite: TagName 'my-api/{api_id}' → alive when v2 API exists.

        **Validates: Requirements 2.2**
        """
        v2 = boto3.client("apigatewayv2", region_name="us-east-1")
        resp = v2.create_api(Name="my-api", ProtocolType="HTTP")
        api_id = resp["ApiId"]

        tag_name = f"my-api/{api_id}"
        result = apigw_collector.resolve_alive_ids({tag_name})
        assert result == {tag_name}

    @mock_aws
    def test_dead_rest_api(self):
        """Dead REST: TagName for non-existent REST API → empty set.

        **Validates: Requirements 2.2**
        """
        result = apigw_collector.resolve_alive_ids({"ghost-api"})
        assert result == set()

    @mock_aws
    def test_dead_http_composite(self):
        """Dead HTTP composite: TagName 'ghost/deadid' → empty set when no v2 API.

        **Validates: Requirements 2.2**
        """
        result = apigw_collector.resolve_alive_ids({"ghost/deadid"})
        assert result == set()

    @mock_aws
    def test_mixed_rest_and_http(self):
        """Mixed REST + HTTP: both alive and dead.

        **Validates: Requirements 2.2**
        """
        rest_client = boto3.client("apigateway", region_name="us-east-1")
        rest_client.create_rest_api(name="alive-rest", description="test")

        v2 = boto3.client("apigatewayv2", region_name="us-east-1")
        resp = v2.create_api(Name="alive-http", ProtocolType="HTTP")
        api_id = resp["ApiId"]

        tag_names = {
            "alive-rest",
            f"alive-http/{api_id}",
            "dead-rest",
            "dead-http/nonexistent",
        }
        result = apigw_collector.resolve_alive_ids(tag_names)
        assert result == {"alive-rest", f"alive-http/{api_id}"}

    @mock_aws
    def test_empty_input(self):
        """Empty input → empty set.

        **Validates: Requirements 2.2**
        """
        result = apigw_collector.resolve_alive_ids(set())
        assert result == set()


# ──────────────────────────────────────────────
# ACM resolve_alive_ids tests
# ──────────────────────────────────────────────


class TestACMResolveAliveIds:
    """ACM resolve_alive_ids: match domain names against ISSUED certs."""

    @mock_aws
    def test_alive_cert(self):
        """Alive cert: TagName 'e2e-test.internal' → alive when ISSUED cert exists.

        Uses import_certificate to create an ISSUED cert (request_certificate
        creates PENDING_VALIDATION which resolve_alive_ids correctly skips).

        **Validates: Requirements 2.3**
        """
        client = boto3.client("acm", region_name="us-east-1")
        _import_issued_cert(client, "e2e-test.internal")

        result = acm_collector.resolve_alive_ids({"e2e-test.internal"})
        assert result == {"e2e-test.internal"}

    @mock_aws
    def test_dead_domain(self):
        """Dead domain: TagName for non-existent cert → empty set.

        **Validates: Requirements 2.3**
        """
        result = acm_collector.resolve_alive_ids({"ghost.example.com"})
        assert result == set()

    @mock_aws
    def test_mixed_alive_and_dead(self):
        """Mixed alive + dead domains.

        **Validates: Requirements 2.3**
        """
        client = boto3.client("acm", region_name="us-east-1")
        _import_issued_cert(client, "alive.example.com")

        result = acm_collector.resolve_alive_ids(
            {"alive.example.com", "ghost.example.com"}
        )
        assert result == {"alive.example.com"}

    @mock_aws
    def test_empty_input(self):
        """Empty input → empty set.

        **Validates: Requirements 2.3**
        """
        result = acm_collector.resolve_alive_ids(set())
        assert result == set()
