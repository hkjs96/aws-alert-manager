# 구현 계획

- [x] 1. 버그 조건 탐색 테스트 작성 (수정 전 코드에서 실행)
  - **Property 1: Bug Condition** - 하드코딩 목록 외 Threshold 태그 알람 미생성
  - **CRITICAL**: 이 테스트는 수정 전 코드에서 반드시 FAIL해야 한다 — 실패가 버그 존재를 확인하는 것이다
  - **DO NOT**: 테스트가 실패할 때 테스트나 코드를 수정하지 말 것
  - **NOTE**: 이 테스트는 기대 동작을 인코딩한다 — 수정 후 PASS하면 버그가 해결된 것이다
  - **GOAL**: 버그 존재를 증명하는 반례(counterexample)를 확인한다
  - **Scoped PBT Approach**: `Threshold_NetworkIn`, `Threshold_ReadLatency` 등 하드코딩 목록에 없는 메트릭 태그를 가진 리소스에 대해 `create_alarms_for_resource()` 호출
  - 테스트 파일: `tests/test_pbt_dynamic_alarm_fault.py`
  - hypothesis 전략: resource_type ∈ {EC2, RDS, ELB}, 하드코딩 목록에 없는 메트릭 이름 생성, 양의 숫자 임계치 생성
  - moto로 CloudWatch에 해당 메트릭 데이터를 등록한 후 `create_alarms_for_resource()` 호출
  - 버그 조건 (design.md isBugCondition): `threshold_tags`에서 `hardcoded_metrics`를 뺀 `extra_metrics`가 1개 이상
  - 기대 동작 (design.md expectedBehavior): 동적 메트릭에 대한 알람이 `result`에 포함되어야 함
  - 수정 전 코드에서 실행 → **FAIL 예상** (동적 메트릭 알람이 생성되지 않음을 확인)
  - 반례 문서화: `create_alarms_for_resource()` 반환값에 동적 메트릭 알람이 포함되지 않음
  - 테스트 작성, 실행, 실패 문서화 완료 시 태스크 완료 처리
  - _Requirements: 1.1, 1.2, 2.1, 2.2_

- [x] 2. 보존 속성 테스트 작성 (수정 전 코드에서 실행)
  - **Property 2: Preservation** - 기존 하드코딩 메트릭 알람 생성 보존
  - **IMPORTANT**: 관찰 우선(observation-first) 방법론을 따른다
  - 테스트 파일: `tests/test_pbt_dynamic_alarm_preservation.py`
  - 관찰: 수정 전 코드에서 하드코딩 메트릭만 포함하는 태그 조합으로 `create_alarms_for_resource()` 호출 시 알람 이름, 네임스페이스, 디멘션, 임계치 확인
  - 관찰: EC2 {CPU, Memory, Disk} → 3개 알람, RDS {CPU, FreeMemoryGB, FreeStorageGB, Connections} → 4개 알람, ELB {RequestCount} → 1개 알람
  - 관찰: RDS FreeMemoryGB/FreeStorageGB 임계치는 GB→bytes 변환 적용
  - 관찰: 알람 이름 포맷 `[{resource_type}] {label} {display_metric} {direction}{threshold}{unit} ({resource_id})` 유지
  - 관찰: 임계치 3단계 폴백 (태그→환경변수→HARDCODED_DEFAULTS) 우선순위 유지
  - hypothesis 전략: resource_type ∈ {EC2, RDS, ELB}, 하드코딩 메트릭만 포함하는 태그 조합, 양의 숫자 임계치
  - moto로 CloudWatch 메트릭 등록 후 `create_alarms_for_resource()` 호출
  - 보존 조건: `isBugCondition(input) == False` — 하드코딩 목록에 있는 메트릭만 포함
  - property-based test: 모든 비버그 입력에 대해 알람 개수, 이름 포맷, 임계치, 네임스페이스가 기대값과 일치
  - 수정 전 코드에서 실행 → **PASS 예상** (기존 동작이 정상임을 확인)
  - 테스트 작성, 실행, PASS 확인 완료 시 태스크 완료 처리
  - _Requirements: 3.1, 3.2, 3.6, 3.7, 3.8_

