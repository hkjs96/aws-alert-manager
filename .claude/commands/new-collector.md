# /new-collector — 새 리소스 타입 추가 워크플로

> 원본: `.kiro/hooks/new-collector-checklist.kiro.hook` (fileCreated) + `.kiro/steering/resource-checklist.md` §11

새 AWS 리소스 타입을 모니터링 대상에 추가할 때 이 커맨드를 사용한다.
$ARGUMENTS에 리소스 타입 이름을 전달한다 (예: `/new-collector Lambda`).

---

## §11 체크리스트 — 모든 항목을 순서대로 확인하며 진행

### 11-1. 메트릭 및 디멘션 확인
- AWS CloudWatch 공식 문서에서 해당 리소스의 메트릭 목록, 네임스페이스, 디멘션을 확인한다.
- LB 레벨 vs TG 레벨 등 디멘션 계층이 있는 경우 구분한다 (§6-1).
- CWAgent 등 커스텀 에이전트 메트릭 필요 여부를 확인한다.

### 11-2. CloudTrail 이벤트 등록 (3개 레이어)
1. `common/__init__.py` → `MONITORED_API_EVENTS`에 CREATE/MODIFY/DELETE/TAG_CHANGE 추가
2. `template.yaml` → `CloudTrailModifyRule` EventPattern `detail.eventName`에 추가
3. `remediation_handler/lambda_handler.py` → `_API_MAP`에 매핑 추가

### 11-3. 하드코딩 알람 정의
- `common/alarm_manager.py`의 `_*_ALARMS`에 필수 메트릭 추가
- `common/__init__.py`의 `HARDCODED_DEFAULTS`에 기본 임계치 추가
- `common/__init__.py`의 `SUPPORTED_RESOURCE_TYPES`에 등록

### 11-4. 동적 알람 네임스페이스 등록
- `_NAMESPACE_SEARCH_MAP`에 해당 리소스의 탐색 네임스페이스를 등록

### 11-5. 단위 환산 검토
- 메모리(bytes→GB), 스토리지 등 사용자 친화적 단위로 변환이 필요한지 확인
- 필요 시 `multiplier` 필드 + `metric_key`/`display_metric`/`unit` 조정

### 11-6. Collector 구현 + 등록
- `common/collectors/{type}_collector.py` 생성 (CollectorProtocol 구현)
  - `collect_monitored_resources()`
  - `get_metrics()`
  - `resolve_alive_ids()` (§5-1: 역매핑 필요 여부 확인)
- `daily_monitor/lambda_handler.py`의 `_COLLECTOR_MODULES`에 등록
- `_RESOURCE_TYPE_TO_COLLECTOR`에 매핑 (alias 포함)

### 11-7. SRE 골든 시그널 커버리지 검토
| 시그널 | 검토 |
|--------|------|
| Latency | 사용자 체감 응답 시간 |
| Traffic | 전체 처리량 (Count/Bytes) |
| Errors | 서비스 중단 직결 에러 |
| Saturation | CPU/메모리/스토리지 |

시그널별 최소 1개 하드코딩 메트릭 선정, 나머지는 동적 알람으로 커버.

### 11-8. 인스턴스 변형별 메트릭 가용성
- 인스턴스 클래스/역할에 따라 발행 메트릭이 다른지 확인
- 차이가 있으면 `_get_alarm_defs()`에서 `resource_tags` 기반 조건부 분기

### 11-9. 퍼센트 기반 임계치 검토
- 절대값 메트릭(FreeableMemory 등)에 퍼센트가 적합한지 판단
- 적합하면 `_INSTANCE_CLASS_MEMORY_MAP` + `_resolve_free_memory_threshold()` 패턴 참고

### 11-10. E2E 테스트 인프라 cleanup
- Backup Vault, S3, ECR 등 내부 데이터가 남는 리소스는 CustomResource Lambda 추가

### 11-10 (추가). Container Insights 의존 메트릭
- ECS/EKS에서 Container Insights 전용 메트릭인지 확인

---

## 완료 조건

- 위 체크리스트 11개 항목 모두 확인/구현
- `pytest tests/ -x -q --tb=short` 통과
- 기존 알람 동기화에 영향 없음 확인
