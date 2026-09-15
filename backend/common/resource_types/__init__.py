"""
리소스 타입 레지스트리 — 타입 하나 = 스펙 하나, 나머지는 파생 (docs/specs/resource-type-registry D3)

2026-09까지 한 리소스 타입은 12개 파일 15곳에 흩어져 있었다: 타입 목록, 수집기 모듈 목록과 타입→수집기 맵,
CloudTrail 이벤트 목록(3곳), 태그 캐시가 프라임할 서비스, 글로벌 리전, 알람 정의에서 파생되는 맵 셋.
횡단 변경이 26개 수집기 중 15개에서 멈추고(태그 캐시), 파생 가능한 맵을 손으로 두 번 적어 테스트로 드리프트를
막는 구조였다. 이 모듈이 **한 곳**이다 — 아래 스펙을 고치면 뷰(`types()`·`monitored_api_events()`·
`type_to_collector()`·`tagged_services()`…)가 따라오고, 소비처(`common/__init__`, `daily_monitor`,
`remediation_handler`, `tag_cache`)는 그 뷰를 읽는다.

알림 채널 어댑터(`notification_adapters.py`)와 같은 수법이다: `register()` 하나로 전부 따라온다.

이 모듈은 `common.alarm_registry`(정의 데이터, logging만 import)와 표준 라이브러리만 의존한다 — 수집기는
**모듈 이름**으로만 가리키고(`daily_monitor`가 import한다), CloudTrail payload에서 ID를 뽑는 추출기는
`remediation_handler`에 남긴다(이벤트→타입 매핑만 여기). 그래야 `common/__init__`이 이 모듈을 import해도
순환이 없다.

P2에서는 기존 데이터(알람 정의·이벤트·수집기)를 **가리키는** 스펙이다. P2.4~2.5에서 알람 정의와 표시명·기본치가
타입별 스펙 파일로 옮겨오고, P3에서 `rgt_filters`가 범용 수집기의 나열 소스가 된다.
"""

from __future__ import annotations

from dataclasses import dataclass

from common.alarm_registry import _get_alarm_defs_raw

# CloudTrail 이벤트 종류 — MONITORED_API_EVENTS의 키. 순서는 옛 상수의 순서를 따른다.
MODIFY, DELETE, TAG_CHANGE, CREATE = "MODIFY", "DELETE", "TAG_CHANGE", "CREATE"
KINDS: tuple[str, ...] = (MODIFY, DELETE, TAG_CHANGE, CREATE)

#: 여러 서비스가 같은 이름을 쓰는 이벤트 — ARN을 봐야 타입이 갈린다. `_API_MAP`은 이걸 "MULTI"로 부른다.
MULTI = "MULTI"


@dataclass(frozen=True)
class Lifecycle:
    """CloudTrail 이벤트 하나. `target`은 remediation이 쓰는 타입 이름 — 기본은 스펙 타입이지만, ELB 계열은
    이벤트 이름이 ALB/NLB/CLB를 구분하지 않아 "ELB"로 받고 ARN으로 가른다."""
    event: str
    kind: str
    target: str = ""


@dataclass(frozen=True)
class ResourceTypeSpec:
    type: str
    label: str
    #: `common.collectors` 아래 모듈 이름. 여러 타입이 하나를 공유할 수 있다(RDS 계열 → rds, LB 계열 → elb).
    collector: str
    #: 같은 수집기를 가리키는 옛 타입 이름(고아 정리 경로가 알람 이름에서 읽는다) — ELB, NATGateway.
    aliases: tuple[str, ...] = ()
    #: Resource Groups Tagging `ResourceTypeFilters`(design.md 부록 A). 실계정에서 유효성 확인됨(2026-09-15).
    rgt_filters: tuple[str, ...] = ()
    #: 런 시작 시 태그 캐시가 이 서비스를 `GetResources`로 프라임하는가(`tag_cache.TAGGED_SERVICES`).
    #: False인 이유는 `notes`에 — EC2 계열은 하위 리소스 ARN이 너무 많고 서버 측 태그 필터가 있다.
    rgt_prime: bool = False
    lifecycle: tuple[Lifecycle, ...] = ()
    #: 메트릭이 us-east-1에만 발행되는 글로벌 서비스.
    global_region: str = ""
    #: 파생 규칙에서 벗어나는 것의 이유. 맵은 이유를 말해 주지 않았다 — 스펙은 말한다(요구사항 R9).
    notes: str = ""

    def alarms(self, resource_tags: dict | None = None) -> list[dict]:
        """이 타입의 알람 정의(태그 조건부 변형 포함). 정의 자체는 아직 `alarm_registry`에 있다(P2.4에서 옮김)."""
        return _get_alarm_defs_raw(self.type, resource_tags)

    @property
    def rgt_services(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(f.split(":", 1)[0] for f in self.rgt_filters))

    def events(self) -> tuple[Lifecycle, ...]:
        return tuple(Lifecycle(e.event, e.kind, e.target or self.type) for e in self.lifecycle)


