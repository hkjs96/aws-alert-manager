"""
Alarm Registry — 알람 정의에서 **파생**되는 표와 조회 (docs/specs/resource-type-registry)

알람 정의의 정본은 타입별 스펙 모듈(`common/resource_types/<type>.py`)이다. 이 모듈은 그 정의에서 평가 정책 적용,
타입별 정의 조회, 메트릭 키·네임스페이스·디멘션 키 표 파생, 표시명, 심각도만 제공한다. 옛 이름(`_EC2_ALARMS` 등)은
더 재수출하지 않는다 — 정의가 필요하면 스펙 모듈에서 직접 import한다.
"""

import logging

from common.resource_types.base import (
    all_specs as _all_specs,
    global_service_regions as _global_service_regions,
    metric_display as _metric_display,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# 메트릭별 표시이름/방향/단위 매핑
# ──────────────────────────────────────────────

# 메트릭 키 → (알람 이름에 쓰는 지표명, 방향, 단위). **스펙에서 파생** — 각 타입 모듈의 `display` + legacy.py.
_METRIC_DISPLAY: dict[str, tuple[str, str, str]] = _metric_display()


# ──────────────────────────────────────────────
# 리소스 유형별 알람 정의
# ──────────────────────────────────────────────


# ──────────────────────────────────────────────
# M-of-N 평가 정책 (Severity 기반)
# ──────────────────────────────────────────────
# 데이터포인트 1개 초과로 즉시 울리는 오탐(순간 스파이크)을 줄이기 위해,
# 심각도에 따라 "N개 평가 창에서 M개 초과 시 알람"을 기본 적용한다.
# 값: (evaluation_periods, datapoints_to_alarm)
_EVAL_POLICY_BY_SEVERITY: dict[str, tuple[int, int]] = {
    "SEV-2": (3, 2),   # 에러 급증: 15분 창에서 10분 이상 지속 시
    "SEV-3": (3, 2),   # 포화도: CPU/메모리는 지속성이 판단 기준
    "SEV-4": (5, 3),   # 성능 저하: 추세로 판단
    "SEV-5": (5, 3),   # 참고 지표
}


def _apply_eval_policy(defs: list[dict]) -> list[dict]:
    """Severity 기반 M-of-N 평가 정책을 알람 정의에 적용한다.

    적용 제외 (즉시 평가 1/1 유지):
    - SEV-1: 가용성 직결 — 감지 지연 불가
    - treat_missing_data="breaching": 데이터 없음=장애로 보는 메트릭.
      M-of-N을 얹으면 다운 감지 자체가 M배 늦어진다.
    - period ≥ 1시간: 저빈도 메트릭(DaysToExpiry 등)은 스파이크 필터가
      무의미하고 알림만 하루 단위로 늦어진다.
    - 정의가 datapoints_to_alarm을 직접 명시: 개별 오버라이드 존중.

    원본 정의 dict는 변경하지 않는다(적용 시 복사본 반환).
    """
    out = []
    for d in defs:
        severity = get_severity(d.get("metric_key") or d["metric"])
        policy = _EVAL_POLICY_BY_SEVERITY.get(severity)
        if (
            policy is None
            or d.get("treat_missing_data") == "breaching"
            or d.get("period", 0) >= 3600
            or "datapoints_to_alarm" in d
        ):
            out.append(d)
            continue
        ep, dp = policy
        out.append({**d, "evaluation_periods": ep, "datapoints_to_alarm": dp})
    return out


def get_dynamic_eval_policy(metric_name: str) -> tuple[int, int]:
    """동적(Threshold_* 태그) 알람의 평가 정책.

    동적 알람은 treat_missing_data=notBreaching·period=300 고정이므로
    Severity 가드만 적용한다. SEV-1 메트릭은 정책 표에 없어 즉시(1/1) 평가.
    """
    return _EVAL_POLICY_BY_SEVERITY.get(get_severity(metric_name), (1, 1))


def _get_alarm_defs(resource_type: str, resource_tags: dict | None = None) -> list[dict]:
    """리소스 타입의 알람 정의 (M-of-N 평가 정책 적용 후)."""
    return _apply_eval_policy(_get_alarm_defs_raw(resource_type, resource_tags))


#: 타입 → 알람 정의(리스트 또는 `Callable[[tags], list]`). **스펙에서 파생** — 정의는 `common/resource_types/<type>.py`에.
_ALARM_DEFS_BY_TYPE: dict = {s.type: s.alarm_defs for s in _all_specs()}


def _get_alarm_defs_raw(resource_type: str, resource_tags: dict | None = None) -> list[dict]:
    entry = _ALARM_DEFS_BY_TYPE.get(resource_type)
    if entry is None:
        return []
    return entry(resource_tags or {}) if callable(entry) else entry


# ──────────────────────────────────────────────
# 타입별 파생 뷰 — 손으로 적지 않고 알람 정의에서 계산한다 (docs/specs/resource-type-registry P1)
# ──────────────────────────────────────────────
# 아래 세 표는 2026-09까지 손으로 유지됐고, 정의와 어긋나지 않는지를 PBT가 지켰다. 정의에서 파생되는
# 값을 두 번 적을 이유가 없다 — 이제 정의가 바뀌면 표가 따라온다. 테스트가 지키는 것은 "파생 규칙이
# 조건 분기의 변형을 전부 열거하는가"다(tests/test_pbt_registry_completeness.py). 규칙은 셋이 다르다:
#   메트릭 키   = 모든 변형의 합집합 − 옵트인(`opt_in`)      (정적 표라 태그 조건부 키도 담는다)
#   네임스페이스 = 모든 변형의 합집합 + 빌드 시 해석기가 바꿔 끼우는 것(_EXTRA_NAMESPACES)
#   디멘션 키   = **기본 변형**(태그 없음)의 키                (변형은 다를 수 있다 — APIGW HTTP/WS는 ApiId)

#: 조건부 정의 함수가 읽는 태그의 **모든 조합**. 파생은 이 변형을 전부 열거해 합친다.
#: 조건 분기에서 태그를 새로 읽으면 여기에도 적어야 한다 — 완전성 테스트가 함수 소스를 훑어 잡는다.
_ALARM_DEF_VARIANTS: dict[str, tuple[dict, ...]] = {s.type: s.variants for s in _all_specs() if s.variants}

#: 정의에는 없지만 빌드 시 해석기가 태그를 보고 바꿔 끼우는 네임스페이스
#: (`dimension_builder._resolve_tg_namespace`). 정의가 그 지식을 갖게 되면(P2, TG 스펙) 사라진다.
_EXTRA_NAMESPACES: dict[str, tuple[str, ...]] = {"TG": ("AWS/NetworkELB",)}


def _variant_defs(resource_type: str) -> list[dict]:
    """모든 변형의 알람 정의 — 중복 제거, 등장 순서 유지."""
    out: list[dict] = []
    seen: set[int] = set()
    for tags in _ALARM_DEF_VARIANTS.get(resource_type, ({},)):
        for d in _get_alarm_defs_raw(resource_type, tags):
            if id(d) not in seen:
                seen.add(id(d))
                out.append(d)
    return out


def _derive_metric_keys() -> dict[str, set[str]]:
    """타입별 기본 알람의 메트릭 키(tag_key = Threshold_{key}). 옵트인 정의는 뺀다 — 태그가 있어야 붙는
    알람이고, 동적 알람과의 중복은 `_get_hardcoded_metric_keys()`가 태그를 함께 보며 막는다."""
    return {
        t: {d.get("metric_key") or d["metric"] for d in _variant_defs(t) if not d.get("opt_in")}
        for t in _ALARM_DEFS_BY_TYPE
    }


def _derive_namespaces() -> dict[str, list[str]]:
    """타입별 CloudWatch 네임스페이스(메트릭 탐색 순서 = 정의 등장 순서)."""
    out: dict[str, list[str]] = {}
    for t in _ALARM_DEFS_BY_TYPE:
        ns: list[str] = []
        for d in _variant_defs(t):
            if d["namespace"] not in ns:
                ns.append(d["namespace"])
        for extra in _EXTRA_NAMESPACES.get(t, ()):
            if extra not in ns:
                ns.append(extra)
        out[t] = ns
    return out


def _derive_dimension_keys() -> dict[str, str]:
    """타입별 디멘션 키 — 기본 변형 정의들이 공유하는 키. 타입 수준 탐색(`dimension_builder`,
    `routes/resources.py`)이 쓰는 기본값이고, 알람 생성은 정의의 키를 직접 쓴다."""
    out: dict[str, str] = {}
    for t in _ALARM_DEFS_BY_TYPE:
        keys = list(dict.fromkeys(d["dimension_key"] for d in _get_alarm_defs_raw(t, {})))
        if len(keys) != 1:
            raise RuntimeError(f"{t}: default alarm defs must share one dimension_key, got {keys}")
        out[t] = keys[0]
    return out


_HARDCODED_METRIC_KEYS: dict[str, set[str]] = _derive_metric_keys()
_NAMESPACE_MAP: dict[str, list[str]] = _derive_namespaces()
_DIMENSION_KEY_MAP: dict[str, str] = _derive_dimension_keys()

# 글로벌 서비스 리전 매핑: 메트릭이 us-east-1에서만 발행되는 리소스 타입
# 알람 생성/검색/삭제 시 해당 리전의 CloudWatch 클라이언트를 사용해야 한다.
_GLOBAL_SERVICE_REGION: dict[str, str] = _global_service_regions()


def _get_hardcoded_metric_keys(resource_type: str, resource_tags: dict | None = None) -> set[str]:
    """resource_type과 resource_tags 기반으로 하드코딩 메트릭 키 집합을 반환.

    metric_key 우선, 없으면 metric 사용. NLB TG 등 LB 타입별 차이를 반영한다.
    반환값은 Threshold_{key} 태그 suffix와 일치한다.
    """
    alarm_defs = _get_alarm_defs(resource_type, resource_tags)
    return {d.get("metric_key") or d["metric"] for d in alarm_defs}


# _METRIC_DISPLAY의 display_name → metric_key 역방향 조회 캐시
_METRIC_NAME_TO_KEY: dict[str, str] = {
    display_name: key
    for key, (display_name, _, _) in _METRIC_DISPLAY.items()
    if display_name != key  # 동일한 경우 직접 키 조회로 처리
}


def _metric_name_to_key(cw_name: str) -> str:
    """CloudWatch 메트릭 이름 → 내부 메트릭 키 변환.

    1. 직접 키 매칭 (cw_name이 이미 metric_key인 경우)
    2. display_name 역방향 조회 (_METRIC_DISPLAY[key][0] == cw_name)
    3. 매칭 실패 시 cw_name 그대로 반환
    """
    if cw_name in _METRIC_DISPLAY:
        return cw_name
    return _METRIC_NAME_TO_KEY.get(cw_name, cw_name)


# ──────────────────────────────────────────────
# Severity 등급 체계 (Phase2 §13, PagerDuty SEV 기준)
# ──────────────────────────────────────────────

# 메트릭 키 → 기본 Severity 매핑.
# 기준: 해당 메트릭이 ALARM 상태일 때의 비즈니스 영향도.
# 미정의 메트릭은 get_severity()에서 "SEV-5"로 폴백.
_DEFAULT_SEVERITY: dict[str, str] = {
    # SEV-1: 서비스 완전 중단 또는 접근 불가
    "StatusCheckFailed":  "SEV-1",
    "StatusCheckFailed_Application": "SEV-1",   # 앱이 응답하지 않음 — 시스템 검사와 같은 급
    "HealthyHostCount":   "SEV-1",
    "TunnelState":        "SEV-1",
    "ConnectionState":    "SEV-1",
    "HealthCheckStatus":  "SEV-1",
    "ActiveControllerCount": "SEV-1",
    # docs/ALARM-RULES.md §13-2에 SEV-1로 정의되어 있으나 코드에 누락돼
    # SEV-5로 폴백되던 항목 (클러스터 완전 다운 지표).
    "ClusterStatusRed":   "SEV-1",

    # SEV-2: 에러 급증, 서비스 품질 심각 저하
    "ELB5XX":                "SEV-2",
    "HTTPCode_ELB_5XX_Count": "SEV-2",
    "CLB5XX":                "SEV-2",
    "Errors":                "SEV-2",
    "UnHealthyHostCount":    "SEV-2",
    "Api5XXError":           "SEV-2",
    "Api5xx":                "SEV-2",
    "ErrorPortAllocation":   "SEV-2",
    "TargetConnectionError": "SEV-2",

    # SEV-3: 리소스 포화 근접, 조치 안 하면 장애 가능
    "CPU":                "SEV-3",
    "Memory":             "SEV-3",
    "Disk":               "SEV-3",
    "FreeMemoryGB":       "SEV-3",
    "FreeStorageGB":      "SEV-3",
    "CPUUtilization":     "SEV-3",
    "mem_used_percent":   "SEV-3",
    "disk_used_percent":  "SEV-3",
    "FreeableMemory":     "SEV-3",
    "FreeStorageSpace":   "SEV-3",
    "FreeLocalStorageGB": "SEV-3",
    "FreeLocalStorage":  "SEV-3",
    "EngineCPU":          "SEV-3",
    "ACUUtilization":     "SEV-3",
    "DaysToExpiry":       "SEV-3",
    "ReplicaLag":         "SEV-3",
    "ReaderReplicaLag":   "SEV-3",
    "PacketsDropCount":   "SEV-3",
    "Evictions":          "SEV-3",
    "OSFreeStorageSpace": "SEV-3",

    # SEV-4: 성능 저하, 사용자 체감 가능하나 서비스 중단 아님
    "TGResponseTime":       "SEV-4",
    "ReadLatency":          "SEV-4",
    "WriteLatency":         "SEV-4",
    "TargetResponseTime":   "SEV-4",
    "Duration":             "SEV-4",
    "ApiLatency":           "SEV-4",
    "ELB4XX":               "SEV-4",
    "Api4XXError":          "SEV-4",
    "Api4xx":               "SEV-4",
    "BurstCreditBalance":   "SEV-4",

    # SEV-5: 트래픽/용량 참고 지표, 추세 모니터링
    "Connections":            "SEV-5",
    "TCPClientReset":         "SEV-5",
    "TCPTargetReset":         "SEV-5",
    "TCP_Client_Reset_Count": "SEV-5",
    "TCP_Target_Reset_Count": "SEV-5",
    "RequestCount":           "SEV-5",
    "DatabaseConnections":    "SEV-5",
    "CurrConnections":        "SEV-5",
    "ProcessedBytes":         "SEV-5",
    "ActiveFlowCount":        "SEV-5",
    "NewFlowCount":           "SEV-5",
    "ConnectionAttempts":     "SEV-5",
    "RequestCountPerTarget":  "SEV-5",
    "ServerlessDatabaseCapacity": "SEV-5",
    "DatabaseMemoryUsagePercentage": "SEV-2",
}


SEVERITIES: tuple[str, ...] = ("SEV-1", "SEV-2", "SEV-3", "SEV-4", "SEV-5")


def is_valid_severity(value) -> bool:
    """`SEV-1`~`SEV-5`인가. 태그·설명 메타데이터·API 입력 모두 이 집합 밖은 받지 않는다."""
    return isinstance(value, str) and value in SEVERITIES


def get_severity(metric_key: str) -> str:
    """메트릭 키에 대한 기본 Severity 등급 반환.

    Disk_root 등 Disk_ prefix, disk_used_percent_ prefix 모두 SEV-3 (포화도).
    미정의 메트릭은 SEV-5 폴백.
    """
    if metric_key.startswith("Disk_") or metric_key.startswith("disk_used_percent_"):
        return "SEV-3"
    return _DEFAULT_SEVERITY.get(metric_key, "SEV-5")
