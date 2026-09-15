"""
리소스 타입 레지스트리 — 타입 하나 = 모듈 하나 (docs/specs/resource-type-registry)

`base.py`가 데이터클래스·레지스트리·파생 뷰를, 타입별 모듈이 스펙(알람 정의 포함)을 갖는다. 이 파일은 둘을 묶어
등록 순서를 정한다 — **이 import 순서가 `SUPPORTED_RESOURCE_TYPES` 순서다.** 타입을 추가하면 모듈을 만들고 여기 한 줄.
"""

from common.resource_types.base import (  # noqa: F401
    CREATE, DELETE, KINDS, MODIFY, MULTI, SHARED_LIFECYCLE, TAG_CHANGE,
    Lifecycle, ResourceTypeSpec,
    add_shared_thresholds, all_specs, collector_modules, event_to_type, get, global_service_regions,
    hardcoded_defaults, metric_display, monitored_api_events, register, shared_threshold_reasons,
    tagged_services, type_to_collector, types,
)

# 등록 순서 = 타입 목록 순서. isort가 재정렬하지 않도록 한 줄씩.
from common.resource_types import ec2  # noqa: E402, F401
from common.resource_types import rds  # noqa: E402, F401
from common.resource_types import alb  # noqa: E402, F401
from common.resource_types import nlb  # noqa: E402, F401
from common.resource_types import tg  # noqa: E402, F401
from common.resource_types import aurora_rds  # noqa: E402, F401
from common.resource_types import docdb  # noqa: E402, F401
from common.resource_types import elasticache  # noqa: E402, F401
from common.resource_types import nat  # noqa: E402, F401
from common.resource_types import lambda_fn  # noqa: E402, F401
from common.resource_types import vpn  # noqa: E402, F401
from common.resource_types import apigw  # noqa: E402, F401
from common.resource_types import acm  # noqa: E402, F401
from common.resource_types import backup  # noqa: E402, F401
from common.resource_types import mq  # noqa: E402, F401
from common.resource_types import clb  # noqa: E402, F401
from common.resource_types import opensearch  # noqa: E402, F401
from common.resource_types import sqs  # noqa: E402, F401
from common.resource_types import ecs  # noqa: E402, F401
from common.resource_types import msk  # noqa: E402, F401
from common.resource_types import dynamodb  # noqa: E402, F401
from common.resource_types import cloudfront  # noqa: E402, F401
from common.resource_types import waf  # noqa: E402, F401
from common.resource_types import route53  # noqa: E402, F401
from common.resource_types import dx  # noqa: E402, F401
from common.resource_types import efs  # noqa: E402, F401
from common.resource_types import s3  # noqa: E402, F401
from common.resource_types import sagemaker  # noqa: E402, F401
from common.resource_types import sns  # noqa: E402, F401
# 타입 밖 표시명·기본치(옛 태그 키) — 타입 뒤에 등록한다.
from common.resource_types import legacy  # noqa: E402, F401
