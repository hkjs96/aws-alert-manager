# AWS Monitoring Engine — 프로젝트 컨텍스트

## 1. 프로젝트 개요

AWS EC2/RDS/ELB 리소스에 대한 CloudWatch 알람 자동 생성·동기화·정리 엔진.
`Monitoring=on` 태그가 있는 리소스를 대상으로 동작하며, `Threshold_*` 태그로 임계치를 제어한다.

### 핵심 Lambda 2개
- **Daily Monitor**: 매일 00:00 UTC 실행. 모든 `Monitoring=on` 리소스 스캔 → 알람 생성/동기화/고아 알람 정리
- **Remediation Handler**: CloudTrail 이벤트(Modify/Delete/TagChange) 기반 실시간 반응

### 배포 방식
- 순수 CloudFormation (SAM 미사용), `template.yaml`
- Lambda Layer로 `common/` 모듈 공유
- S3에 zip 업로드 → CFN 스택 업데이트 (`CodeVersion` 파라미터 변경)
- AWS CLI SSO 프로필: `bjs` (리전: `ap-northeast-2`)

---

## 2. 디렉터리 구조

```
aws-alert-manager/
├── template.yaml                    # CloudFormation 템플릿
├── common/                          # Lambda Layer (공유 모듈)
│   ├── __init__.py                  # ResourceInfo, AlertMessage 등 TypedDict
│   ├── alarm_manager.py             # 알람 CRUD + sync (핵심)
│   ├── tag_resolver.py              # 임계치 조회 (태그→환경변수→하드코딩)
│   ├── sns_notifier.py              # SNS 알림 발송
│   └── collectors/
│       ├── base.py                  # CollectorProtocol + query_metric 공통
│       ├── ec2.py                   # EC2 수집/메트릭
│       ├── rds.py                   # RDS 수집/메트릭
│       └── elb.py                   # ALB/NLB/TG 수집/메트릭
├── daily_monitor/
│   └── lambda_handler.py            # Daily Monitor Lambda 진입점
├── remediation_handler/
│   └── lambda_handler.py            # Remediation Handler Lambda 진입점
├── tests/                           # pytest + hypothesis PBT
├── .kiro/
│   ├── steering/coding-governance.md # 코딩 거버넌스 규칙
│   └── specs/tag-driven-alarm-engine/ # 버그 수정 스펙 (완료)
├── DEPLOY.md                        # 배포 가이드
└── requirements.txt                 # 개발 의존성
```

---

## 3. 기술 스택

| 항목 | 값 |
|------|-----|
| Python | 3.12 (Lambda 런타임) |
| IaC | CloudFormation 2010-09-09 (순수 CFN) |
| boto3 | >=1.35.0 (Lambda 내장) |
| 테스트 | pytest >=9.0, hypothesis >=6.100, moto >=5.0 |
| 리전 | us-east-1 (Lambda), ap-northeast-2 (SSO/배포) |
| 브랜치 | feature/phase1 |
| 환경 | Windows git bash |

---

## 4. 리소스별 기본 알람 (하드코딩)

`Monitoring=on` 태그만 있으면 자동 생성되는 알람:

### EC2
| 메트릭 키 | CloudWatch MetricName | Namespace | 기본 임계치 |
|-----------|----------------------|-----------|-----------|
| CPU | CPUUtilization | AWS/EC2 | 80% |
| Memory | mem_used_percent | CWAgent | 80% |
| Disk | disk_used_percent | CWAgent | 80% (경로별) |

### RDS
| 메트릭 키 | CloudWatch MetricName | Namespace | 기본 임계치 |
|-----------|----------------------|-----------|-----------|
| CPU | CPUUtilization | AWS/RDS | 80% |
| FreeMemoryGB | FreeableMemory | AWS/RDS | 2GB (bytes 변환) |
| FreeStorageGB | FreeStorageSpace | AWS/RDS | 10GB (bytes 변환) |
| Connections | DatabaseConnections | AWS/RDS | 100 |

### ELB
| 메트릭 키 | CloudWatch MetricName | Namespace | 기본 임계치 |
|-----------|----------------------|-----------|-----------|
| RequestCount | RequestCount | AWS/ApplicationELB | 10000 |

---

## 5. 동적 태그 알람 (이번 스펙에서 추가)

`Threshold_{MetricName}={Value}` 태그를 달면 하드코딩 목록에 없는 메트릭도 알람 생성.

동작 흐름:
1. `_parse_threshold_tags()` → 하드코딩 목록에 없는 `Threshold_*` 태그 추출
2. `_resolve_metric_dimensions()` → `list_metrics` API로 Namespace/Dimensions 자동 해석
3. `_create_dynamic_alarm()` → 알람 생성

탐색 네임스페이스:
| 리소스 | 네임스페이스 | 디멘션 키 |
|--------|------------|----------|
| EC2 | AWS/EC2, CWAgent | InstanceId |
| RDS | AWS/RDS | DBInstanceIdentifier |
| ELB | AWS/ApplicationELB, AWS/NetworkELB | LoadBalancer |

조건: CloudWatch에 해당 메트릭 데이터가 실제 존재해야 `list_metrics`에서 해석 가능.

---

## 6. ELB/TG 현재 구현 상태

### ALB/NLB 구분 (Task 4.4에서 추가)
- `collect_monitored_resources()`에서 `lb.get("Type")` → `application` / `network` 구분
- `tags["_lb_type"]`에 저장하여 메트릭 조회 시 네임스페이스 분기
- ALB → `AWS/ApplicationELB`, NLB → `AWS/NetworkELB`