- [x] 3. 인프라/기반 변경 (base.py, boto3 패턴 통일)

  - [x] 3.1 `common/collectors/base.py` 신규 생성 — CollectorProtocol + query_metric 공통화
    - `CollectorProtocol` (typing.Protocol) 정의: `collect_monitored_resources() -> list[ResourceInfo]`, `get_metrics(resource_id: str, resource_tags: dict) -> dict[str, float] | None`
    - `query_metric()` 공통 유틸리티: CloudWatch `get_metric_statistics` 래퍼 (기존 ec2/rds/elb의 `_query_metric` 통합)
    - `@functools.lru_cache(maxsize=None)` 기반 `_get_cw_client()` 포함
    - 코딩 거버넌스 §1 (lru_cache boto3), §5 (Collector 인터페이스), §10 (코드 중복 금지) 준수
    - _Bug_Condition: 변경 7 — Collector 코드 중복 제거_
    - _Requirements: 1.10, 1.11, 2.10, 2.11_

  - [x] 3.2 `common/alarm_manager.py` — boto3 클라이언트 `lru_cache` 전환
    - `global _cw_client` + `global` statement 제거
    - `import functools` 추가, `@functools.lru_cache(maxsize=None)` 데코레이터 적용
    - 코딩 거버넌스 §1 (lru_cache boto3) 준수
    - _Bug_Condition: 변경 1 — boto3 클라이언트 패턴 통일_
    - _Requirements: 1.8, 2.8_

  - [x] 3.3 Collector 모듈 공통 유틸리티 전환 (ec2.py, rds.py, elb.py)
    - 각 모듈의 `_query_metric()` 삭제, `from common.collectors.base import query_metric` 사용
    - `boto3.client()` 직접 생성 → `@functools.lru_cache` 싱글턴 또는 `base._get_cw_client()` 사용
    - 코딩 거버넌스 §1, §2 (import 규칙), §5, §10 준수
    - _Bug_Condition: 변경 8 — Collector 공통 유틸리티 사용_
    - _Requirements: 1.10, 2.10_

  - [x] 3.4 `common/tag_resolver.py` — boto3 클라이언트 `lru_cache` 전환
    - `boto3.client()` 직접 생성 → `@functools.lru_cache` 싱글턴 패턴
    - 코딩 거버넌스 §1 준수
    - _Bug_Condition: 변경 10 — tag_resolver boto3 패턴 통일_
    - _Requirements: 1.8, 2.8_

  - [x] 3.5 `remediation_handler/lambda_handler.py` — 지연 import 제거 + 중복 코드 추출
    - `from common.alarm_manager import ...` 6건의 지연 import를 파일 상단으로 이동
    - `_remove_monitoring()` 헬퍼 추출: 알람 삭제 + lifecycle 알림 발송 공통 로직
    - 코딩 거버넌스 §2 (import 규칙), §10 (코드 중복 금지) 준수
    - _Bug_Condition: 변경 11 — 지연 import 제거 + 중복 코드 추출_
    - _Requirements: 1.9, 2.9_

- [x] 4. 핵심 기능 변경 (동적 파싱, 디멘션 해석, 메타데이터 매칭)

  - [x] 4.1 `alarm_manager.py` — 태그 동적 파싱 + 디멘션 자동 해석
    - `_parse_threshold_tags(resource_tags, resource_type)` 헬퍼 추가: `Threshold_*` 태그에서 하드코딩 목록에 없는 메트릭 추출
    - 태그 키 유효성 검증: `Threshold_` + 1자 이상 메트릭 이름, 128자 이하, 태그 허용 문자만 포함
    - 태그 값 유효성 검증: 양의 숫자로 파싱 가능 (기존 `get_threshold()` 로직 재사용)
    - `Threshold_Disk_*` 패턴은 기존 Disk 알람 로직에서 처리하므로 동적 파싱에서 제외
    - `_resolve_metric_dimensions(resource_id, metric_name, resource_type)` 헬퍼 추가: `list_metrics` API로 네임스페이스/디멘션 자동 해석
    - resource_type별 기본 네임스페이스 매핑 (EC2→AWS/EC2+CWAgent, RDS→AWS/RDS, ELB→AWS/ApplicationELB+AWS/NetworkELB)
    - `create_alarms_for_resource()`에서 하드코딩 알람 생성 후 동적 태그 알람도 생성
    - 코딩 거버넌스 §3 (함수 복잡도), §4 (ClientError만 catch), §7 (태그 기반 동적 알람) 준수
    - _Bug_Condition: isBugCondition(input) where extra_metrics > 0_
    - _Expected_Behavior: 동적 메트릭에 대한 알람이 list_metrics 해석된 Namespace/Dimensions로 생성_
    - _Preservation: 하드코딩 메트릭 알람은 기존과 동일하게 생성_
    - _Requirements: 1.1, 1.2, 2.1, 2.2, 3.1_

  - [x] 4.2 `alarm_manager.py` — 알람 이름 255자 제한 준수 + 검색 prefix 통일
    - `_pretty_alarm_name()`에 255자 truncate 로직 추가: label → display_metric 순으로 truncate (`...` 접미사)
    - resource_id 부분은 알람 검색/매칭에 필수이므로 절대 truncate하지 않음
    - `_find_alarms_for_resource()`를 `AlarmNamePrefix=resource_id` 단일 검색으로 단순화 (O(N) 풀스캔 제거)
    - 레거시 알람 호환을 위해 기존 prefix 검색도 유지
    - `except Exception` 2건을 `except ClientError`로 변경
    - 코딩 거버넌스 §4 (ClientError만 catch), §6 (알람 이름 255자, prefix 검색) 준수
    - _Bug_Condition: 변경 3, 6 — 알람 이름 제한 + 풀스캔 제거_
    - _Requirements: 1.3, 2.3_

  - [x] 4.3 `alarm_manager.py` — 메타데이터 기반 알람 매칭 + 함수 분리
    - `AlarmDescription`에 메트릭 키를 JSON 형태로 저장: `{"metric_key": "CPU", "resource_id": "i-xxx"}`
    - `sync_alarms_for_resource()`에서 `describe_alarms` 1회 호출 후 메타데이터 기반 매칭
    - 이름 문자열 매칭(`display in a`) 로직 제거
    - `_create_disk_alarms()`, `_create_standard_alarm()`, `_create_dynamic_alarm()` 함수 분리
    - `_sync_disk_alarms()`, `_sync_standard_alarms()` 함수 분리
    - 코딩 거버넌스 §3 (로컬 변수 15개, statements 50개, branches 12개), §6 (메타데이터 매칭) 준수
    - _Bug_Condition: 변경 4, 5 — 메타데이터 매칭 + 함수 분리_
    - _Requirements: 1.4, 1.6, 1.7, 1.13, 2.4, 2.6, 2.7, 2.13_

  - [x] 4.4 `common/collectors/elb.py` — NLB 지원 추가
    - `collect_monitored_resources()`에서 LoadBalancer Type 확인 (ALB/NLB)
    - NLB인 경우 `AWS/NetworkELB` 네임스페이스 사용
    - `get_metrics()`에서 lb_type에 따라 네임스페이스 분기
    - 코딩 거버넌스 §5 (Collector 인터페이스) 준수
    - _Bug_Condition: 변경 9 — NLB 지원 추가_
    - _Requirements: 1.12, 2.12_

  - [x] 4.5 `daily_monitor/lambda_handler.py` — 고아 알람 확장 + 지연 import 정리
    - `_cleanup_orphan_alarms()`에서 EC2 외 RDS/ELB 고아 알람도 정리
    - `_cleanup_orphan_alarms()` 내부의 `import boto3`, `import re` 지연 import를 파일 상단으로 이동
    - boto3 클라이언트 `@lru_cache` 싱글턴 패턴 적용
    - 코딩 거버넌스 §1, §2 준수
    - _Bug_Condition: 변경 12 — 고아 알람 확장_
    - _Requirements: 1.5, 2.5_

  - [x] 4.6 기존 단위 테스트 업데이트
    - `tests/test_alarm_manager.py`: `_reset_cw_client` 픽스처를 `lru_cache.cache_clear()` 방식으로 변경
    - 새 함수(`_parse_threshold_tags`, `_resolve_metric_dimensions`, `_create_dynamic_alarm` 등) 단위 테스트 추가
    - `tests/test_collectors.py`: `base.query_metric()` 사용으로 변경된 부분 반영
    - `tests/test_remediation_handler.py`: 지연 import 제거에 따른 패치 경로 업데이트
    - `tests/test_daily_monitor.py`: 고아 알람 확장에 따른 테스트 추가
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10, 2.11, 2.12, 2.13_