# ────────────────────────────────── 레지스트리

_SPECS: dict[str, ResourceTypeSpec] = {}
_ALIASES: dict[str, str] = {}


def register(spec: ResourceTypeSpec) -> ResourceTypeSpec:
    if spec.type in _SPECS or spec.type in _ALIASES:
        raise ValueError(f"resource type already registered: {spec.type}")
    for alias in spec.aliases:
        if alias in _SPECS or alias in _ALIASES:
            raise ValueError(f"alias already registered: {alias} (for {spec.type})")
    if spec.kind_check():
        raise ValueError(spec.kind_check())
    _SPECS[spec.type] = spec
    for alias in spec.aliases:
        _ALIASES[alias] = spec.type
    return spec


def _kind_check(self: ResourceTypeSpec) -> str:
    bad = [e.event for e in self.lifecycle if e.kind not in KINDS]
    return f"{self.type}: unknown lifecycle kind on {bad}" if bad else ""


ResourceTypeSpec.kind_check = _kind_check      # type: ignore[attr-defined]


def get(type_or_alias: str) -> ResourceTypeSpec:
    key = _ALIASES.get(type_or_alias, type_or_alias)
    try:
        return _SPECS[key]
    except KeyError:
        raise KeyError(f"unknown resource type: {type_or_alias!r} (known: {', '.join(_SPECS)})") from None


def all_specs() -> list[ResourceTypeSpec]:
    return list(_SPECS.values())


def types() -> list[str]:
    """지원 타입 목록 — 등록 순서. `common.SUPPORTED_RESOURCE_TYPES`가 이것이다."""
    return list(_SPECS)


#: 특정 타입에 속하지 않는 생명주기 이벤트. 12개 서비스가 `TagResource`/`UntagResource`를 같은 이름으로 낸다.
SHARED_LIFECYCLE: tuple[Lifecycle, ...] = (
    Lifecycle("TagResource", TAG_CHANGE, target=MULTI),
    Lifecycle("UntagResource", TAG_CHANGE, target=MULTI),
)


# ────────────────────────────────── 파생 뷰 — 소비처가 읽는 이름들

def monitored_api_events() -> dict[str, list[str]]:
    """종류 → CloudTrail 이벤트 이름. `common.MONITORED_API_EVENTS`. CFN 템플릿의 EventPattern과 같아야 한다(R8)."""
    out: dict[str, list[str]] = {k: [] for k in KINDS}
    for spec in _SPECS.values():
        for e in spec.events():
            if e.event not in out[e.kind]:
                out[e.kind].append(e.event)
    for e in SHARED_LIFECYCLE:
        if e.event not in out[e.kind]:
            out[e.kind].append(e.event)
    return out


def event_to_type() -> dict[str, str]:
    """CloudTrail 이벤트 → remediation이 처리에 쓰는 타입 이름("ELB"·"MULTI" 포함). `_API_MAP`의 타입 절반."""
    out: dict[str, str] = {}
    for spec in _SPECS.values():
        for e in spec.events():
            if e.event in out and out[e.event] != e.target:
                raise ValueError(f"event {e.event} claimed by {out[e.event]} and {e.target}")
            out[e.event] = e.target
    for e in SHARED_LIFECYCLE:
        out[e.event] = e.target
    return out


def type_to_collector() -> dict[str, str]:
    """타입(별칭 포함) → 수집기 모듈 이름. `daily_monitor._RESOURCE_TYPE_TO_COLLECTOR`."""
    out: dict[str, str] = {}
    for spec in _SPECS.values():
        out[spec.type] = spec.collector
        for alias in spec.aliases:
            out[alias] = spec.collector
    return out


