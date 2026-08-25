# /new-collector resource onboarding checklist

Use this command when adding a backend-supported AWS resource type.
(구 `.kiro/steering/resource-checklist.md` 전문 병합본 — 이 파일이 SSOT)

## Collector 인터페이스 (§5)

새 Collector는 `common/collectors/base.py`의 `CollectorProtocol`을 구현한다. 필수 메서드:

- `collect_monitored_resources() -> list[ResourceInfo]`
- `get_metrics(resource_id: str, resource_tags: dict) -> dict[str, float] | None`
- `resolve_alive_ids(tag_names: set[str]) -> set[str]`

메트릭 조회는 `common/collectors/base.py`의 공통 `query_metric()` 유틸리티를 사용한다.

### resolve_alive_ids 구현 규칙 (§5-1)

- 각 Collector가 자기 리소스의 alive 체크를 직접 담당한다. `daily_monitor/lambda_handler.py`에
  alive 체크 로직을 하드코딩하지 않는다 (AGENTS.md AP-8).
- 입력: 알람 TagName 집합 (알람 이름의 `(TagName: ...)` 부분에서 추출된 값).
  출력: 실제 AWS 리소스가 존재하는 TagName 부분집합.
- TagName은 `_shorten_elb_resource_id()`가 생성한 short ID 형식이므로, collector가 원본
  리소스 식별자로 **역매핑**해야 한다:
  - MQ: `{broker_name}-{1|2}` → suffix 제거 후 broker name으로 조회
  - APIGW HTTP/WS: `{api_name}/{api_id}` → split 후 api_id로 조회
  - ACM: 도메인명 → `list_certificates` + `describe_certificate`로 도메인 매칭
  - ALB/NLB/TG: short ID (`{name}/{hash}`) → ARN이 아닌 경우 보수적으로 alive 처리
  - 역매핑 불필요 (TagName == resource_id): EC2, RDS, CLB, ElastiCache, NAT, Lambda, VPN,
    Backup, OpenSearch, DocDB
- 에러 처리: `ClientError`만 catch, 기존 collector의 boto3 클라이언트 싱글턴 재사용.

## Required Updates

1. **메트릭/디멘션 확인 (AWS 공식 문서 필수):** 메트릭 목록·네임스페이스·디멘션을 확인한다.
   LB 레벨 vs TG 레벨 등 디멘션 계층 구분 필수 (`docs/ALARM-RULES.md` §6-1).
   CWAgent 등 커스텀 에이전트 네임스페이스는 별도 확인.
2. **CloudTrail 이벤트 (생명주기):** CREATE/MODIFY/DELETE/TAG_CHANGE API를 확인하고 3곳에 등록:
   - `backend/common/__init__.py::MONITORED_API_EVENTS`
   - `infrastructure/backend/template.yaml` CloudTrail EventPattern `detail.eventName`
   - `backend/remediation_handler/lambda_handler.py::_API_MAP` (resource_type, id_extractor)
   - CREATE 이벤트는 `responseElements`에서 ID를 추출하는 경우가 많으므로 주의.
   - ARN → 리소스 ID 변환이 필요한 타입은 `docs/ALARM-RULES.md` §9 매핑을 갱신.
3. **필수 알람 자동 생성 (Monitoring=on):**
   - `backend/common/alarm_registry.py`의 `_*_ALARMS` 정의 + `_get_alarm_defs()` 분기
   - `_HARDCODED_METRIC_KEYS`, `_NAMESPACE_MAP`, `_DIMENSION_KEY_MAP`, `_METRIC_DISPLAY`,
     `_metric_name_to_key`
   - `backend/common/__init__.py::HARDCODED_DEFAULTS` 기본 임계치
   - `backend/common/__init__.py::SUPPORTED_RESOURCE_TYPES`
4. **태그 기반 임계치:** `Threshold_{MetricName}` 태그 suffix가 알람 정의 `metric_key`와 매칭돼야
   한다. 동적 알람용 탐색 네임스페이스를 `_NAMESPACE_SEARCH_MAP`에 등록.
   우선순위: 태그 → 환경 변수(`DEFAULT_{METRIC}_THRESHOLD`) → `HARDCODED_DEFAULTS`.