- [x] 5. 수정 후 검증

  - [x] 5.1 버그 조건 탐색 테스트 재실행 — 수정 확인
    - **Property 1: Expected Behavior** - 하드코딩 목록 외 Threshold 태그 알람 생성 확인
    - **IMPORTANT**: 태스크 1에서 작성한 동일한 테스트를 재실행한다 — 새 테스트를 작성하지 말 것
    - 태스크 1의 테스트가 기대 동작을 인코딩하고 있음
    - 이 테스트가 PASS하면 기대 동작이 충족된 것이다
    - `tests/test_pbt_dynamic_alarm_fault.py` 실행
    - **PASS 예상** (동적 메트릭 알람이 정상 생성됨을 확인)
    - _Requirements: 2.1, 2.2_

  - [x] 5.2 보존 속성 테스트 재실행 — 회귀 없음 확인
    - **Property 2: Preservation** - 기존 하드코딩 메트릭 알람 생성 보존
    - **IMPORTANT**: 태스크 2에서 작성한 동일한 테스트를 재실행한다 — 새 테스트를 작성하지 말 것
    - `tests/test_pbt_dynamic_alarm_preservation.py` 실행
    - **PASS 예상** (기존 동작이 수정 후에도 보존됨을 확인)
    - _Requirements: 3.1, 3.2, 3.6, 3.7, 3.8_

  - [x] 5.3 추가 정합성 속성 테스트 작성 및 실행
    - Property 3 (design.md): 메타데이터 기반 알람 매칭 — `sync_alarms_for_resource()`가 Namespace/MetricName/Dimensions로 매칭
    - Property 4 (design.md): 알람 검색 효율성 — prefix 기반 검색이 풀스캔과 동일 결과
    - Property 5 (design.md): 알람 이름 255자 제한 — `_pretty_alarm_name()`이 항상 255자 이하 반환
    - Property 6 (design.md): 태그 키/값 유효성 — `_parse_threshold_tags()`가 유효하지 않은 태그 skip
    - 테스트 파일: `tests/test_pbt_alarm_metadata_match.py`, `tests/test_pbt_alarm_name_constraint.py` 등
    - _Requirements: 2.3, 2.4, 2.13_

- [x] 6. 체크포인트 — 전체 테스트 통과 확인
  - 전체 테스트 스위트 실행: `pytest tests/ -v`
  - 모든 PBT 테스트 PASS 확인
  - 모든 기존 단위/통합 테스트 PASS 확인
  - 질문이 있으면 사용자에게 확인
