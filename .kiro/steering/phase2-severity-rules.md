---
inclusion: manual
description: Phase2 알람 등급(Severity) 및 UI 설계 규칙
---

# Phase2 알람 등급(Severity) 및 UI 설계 규칙

## §13. 알람 등급(Severity) 체계

> 참고: [PagerDuty Incident Response — Severity Levels](https://response.pagerduty.com/before/severity_levels/), ITIL Incident Priority Matrix, Splunk/Datadog 등급 체계를 참고하여 MSP 환경에 맞게 재정의.

### 13-1. 등급 정의 (5단계, SEV 체계)

업계 표준인 SEV-1~5 체계를 채택한다. 숫자가 낮을수록 심각.

| 등급 | 코드 | 명칭 | 설명 | 대응 시간 | 알림 방식 |
|------|------|------|------|----------|----------|
| SEV-1 | Critical | 서비스 장애 | 고객 서비스 전면 중단. 다수 사용자 영향. SLA 위반 위험. | 즉시 (5분 내 확인) | 전화 + Slack + 에스컬레이션 |
| SEV-2 | High | 주요 기능 장애 | 핵심 기능 심각한 성능 저하 또는 부분 중단. 다수 사용자 영향. | 15분 내 확인 | Slack + 에스컬레이션 |
| SEV-3 | Medium | 부분 장애 | 일부 기능 제한 또는 단일 리소스 장애. 우회 가능. SEV-2로 확대 가능성. | 30분 내 확인 | Slack |
| SEV-4 | Low | 경미한 이슈 | 성능 저하, 단일 노드 장애 등. 고객 사용에 직접 영향 없음. | 4시간 내 확인 | Slack (저우선) |
| SEV-5 | Info | 참고/모니터링 | 정상 범위 내 추세 관찰. 버그/코스메틱 이슈. | 다음 업무 시간 | 로그만 |

SEV-1, SEV-2는 "Major Incident"로 분류하여 인시던트 대응 프로세스를 트리거한다 (Phase2).

### 13-2. 메트릭별 기본 등급 매핑

`alarm_registry.py`에 `_DEFAULT_SEVERITY` dict로 관리한다.
기본 등급은 "해당 메트릭이 ALARM 상태일 때의 비즈니스 영향도"를 기준으로 부여한다.

| 등급 | 메트릭 | 기준 |
|------|--------|------|
| SEV-1 | StatusCheckFailed, HealthyHostCount(<1), TunnelState(<1), ClusterStatusRed, ConnectionState(<1), HealthCheckStatus(<1) | 서비스 완전 중단 또는 접근 불가 |
| SEV-2 | ELB5XX(>임계치), CLB5XX, Errors(Lambda), UnHealthyHostCount(>임계치) | 에러 급증, 서비스 품질 심각 저하 |
| SEV-3 | CPU, Memory, Disk, FreeMemoryGB, FreeStorageGB, FreeLocalStorageGB, EngineCPU, ACUUtilization, DaysToExpiry | 리소스 포화 근접, 조치 안 하면 장애 가능 |
| SEV-4 | ReadLatency, WriteLatency, TargetResponseTime, TGResponseTime, Duration, ApiLatency | 성능 저하, 사용자 체감 가능하나 서비스 중단 아님 |
| SEV-5 | RequestCount, Connections, ProcessedBytes, ActiveFlowCount, NewFlowCount, ConnectionAttempts, BytesInPerSec | 트래픽/용량 참고 지표, 추세 모니터링 |

기본 등급이 정의되지 않은 메트릭은 SEV-5(Info)로 폴백한다.

### 13-3. 기본 등급 오버라이드

기본 등급은 시스템 전역 기본값이며, 다음 레벨에서 오버라이드 가능하다:

```
조회 우선순위 (높은 것이 우선):
1. 리소스별 오버라이드  — 특정 리소스의 특정 메트릭 등급 변경
2. 고객사별 오버라이드  — 고객사 전체에 적용되는 등급 정책
3. 시스템 기본값        — _DEFAULT_SEVERITY dict
```

Phase1: 시스템 기본값만 사용 (코드 내 dict)
Phase2: DB 도입 후 고객사별/리소스별 오버라이드 지원

오버라이드 예시:
- A고객사: CPU를 SEV-3(기본) → SEV-2로 승격 (CPU 민감한 워크로드)
- B고객사의 특정 RDS: Connections를 SEV-5(기본) → SEV-3으로 승격 (커넥션 풀 이슈 이력)

### 13-4. Severity 저장: CloudWatch 알람 태그

Severity는 AlarmDescription이 아닌 CloudWatch 알람 태그(Tags)에 저장한다.

```python
# 알람 생성 시
cw.put_metric_alarm(AlarmName=name, ...)
cw.tag_resource(
    ResourceARN=f"arn:aws:cloudwatch:{region}:{account}:alarm:{name}",
    Tags=[
        {"Key": "Severity", "Value": severity},   # "SEV-1" ~ "SEV-5"
        {"Key": "ManagedBy", "Value": "AlarmManager"},
    ]
)
```

선택 이유:
- severity 변경 시 `tag_resource`만 호출 (알람 재생성/PutMetricAlarm 불필요)
- DescribeAlarms + list_tags_for_resource로 조회 가능
- CloudWatch 네이티브, 별도 인프라 없음

### 13-5. Severity 변경

```python
# severity만 변경 (알람 재생성 없음)
cw.tag_resource(
    ResourceARN=alarm_arn,
    Tags=[{"Key": "Severity", "Value": "SEV-2"}]  # SEV-3 → SEV-2
)
```

Phase1: 코드에서 기본값 자동 부여만. UI에서는 읽기 전용 뱃지.
Phase2: UI에서 드롭다운으로 변경 가능 → tag_resource + DB 동시 업데이트.


## §14. Phase2 UI 범위 구분

### 14-1. 1번: 알람 매니징 (현재 범위)

| 기능 | 포함 여부 |
|------|----------|
| 알람 CRUD (생성/수정/삭제) | ✅ |
| 리소스 조회/필터링 | ✅ |
| 벌크 알람 설정 (선택적 메트릭 업데이트) | ✅ |
| 고객사별 기본 임계치 정의 | ✅ |
| 알람 동기화/드리프트 감지 | ✅ |
| 뮤트 규칙 (CloudWatch Alarm Mute Rules) | ✅ |
| 커버리지 리포트 | ✅ |
| xlsx 임포트 | ✅ |
| 템플릿 관리 | ✅ |
| 감사 로그 | ✅ |
| 동기화 상태 | ✅ |
| Severity 읽기 전용 뱃지 표시 | ✅ |
| Severity 기본값 dict + 알람 태그 저장 | ✅ |
| 알림: AWS Chatbot → Slack (기존 파이프라인) | ✅ |

### 14-2. 2번: 24x7 관제 (향후 범위)

| 기능 | 포함 여부 |
|------|----------|
| 알람 이벤트 수집 파이프라인 | 🔜 |
| 알림 채널 등록/관리 UI | 🔜 |
| 알림 라우팅 규칙 엔진 | 🔜 |
| Severity 변경 UI (드롭다운) | 🔜 |
| 에스컬레이션 체인 | 🔜 |
| 인시던트 관리 / Acknowledge | 🔜 |
| 실시간 알람 피드 (WebSocket) | 🔜 |
| 교대 근무(Shift) 관리 | 🔜 |

### 14-3. 1번에서 2번을 위해 미리 깔아둘 것

- `_DEFAULT_SEVERITY` dict를 `alarm_registry.py`에 추가
- 알람 생성 시 CloudWatch 알람 태그에 `Severity` 저장
- AlarmDescription에 `customer_id`, `account_id` 필드 예약 (멀티어카운트 대비)
- 고객사 데이터 모델에 severity 오버라이드 슬롯 예약 (DB 스키마)
- UI에서 Severity 읽기 전용 뱃지 표시 (변경은 2번에서)

## §15. 알림 흐름

### 15-1. Phase1 (현재)

```
CloudWatch ALARM → SNS → AWS Chatbot → Slack (고객사별)
```

기존 구축된 파이프라인 그대로 사용. UI에서 알림 채널 관리 불필요.

### 15-2. Phase2 (향후)

```
CloudWatch ALARM → SNS → Lambda(알림 라우터)
→ 알람 태그에서 Severity 조회
→ DB에서 라우팅 규칙 매칭 (severity + customer + resource_type)
→ 채널별 분기 (Slack/PagerDuty/Email/Webhook)
```

## §16. 서비스 확장 패턴

### 16-1. 서비스 스위칭

상단 서비스 스위처 패턴 (패턴 C) 채택.
- 현재: "Alarm Manager" 단독 앱
- 향후: 서비스 스위처 드롭다운으로 24x7 Monitoring, FinOps 등 추가
- 글로벌 필터(고객사/어카운트)는 서비스 간 공유

### 16-2. 고객사 관리

1번에서는 Settings 내 경량 고객사 관리.
향후 플랫폼 코어로 승격 가능하도록 API 경계 분리.
(OpsRamp/LogicMonitor 등 MSP 플랫폼 참고: 고객사 = 플랫폼 코어, 모니터링 = 모듈)

### 16-3. 멀티 클라우드

데이터 모델에 `provider` 필드 예약 (기본값: "aws").
UI 필터에 Cloud Provider 슬롯 예약. 지금은 AWS만.
