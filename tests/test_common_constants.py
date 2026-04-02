"""
공통 상수 검증 테스트

SUPPORTED_RESOURCE_TYPES, HARDCODED_DEFAULTS, MONITORED_API_EVENTS 상수에
신규 리소스 타입이 올바르게 포함되어 있는지 검증.
"""

import pytest

from common import HARDCODED_DEFAULTS


@pytest.fixture(autouse=True)
def _reset_cw_client():
    """각 테스트마다 캐시된 CloudWatch 클라이언트 초기화."""
    from common._clients import _get_cw_client
    _get_cw_client.cache_clear()
    yield
    _get_cw_client.cache_clear()


@pytest.fixture(autouse=True)
def _env_vars(monkeypatch):
    """테스트용 환경변수 설정."""
    monkeypatch.setenv("ENVIRONMENT", "prod")
    monkeypatch.setenv("SNS_TOPIC_ARN_ALERT", "arn:aws:sns:us-east-1:123:alert-topic")


class TestCommonConstantsNewResourceTypes:
    """common/__init__.py 상수에 8개 신규 리소스 타입 포함 검증.
    Validates: Requirements 1.6, 1.7, 2.7, 2.8, 3-A.1, 3-F.23,
               4.7, 4.8, 5.6, 5.7, 6.6, 6.7, 7.6, 7.7, 8.7, 8.8, 10.1
    """

    NEW_TYPES = [
        "Lambda", "VPN", "APIGW", "ACM",
        "Backup", "MQ", "CLB", "OpenSearch",
    ]

    def test_supported_resource_types_includes_all_new_types(self):
        from common import SUPPORTED_RESOURCE_TYPES
        for rt in self.NEW_TYPES:
            assert rt in SUPPORTED_RESOURCE_TYPES, f"{rt} not in SUPPORTED_RESOURCE_TYPES"

    def test_hardcoded_defaults_lambda(self):
        assert HARDCODED_DEFAULTS["Duration"] == 2500.0
        assert HARDCODED_DEFAULTS["Errors"] == 0.0

    def test_hardcoded_defaults_vpn(self):
        assert HARDCODED_DEFAULTS["TunnelState"] == 1.0

    def test_hardcoded_defaults_apigw_rest(self):
        assert HARDCODED_DEFAULTS["ApiLatency"] == 3000.0
        assert HARDCODED_DEFAULTS["Api4XXError"] == 1.0
        assert HARDCODED_DEFAULTS["Api5XXError"] == 1.0

    def test_hardcoded_defaults_apigw_http(self):
        assert HARDCODED_DEFAULTS["Api4xx"] == 1.0
        assert HARDCODED_DEFAULTS["Api5xx"] == 1.0

    def test_hardcoded_defaults_apigw_websocket(self):
        assert HARDCODED_DEFAULTS["WsConnectCount"] == 1000.0
        assert HARDCODED_DEFAULTS["WsMessageCount"] == 10000.0
        assert HARDCODED_DEFAULTS["WsIntegrationError"] == 0.0
        assert HARDCODED_DEFAULTS["WsExecutionError"] == 0.0

    def test_hardcoded_defaults_acm(self):
        assert HARDCODED_DEFAULTS["DaysToExpiry"] == 14.0

    def test_hardcoded_defaults_backup(self):
        assert HARDCODED_DEFAULTS["BackupJobsFailed"] == 0.0
        assert HARDCODED_DEFAULTS["BackupJobsAborted"] == 0.0

    def test_hardcoded_defaults_mq(self):
        assert HARDCODED_DEFAULTS["MqCPU"] == 90.0
        assert HARDCODED_DEFAULTS["HeapUsage"] == 80.0
        assert HARDCODED_DEFAULTS["JobSchedulerStoreUsage"] == 80.0
        assert HARDCODED_DEFAULTS["StoreUsage"] == 80.0

    def test_hardcoded_defaults_clb(self):
        assert HARDCODED_DEFAULTS["CLBUnHealthyHost"] == 0.0
        assert HARDCODED_DEFAULTS["CLB5XX"] == 300.0
        assert HARDCODED_DEFAULTS["CLB4XX"] == 300.0
        assert HARDCODED_DEFAULTS["CLBBackend5XX"] == 300.0
        assert HARDCODED_DEFAULTS["CLBBackend4XX"] == 300.0
        assert HARDCODED_DEFAULTS["SurgeQueueLength"] == 300.0
        assert HARDCODED_DEFAULTS["SpilloverCount"] == 300.0

    def test_hardcoded_defaults_opensearch(self):
        assert HARDCODED_DEFAULTS["ClusterStatusRed"] == 0.0
        assert HARDCODED_DEFAULTS["ClusterStatusYellow"] == 0.0
        assert HARDCODED_DEFAULTS["OSFreeStorageSpace"] == 20480.0
        assert HARDCODED_DEFAULTS["ClusterIndexWritesBlocked"] == 0.0
        assert HARDCODED_DEFAULTS["OsCPU"] == 80.0
        assert HARDCODED_DEFAULTS["JVMMemoryPressure"] == 80.0
        assert HARDCODED_DEFAULTS["MasterCPU"] == 50.0
        assert HARDCODED_DEFAULTS["MasterJVMMemoryPressure"] == 80.0

    def test_monitored_api_events_create_new_entries(self):
        from common import MONITORED_API_EVENTS
        expected_create = [
            "CreateFunction20150331",
            "CreateRestApi",
            "CreateApi",
            "CreateBackupVault",
            "CreateBroker",
            "CreateDomain",
        ]
        for event in expected_create:
            assert event in MONITORED_API_EVENTS["CREATE"], f"{event} not in CREATE"

    def test_monitored_api_events_delete_new_entries(self):
        from common import MONITORED_API_EVENTS
        expected_delete = [
            "DeleteFunction20150331",
            "DeleteVpnConnection",
            "DeleteRestApi",
            "DeleteApi",
            "DeleteCertificate",
            "DeleteBackupVault",
            "DeleteBroker",
            "DeleteDomain",
        ]
        for event in expected_delete:
            assert event in MONITORED_API_EVENTS["DELETE"], f"{event} not in DELETE"

    def test_monitored_api_events_tag_change_new_entries(self):
        from common import MONITORED_API_EVENTS
        assert "TagResource" in MONITORED_API_EVENTS["TAG_CHANGE"]
        assert "UntagResource" in MONITORED_API_EVENTS["TAG_CHANGE"]