def collector_modules() -> list[str]:
    """수집기 모듈 이름 — 중복 제거, 등록 순서. `daily_monitor._COLLECTOR_MODULES`."""
    return list(dict.fromkeys(s.collector for s in _SPECS.values()))


def tagged_services() -> list[str]:
    """태그 캐시가 프라임하는 RGT 서비스 — `rgt_prime`인 스펙의 서비스, 등록 순서. `tag_cache.TAGGED_SERVICES`."""
    return list(dict.fromkeys(svc for s in _SPECS.values() if s.rgt_prime for svc in s.rgt_services))


def global_service_regions() -> dict[str, str]:
    return {s.type: s.global_region for s in _SPECS.values() if s.global_region}


# ────────────────────────────────── 스펙 — 등록 순서가 SUPPORTED_RESOURCE_TYPES 순서다

_EC2_SUBRESOURCE_NOTE = ("RGT 프라임 안 함: ec2 서비스는 스냅숏·ENI·보안그룹 등 하위 리소스 ARN이 수백 개라 프라임 비용이 크고, "
                         "describe_*가 서버 측 태그 필터(Filter=tag:Monitoring)를 지원한다.")

register(ResourceTypeSpec(
    type="EC2", label="EC2 인스턴스", collector="ec2",
    rgt_filters=("ec2:instance",), rgt_prime=False,
    lifecycle=(Lifecycle("ModifyInstanceAttribute", MODIFY), Lifecycle("ModifyInstanceType", MODIFY),
               Lifecycle("TerminateInstances", DELETE), Lifecycle("RunInstances", CREATE),
               Lifecycle("CreateTags", TAG_CHANGE), Lifecycle("DeleteTags", TAG_CHANGE)),
    notes=_EC2_SUBRESOURCE_NOTE + " 앱 상태검사 알람은 옵트인(Threshold_StatusCheckFailed_Application).",
))
register(ResourceTypeSpec(
    type="RDS", label="RDS 인스턴스", collector="rds",
    rgt_filters=("rds:db",), rgt_prime=True,
    lifecycle=(Lifecycle("ModifyDBInstance", MODIFY), Lifecycle("DeleteDBInstance", DELETE),
               Lifecycle("CreateDBInstance", CREATE),
               Lifecycle("AddTagsToResource", TAG_CHANGE), Lifecycle("RemoveTagsFromResource", TAG_CHANGE)),
    notes="rds:db 필터와 이 이벤트들은 Aurora·DocDB 인스턴스도 낸다 — 엔진은 describe로 판별(remediation 엔진 스니핑).",
))
register(ResourceTypeSpec(
    type="ALB", label="Application Load Balancer", collector="elb", aliases=("ELB",),
    rgt_filters=("elasticloadbalancing:loadbalancer",), rgt_prime=True,
    lifecycle=(Lifecycle("ModifyLoadBalancerAttributes", MODIFY, "ELB"), Lifecycle("ModifyListener", MODIFY, "ELB"),
               Lifecycle("DeleteLoadBalancer", DELETE, "ELB"), Lifecycle("CreateLoadBalancer", CREATE, "ELB"),
               Lifecycle("AddTags", TAG_CHANGE, "ELB"), Lifecycle("RemoveTags", TAG_CHANGE, "ELB")),
    notes="LB 이벤트 이름은 ALB/NLB/CLB를 구분하지 않아 target=ELB로 받고 ARN(loadbalancer/app|net)으로 가른다. "
          "필터도 셋이 공유한다. NLB·CLB 스펙은 그래서 lifecycle이 비어 있다.",
))
register(ResourceTypeSpec(
    type="NLB", label="Network Load Balancer", collector="elb",
    rgt_filters=("elasticloadbalancing:loadbalancer",), rgt_prime=True,
    notes="생명주기 이벤트는 ALB 스펙(target=ELB)에 — 이벤트 이름이 LB 종류를 구분하지 않는다.",
))
register(ResourceTypeSpec(
    type="TG", label="대상 그룹", collector="elb",
    rgt_filters=("elasticloadbalancing:targetgroup",), rgt_prime=True,
    lifecycle=(Lifecycle("DeleteTargetGroup", DELETE), Lifecycle("CreateTargetGroup", CREATE)),
    notes="NLB 대상그룹은 네임스페이스가 AWS/NetworkELB(빌드 시 해석기), TargetType=alb는 알람 없음. LB 계층·short-id 역매핑 때문에 나열은 elb 수집기.",
))
register(ResourceTypeSpec(
    type="AuroraRDS", label="Aurora", collector="rds",
    rgt_filters=("rds:db",), rgt_prime=True,
    notes="RDS 스펙의 이벤트·필터를 공유한다. 알람 정의는 Serverless v2/Writer/Readers 태그로 갈린다.",
))
register(ResourceTypeSpec(
    type="DocDB", label="DocumentDB", collector="docdb",
    rgt_filters=("rds:db",), rgt_prime=True,
    notes="생명주기 이벤트는 RDS 스펙의 것을 공유한다 — CloudTrail이 rds.amazonaws.com의 ModifyDBInstance/DeleteDBInstance로 내고, remediation이 엔진(docdb)으로 판별한다.",
))
register(ResourceTypeSpec(
    type="ElastiCache", label="ElastiCache", collector="elasticache",
    rgt_filters=("elasticache:cluster",), rgt_prime=True,
    lifecycle=(Lifecycle("ModifyCacheCluster", MODIFY), Lifecycle("DeleteCacheCluster", DELETE),
               Lifecycle("CreateCacheCluster", CREATE)),
))
register(ResourceTypeSpec(
    type="NAT", label="NAT Gateway", collector="natgw", aliases=("NATGateway",),
    rgt_filters=("ec2:natgateway",), rgt_prime=False,
    lifecycle=(Lifecycle("DeleteNatGateway", DELETE), Lifecycle("CreateNatGateway", CREATE)),
    notes=_EC2_SUBRESOURCE_NOTE + " natgw 수집기가 이미 서버 측 필터를 쓴다 — 다른 EC2 계열이 따라갈 본보기.",
))
register(ResourceTypeSpec(
    type="Lambda", label="Lambda 함수", collector="lambda_fn",
    rgt_filters=("lambda:function",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateFunction20150331", CREATE), Lifecycle("DeleteFunction20150331", DELETE)),
))
register(ResourceTypeSpec(
    type="VPN", label="Site-to-Site VPN", collector="vpn",
    rgt_filters=("ec2:vpn-connection",), rgt_prime=False,
    lifecycle=(Lifecycle("DeleteVpnConnection", DELETE),),
    notes=_EC2_SUBRESOURCE_NOTE,
))
register(ResourceTypeSpec(
    type="APIGW", label="API Gateway", collector="apigw",
    rgt_filters=("apigateway:restapis", "apigateway:apis"), rgt_prime=True,
    lifecycle=(Lifecycle("CreateRestApi", CREATE), Lifecycle("CreateApi", CREATE),
               Lifecycle("DeleteRestApi", DELETE), Lifecycle("DeleteApi", DELETE)),
    notes="REST(restapis, 디멘션 ApiName)와 HTTP/WebSocket(apis, 디멘션 ApiId)은 다른 리소스 타입 — 필터 둘, 알람 정의는 _api_type 태그로 갈린다.",
))
register(ResourceTypeSpec(
    type="ACM", label="ACM 인증서", collector="acm",
    rgt_filters=("acm:certificate",), rgt_prime=True,
    lifecycle=(Lifecycle("DeleteCertificate", DELETE),),
    notes="TagName은 도메인명 — alive 판정이 list_certificates+describe로 역매핑한다.",
))
register(ResourceTypeSpec(
    type="Backup", label="AWS Backup 볼트", collector="backup",
    rgt_filters=("backup:backup-vault",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateBackupVault", CREATE), Lifecycle("DeleteBackupVault", DELETE)),
))
register(ResourceTypeSpec(
    type="MQ", label="Amazon MQ 브로커", collector="mq",
    rgt_filters=("mq:broker",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateBroker", CREATE), Lifecycle("DeleteBroker", DELETE)),
    notes="TagName `{broker}-{1|2}` — alive 판정이 접미를 떼고 조회한다.",
))
register(ResourceTypeSpec(
    type="CLB", label="Classic Load Balancer", collector="clb",
    rgt_filters=("elasticloadbalancing:loadbalancer",), rgt_prime=True,
    notes="생명주기 이벤트는 ALB 스펙(target=ELB)에. ARN에 loadbalancer/app|net 접미가 없는 것이 classic.",
))
register(ResourceTypeSpec(
    type="OpenSearch", label="OpenSearch 도메인", collector="opensearch",
    rgt_filters=("es:domain",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateDomain", CREATE), Lifecycle("DeleteDomain", DELETE)),
))
register(ResourceTypeSpec(
    type="SQS", label="SQS 큐", collector="sqs",
    rgt_filters=("sqs",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateQueue", CREATE), Lifecycle("DeleteQueue", DELETE),
               Lifecycle("TagQueue", TAG_CHANGE), Lifecycle("UntagQueue", TAG_CHANGE)),
))
register(ResourceTypeSpec(
    type="ECS", label="ECS 서비스", collector="ecs",
    rgt_filters=("ecs:service",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateService", CREATE), Lifecycle("DeleteService", DELETE)),
))
register(ResourceTypeSpec(
    type="MSK", label="MSK 클러스터", collector="msk",
    rgt_filters=("kafka:cluster",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateCluster", CREATE), Lifecycle("DeleteCluster", DELETE)),
))
register(ResourceTypeSpec(
    type="DynamoDB", label="DynamoDB 테이블", collector="dynamodb",
    rgt_filters=("dynamodb:table",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateTable", CREATE), Lifecycle("DeleteTable", DELETE)),
))
register(ResourceTypeSpec(
    type="CloudFront", label="CloudFront 배포", collector="cloudfront",
    rgt_filters=("cloudfront:distribution",), rgt_prime=True, global_region="us-east-1",
    lifecycle=(Lifecycle("CreateDistribution", CREATE), Lifecycle("DeleteDistribution", DELETE)),
))
register(ResourceTypeSpec(
    type="WAF", label="WAFv2 Web ACL", collector="waf",
    rgt_filters=("wafv2:webacl",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateWebACL", CREATE), Lifecycle("DeleteWebACL", DELETE)),
    notes="REGIONAL 스코프는 리전, CLOUDFRONT 스코프는 us-east-1에서 조회.",
))
register(ResourceTypeSpec(
    type="Route53", label="Route 53 상태 검사", collector="route53",
    rgt_filters=("route53:healthcheck",), rgt_prime=True, global_region="us-east-1",
    lifecycle=(Lifecycle("CreateHealthCheck", CREATE), Lifecycle("DeleteHealthCheck", DELETE)),
))
register(ResourceTypeSpec(
    type="DX", label="Direct Connect", collector="dx",
    rgt_filters=("directconnect:dxcon",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateConnection", CREATE), Lifecycle("DeleteConnection", DELETE)),
))
register(ResourceTypeSpec(
    type="EFS", label="EFS 파일 시스템", collector="efs",
    rgt_filters=("elasticfilesystem:file-system",), rgt_prime=False,
    lifecycle=(Lifecycle("CreateFileSystem", CREATE), Lifecycle("DeleteFileSystem", DELETE)),
    notes="RGT 프라임 안 함: efs 수집기가 태그 캐시를 참조하지 않는다(2026-09 현재). P3 범용 수집기로 옮기며 켠다.",
))
register(ResourceTypeSpec(
    type="S3", label="S3 버킷", collector="s3",
    rgt_filters=("s3",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateBucket", CREATE), Lifecycle("DeleteBucket", DELETE)),
    notes="버킷 메트릭은 버킷 리전에서 — 나열 뒤 리전 조회가 필요하다.",
))
register(ResourceTypeSpec(
    type="SageMaker", label="SageMaker 엔드포인트", collector="sagemaker",
    rgt_filters=("sagemaker:endpoint",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateEndpoint", CREATE), Lifecycle("DeleteEndpoint", DELETE)),
))
register(ResourceTypeSpec(
    type="SNS", label="SNS 토픽", collector="sns",
    rgt_filters=("sns",), rgt_prime=True,
    lifecycle=(Lifecycle("CreateTopic", CREATE), Lifecycle("DeleteTopic", DELETE)),
))
