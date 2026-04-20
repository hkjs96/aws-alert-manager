# Phase2 UI 설계 결정 사항

> 알람 매니징 웹앱 설계 과정에서 결정된 사항 정리.
> Stitch 프롬프트 파일과 함께 참고.

## 1. 범위 구분

### 1번: 알람 매니징 (지금)
- 알람 CRUD (생성/수정/삭제) 자동화
- 리소스 조회/필터링, 벌크 설정
- 고객사별 기본 임계치 정의
- 알람 동기화/드리프트 감지
- 알림: 고객사 사이트에 AWS Chatbot → Slack (기존 구축)
- xlsx 임포트, 템플릿, 감사 로그
- 뮤트 규칙 (CloudWatch Alarm Mute Rules)
- 커버리지 리포트

### 2번: 24x7 관제 (나중)
- 알람 이벤트 수집 파이프라인
- 알림 채널 등록/관리/라우팅
- 알람 등급(Severity) 변경 UI
- 에스컬레이션 체인
- 인시던트 관리, Acknowledge
- 실시간 알람 피드

## 2. 1번에서 2번을 위해 미리 깔아둘 것

### 2-1. Severity 기본값 (alarm_registry.py)

`_DEFAULT_SEVERITY` dict 추가. 업계 표준 SEV-1~5 체계 채택 (PagerDuty/ITIL 참고).

```python
_DEFAULT_SEVERITY = {
    # SEV-1 Critical: 서비스 완전 중단/접근 불가
    "StatusCheckFailed": "SEV-1",
    "HealthyHostCount": "SEV-1",
    "TunnelState": "SEV-1",
    "ClusterStatusRed": "SEV-1",
    "ConnectionState": "SEV-1",
    "HealthCheckStatus": "SEV-1",
    
    # SEV-2 High: 에러 급증, 서비스 품질 심각 저하
    "ELB5XX": "SEV-2", "CLB5XX": "SEV-2",
    "Errors": "SEV-2", "UnHealthyHostCount": "SEV-2",
    
    # SEV-3 Medium: 리소스 포화 근접
    "CPU": "SEV-3", "Memory": "SEV-3", "Disk": "SEV-3",
    "FreeMemoryGB": "SEV-3", "FreeStorageGB": "SEV-3",
    "FreeLocalStorageGB": "SEV-3", "EngineCPU": "SEV-3",
    "ACUUtilization": "SEV-3", "DaysToExpiry": "SEV-3",
    
    # SEV-4 Low: 성능 저하
    "ReadLatency": "SEV-4", "WriteLatency": "SEV-4",
    "TargetResponseTime": "SEV-4", "Duration": "SEV-4",
    
    # SEV-5 Info: 트래픽/용량 참고
    "RequestCount": "SEV-5", "Connections": "SEV-5",
    "ProcessedBytes": "SEV-5", "ActiveFlowCount": "SEV-5",
    # ... 나머지 메트릭은 기본 SEV-5
}
```

기본 등급은 고객사별/리소스별 오버라이드 가능 (Phase2 DB 도입 후).

### 2-2. Severity 저장: CloudWatch 알람 태그

AlarmDescription이 아닌 CloudWatch 알람 태그(Tags)에 Severity 저장.

```python
# 알람 생성 시
cw.put_metric_alarm(AlarmName=name, ...)
cw.tag_resource(
    ResourceARN=f"arn:aws:cloudwatch:{region}:{account}:alarm:{name}",
    Tags=[
        {"Key": "Severity", "Value": severity},
        {"Key": "ManagedBy", "Value": "AlarmManager"},
    ]
)

# severity 변경 시 (알람 재생성 없음)
cw.tag_resource(
    ResourceARN=alarm_arn,
    Tags=[{"Key": "Severity", "Value": new_severity}]
)
```

선택 이유:
- 변경 시 tag_resource만 호출 (알람 재생성/PutMetricAlarm 불필요)
- DescribeAlarms + list_tags_for_resource로 조회 가능
- CloudWatch 네이티브, 별도 인프라 없음
- 2번에서 DB 도입 시 DB가 Source of Truth, 알람 태그는 sync


### 2-3. AlarmDescription 메타데이터

기존 구조 유지. Severity는 넣지 않음 (태그로 분리).

```json
{
  "resource_id": "i-abc123",
  "resource_type": "EC2",
  "metric_key": "CPU",
  "customer_id": "acme-corp",
  "account_id": "123456789012"
}
```

customer_id, account_id는 멀티어카운트 확장 시 추가.

### 2-4. 고객사 데이터 모델

1번에서는 Settings 내 경량 고객사 관리. 나중에 플랫폼 코어로 승격 가능하도록 API 경계 분리.

### 2-5. UI에서 Severity 표시

1번: 읽기 전용 뱃지 (시스템 기본값 표시만, 변경 불가)
2번: 드롭다운으로 변경 가능 (DB + 알람 태그 동시 업데이트)

## 3. 서비스 스위칭 패턴

상단 서비스 스위처 (패턴 C) 채택.
- 현재: "Alarm Manager" 단독 앱
- 향후: 서비스 스위처 드롭다운으로 24x7 Monitoring, FinOps 등 추가
- 글로벌 필터(고객사/어카운트)는 서비스 간 공유

## 4. 멀티 클라우드 확장성

데이터 모델에 `provider` 필드 예약 (기본값: "aws").
UI 필터에 Cloud Provider 슬롯 예약. 지금은 AWS만.

## 5. 알림 흐름 (1번 vs 2번)

```
1번 (지금):
  CloudWatch ALARM → SNS → AWS Chatbot → Slack (고객사별)
  (기존 구축된 파이프라인 그대로 사용)

2번 (나중):
  CloudWatch ALARM → SNS → Lambda(알림 라우터)
  → 알람 태그에서 Severity 조회
  → DB에서 라우팅 규칙 매칭
  → 채널별 분기 (Slack/PagerDuty/Email/Webhook)
```

## 6. Stitch 프롬프트 파일

| 파일 | 설명 |
|------|------|
| `docs/stitch-prompts-en.md` | 영어판 페이지별 프롬프트 (0~11) |
| `docs/stitch-prompts-ko.md` | 한글판 페이지별 프롬프트 (0~11) |
| `docs/stitch-prompt-alarm-webapp.md` | 전체 앱 요약 프롬프트 (단일 파일) |
| `docs/stitch-prompt-iep-alarm-management.md` | IEP 풀버전 프롬프트 (참고용) |

## 7. 프롬프트 조정 필요 사항

현재 프롬프트에서 2번 영역이 포함된 부분:
- Notification Routing 페이지 → 1번에서는 제거 또는 "Coming Soon" 처리
- Severity 드롭다운 오버라이드 → 1번에서는 읽기 전용 뱃지로
- 고객사 온보딩 Severity 컬럼 → 1번에서는 제거 (시스템 기본값만)
- 에스컬레이션 설정 → 1번에서는 제거

1번에서 유지할 것:
- Severity 읽기 전용 뱃지 (테이블, 필터)
- 뮤트 규칙 (CloudWatch 네이티브)
- 커버리지 리포트
- 동기화 상태/드리프트
- 감사 로그