class TestExtendedCommonConstants:
    """common/__init__.py 상수에 12개 Extended 리소스 타입 포함 검증.
    Validates: Requirements 1.6, 1.7, 2-A.1, 2-D.13, 3.7, 3.8, 4.6, 4.7,
               5.7, 5.8, 6.7, 6.8, 7.8, 7.9, 8.7, 8.8, 9.7, 9.8,
               10-D.10, 10-D.11, 11-C.9, 11-C.10, 12.6, 12.7, 14.1
    """

    EXTENDED_TYPES = [
        "SQS", "ECS", "MSK", "DynamoDB", "CloudFront", "WAF",
        "Route53", "DX", "EFS", "S3", "SageMaker", "SNS",
    ]

    def test_supported_resource_types_includes_all_extended_types(self):
        from common import SUPPORTED_RESOURCE_TYPES
        for rt in self.EXTENDED_TYPES:
            assert rt in SUPPORTED_RESOURCE_TYPES, f"{rt} not in SUPPORTED_RESOURCE_TYPES"

    def test_hardcoded_defaults_sqs(self):
        assert HARDCODED_DEFAULTS["SQSMessagesVisible"] == 1000.0
        assert HARDCODED_DEFAULTS["SQSOldestMessage"] == 300.0
        assert HARDCODED_DEFAULTS["SQSMessagesSent"] == 10000.0

    def test_hardcoded_defaults_ecs(self):
        assert HARDCODED_DEFAULTS["EcsCPU"] == 80.0
        assert HARDCODED_DEFAULTS["EcsMemory"] == 80.0
        assert HARDCODED_DEFAULTS["RunningTaskCount"] == 1.0

    def test_hardcoded_defaults_msk(self):
        assert HARDCODED_DEFAULTS["OffsetLag"] == 1000.0
        assert HARDCODED_DEFAULTS["BytesInPerSec"] == 100000000.0
        assert HARDCODED_DEFAULTS["UnderReplicatedPartitions"] == 0.0
        assert HARDCODED_DEFAULTS["ActiveControllerCount"] == 1.0

    def test_hardcoded_defaults_dynamodb(self):
        assert HARDCODED_DEFAULTS["DDBReadCapacity"] == 80.0
        assert HARDCODED_DEFAULTS["DDBWriteCapacity"] == 80.0
        assert HARDCODED_DEFAULTS["ThrottledRequests"] == 0.0
        assert HARDCODED_DEFAULTS["DDBSystemErrors"] == 0.0

    def test_hardcoded_defaults_cloudfront(self):
        assert HARDCODED_DEFAULTS["CF5xxErrorRate"] == 1.0
        assert HARDCODED_DEFAULTS["CF4xxErrorRate"] == 5.0
        assert HARDCODED_DEFAULTS["CFRequests"] == 1000000.0
        assert HARDCODED_DEFAULTS["CFBytesDownloaded"] == 10000000000.0

    def test_hardcoded_defaults_waf(self):
        assert HARDCODED_DEFAULTS["WAFBlockedRequests"] == 100.0
        assert HARDCODED_DEFAULTS["WAFAllowedRequests"] == 1000000.0
        assert HARDCODED_DEFAULTS["WAFCountedRequests"] == 100000.0

    def test_hardcoded_defaults_route53(self):
        assert HARDCODED_DEFAULTS["HealthCheckStatus"] == 1.0

    def test_hardcoded_defaults_dx(self):
        assert HARDCODED_DEFAULTS["ConnectionState"] == 1.0

    def test_hardcoded_defaults_efs(self):
        assert HARDCODED_DEFAULTS["BurstCreditBalance"] == 1000000000.0
        assert HARDCODED_DEFAULTS["PercentIOLimit"] == 90.0
        assert HARDCODED_DEFAULTS["EFSClientConnections"] == 1000.0

    def test_hardcoded_defaults_s3(self):
        assert HARDCODED_DEFAULTS["S34xxErrors"] == 100.0
        assert HARDCODED_DEFAULTS["S35xxErrors"] == 10.0
        assert HARDCODED_DEFAULTS["S3BucketSizeBytes"] == 1000000000000.0
        assert HARDCODED_DEFAULTS["S3NumberOfObjects"] == 10000000.0

    def test_hardcoded_defaults_sagemaker(self):
        assert HARDCODED_DEFAULTS["SMInvocations"] == 100000.0
        assert HARDCODED_DEFAULTS["SMInvocationErrors"] == 0.0
        assert HARDCODED_DEFAULTS["SMModelLatency"] == 1000.0
        assert HARDCODED_DEFAULTS["SMCPU"] == 80.0

    def test_hardcoded_defaults_sns(self):
        assert HARDCODED_DEFAULTS["SNSNotificationsFailed"] == 0.0
        assert HARDCODED_DEFAULTS["SNSMessagesPublished"] == 1000000.0

    def test_monitored_api_events_create_extended(self):
        from common import MONITORED_API_EVENTS
        expected_create = [
            "CreateQueue", "CreateService", "CreateCluster",
            "CreateTable", "CreateDistribution", "CreateWebACL",
            "CreateHealthCheck", "CreateConnection", "CreateFileSystem",
            "CreateBucket", "CreateEndpoint", "CreateTopic",
        ]
        for event in expected_create:
            assert event in MONITORED_API_EVENTS["CREATE"], f"{event} not in CREATE"

    def test_monitored_api_events_delete_extended(self):
        from common import MONITORED_API_EVENTS
        expected_delete = [
            "DeleteQueue", "DeleteService", "DeleteCluster",
            "DeleteTable", "DeleteDistribution", "DeleteWebACL",
            "DeleteHealthCheck", "DeleteConnection", "DeleteFileSystem",
            "DeleteBucket", "DeleteEndpoint", "DeleteTopic",
        ]
        for event in expected_delete:
            assert event in MONITORED_API_EVENTS["DELETE"], f"{event} not in DELETE"

    def test_monitored_api_events_tag_change_sqs(self):
        from common import MONITORED_API_EVENTS
        assert "TagQueue" in MONITORED_API_EVENTS["TAG_CHANGE"]
        assert "UntagQueue" in MONITORED_API_EVENTS["TAG_CHANGE"]

    def test_monitored_api_events_tag_change_existing_covers_new(self):
        """TagResource/UntagResource already covers ECS, MSK, DynamoDB, EFS, SageMaker, SNS."""
        from common import MONITORED_API_EVENTS
        assert "TagResource" in MONITORED_API_EVENTS["TAG_CHANGE"]
        assert "UntagResource" in MONITORED_API_EVENTS["TAG_CHANGE"]