5. **단위 환산 검토:** bytes 메트릭(FreeableMemory 등)은 GB 단위 `metric_key` + `multiplier`
   (GB→bytes: 1073741824)로 환산하고, 알람 이름의 `display_metric`/`unit`도 환산 단위로 표시.
6. **Collector 구현:** `backend/common/collectors/` 하위에 모듈 추가 후
   - `daily_monitor/lambda_handler.py::_COLLECTOR_MODULES` 리스트에 등록
   - `daily_monitor/lambda_handler.py::_RESOURCE_TYPE_TO_COLLECTOR`에 매핑 추가
     (alias 포함 — 예: `AuroraRDS` → rds, `NATGateway` → natgw)
   - TagName ≠ resource_id인 타입은 `resolve_alive_ids` 역매핑 필수 (§5-1)
7. **테스트:** `backend/tests/` 하위에 추가.
8. **프론트엔드 노출 시:**
   - `frontend/lib/constants.ts`, `frontend/types`
   - `docs/API-CONTRACT.md`, `docs/DATA-MODEL.md`, `docs/API-WORKFLOWS.md`

## 설계 검토 항목

### SRE 골든 시그널 기반 메트릭 선정 (§11-7, 필수)

시그널별 최소 1개 이상의 하드코딩 메트릭이 있는지 확인하고 판단 근거를 기록한다:

| 시그널 | 하드코딩 기준 | 동적 알람 후보 |
|--------|-------------|---------------|
| Latency | 사용자 체감 직결 (예: TargetResponseTime) | 워크로드별 차이가 큰 메트릭 |
| Traffic | 과부하 감지용 (예: RequestCount) | 급증/급감 감지 세부 메트릭 |
| Errors | 가용성 직결 (예: 5XX, StatusCheckFailed) | 앱 레벨 에러 (Deadlocks 등) |
| Saturation | CPU, 메모리, 스토리지, 연결 수 | I/O 병목 (DiskQueueDepth) 등 |

- 비교 방향 명시: "높을수록 위험" `GreaterThanThreshold` / "낮을수록 위험" `LessThanThreshold`
  (동적 알람은 `Threshold_LT_` prefix 안내).

### 인스턴스 변형별 메트릭 가용성 (§11-8)

- 클래스별 차이 (예: Aurora Serverless v2는 `FreeLocalStorage` 미발행 — KI-006)
- 역할별 차이 (예: Aurora Writer만 `AuroraReplicaLagMaximum` — KI-007)
- 확인된 차이는 `_get_alarm_defs()`에서 `resource_tags` 기반 조건부 분기로 처리하고
  E2E 테스트로 검증한다.

### 퍼센트 기반 임계치 (§11-9)

절대값 메트릭(FreeableMemory 등)이 인스턴스 사양에 따라 의미가 달라지면:
1. Collector에서 `_total_{resource}_bytes` 내부 태그 설정
2. `_INSTANCE_CLASS_MEMORY_MAP` 등 lookup 테이블에 클래스 추가
3. `_resolve_free_memory_threshold()` 패턴으로 퍼센트 해석 로직 구현
- Serverless/Auto-scaling은 퍼센트 부적합할 수 있음 (ACUUtilization 등 대체 메트릭 사용).

### Container Insights 의존 메트릭 (ECS/EKS)

`RunningTaskCount`/`NetworkRx/TxBytes`는 `ECS/ContainerInsights` 네임스페이스 전용 —
Container Insights 미활성 시 영구 INSUFFICIENT_DATA. 현재 ECS 하드코딩 알람은 `AWS/ECS`의
CPU/Memory만 포함하며, RunningTaskCount는 동적 알람 태그로 사용 가능.

### E2E 테스트 인프라 정리 (§11-10)

스택 삭제 시 내부 데이터가 남으면 `DELETE_FAILED`: Backup Vault(recovery point),
S3(객체), ECR(이미지)는 cleanup CustomResource를 추가하고, Delete 핸들러는 에러 시에도
`SUCCESS`를 반환해 스택 삭제를 블로킹하지 않는다. OpenSearch는 삭제에 10~15분 소요.

## Verification

```bash
cd backend && pytest tests/ -x -q --tb=short
```

Do not expose a new resource type in frontend filters or settings until the
frontend API contract, DTO mapping, and tests are complete for that type.