### TG (Target Group) 수집
- LB에 연결된 TG 중 `Monitoring=on` 태그 있는 것만 수집
- `ResourceInfo(type="TG")`, `tags["_lb_arn"]`, `tags["_lb_type"]`, `tags["_resource_subtype"]="TG"` 저장
- `get_metrics()`에서 TG 메트릭 조회 시 `TargetGroup` + `LoadBalancer` 2개 디멘션 사용

### 현재 한계 (TG 알람 미지원)
- `alarm_manager.py`의 `_get_alarm_defs()`에 TG용 하드코딩 알람 정의 없음
- `_DIMENSION_KEY_MAP`에 `"ELB": "LoadBalancer"`만 있고 TG용 매핑 없음
- 동적 알람도 `LoadBalancer` 단일 디멘션으로만 검색 → TG의 복합 디멘션(`TargetGroup` + `LoadBalancer`) 해석 불가
- 결론: LB 레벨 메트릭 수집/조회는 ALB/NLB 모두 동작하지만, TG 레벨 알람 자동 생성은 미구현

### ELB Collector 메트릭 수집 현황
| 타입 | 메트릭 | Stat | 네임스페이스 |
|------|--------|------|------------|
| ALB (LB 레벨) | RequestCount | Sum | AWS/ApplicationELB |
| NLB (LB 레벨) | ProcessedBytes, ActiveFlowCount, NewFlowCount | Sum/Avg | AWS/NetworkELB |
| TG (대상 그룹) | RequestCount, HealthyHostCount | Sum/Avg | LB 타입에 따라 분기 |

---

## 7. 알람 관리 핵심 함수 (alarm_manager.py)

| 함수 | 역할 |
|------|------|
| `create_alarms_for_resource()` | 전체 삭제 후 재생성 (하드코딩 + 동적) |
| `sync_alarms_for_resource()` | 메타데이터 기반 매칭 → 개별 업데이트 |
| `_parse_threshold_tags()` | 동적 메트릭 태그 파싱 |
| `_resolve_metric_dimensions()` | list_metrics API로 Namespace/Dimensions 해석 |
| `_create_dynamic_alarm()` | 동적 메트릭 알람 생성 |
| `_find_alarms_for_resource()` | resource_id prefix 기반 알람 검색 |
| `_describe_alarms_batch()` | 알람 정보 일괄 조회 (100개씩 배치) |
| `_sync_standard_alarms()` | CPU/Memory 등 표준 메트릭 동기화 |
| `_sync_disk_alarms()` | Disk 경로별 동기화 |
| `_apply_sync_changes()` | 동기화 결과 적용 (개별 재생성) |
| `_pretty_alarm_name()` | 알람 이름 생성 (255자 제한 + truncate) |
| `_build_alarm_description()` | AlarmDescription에 메타데이터 JSON 포함 |

---

## 8. 임계치 조회 우선순위 (tag_resolver.py)

1. 태그: `Threshold_{MetricName}` (예: `Threshold_CPU=90`)
2. 환경 변수: `DEFAULT_{METRIC}_THRESHOLD` (예: `DEFAULT_CPU_THRESHOLD=80`)
3. 하드코딩: `common/__init__.py`의 `HARDCODED_DEFAULTS`

Disk 계열은 `Threshold_Disk_root`, `Threshold_Disk_data` 등 경로별 태그 지원.
`disk_path_to_tag_suffix()` / `tag_suffix_to_disk_path()`로 경로↔태그 변환.

---

## 9. CloudFormation 스택 리소스

| 리소스 | 타입 | 설명 |
|--------|------|------|
| CommonLayer | Lambda::LayerVersion | common/ 모듈 공유 레이어 |
| DailyMonitorFunction | Lambda::Function | 일일 모니터링 |
| RemediationHandlerFunction | Lambda::Function | CloudTrail 이벤트 반응 |
| DailyMonitorSchedule | Scheduler::Schedule | 매일 00:00 UTC cron |
| CloudTrailModifyRule | Events::Rule | EC2/RDS/ELB 변경 이벤트 감지 |
| MonitoringAlertTopic | SNS::Topic | 임계치 초과 알림 |
| RemediationAlertTopic | SNS::Topic | Auto-Remediation 완료 |
| LifecycleAlertTopic | SNS::Topic | 리소스 생명주기 알림 |
| ErrorAlertTopic | SNS::Topic | 오류 알림 |
| InitialAlarmSync | CloudFormation::CustomResource | 스택 생성/업데이트 시 Daily Monitor 1회 실행 |

---

## 10. 코딩 거버넌스 요약

- boto3 클라이언트: `@functools.lru_cache(maxsize=None)` 싱글턴
- import: 파일 상단, stdlib → 서드파티 → 프로젝트 내부
- 에러: `ClientError`만 catch, `except Exception` 금지
- 함수 복잡도: 로컬변수 15개, statements 50개, branches 12개, 인자 5개 이하
- 알람 이름: 255자 제한, 메타데이터 매칭, prefix 검색
- 테스트: TDD (레드-그린-리팩터링), moto + hypothesis PBT
- 로깅: `logger.error("메시지: %s", e)` (f-string 금지)

---

## 11. 현재 git 상태

- 브랜치: `feature/phase1`
- tag-driven-alarm-engine 버그 수정 스펙 6개 태스크 완료 (미커밋)
- 전체 테스트: 257 passed, 0 failed
