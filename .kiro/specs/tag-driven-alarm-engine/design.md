# 태그 기반 동적 알람 엔진 버그 수정 설계

## 개요

AWS 모니터링 엔진의 알람 관리 시스템에 13개의 결함이 존재한다. 핵심 결함은 `Threshold_{MetricName}` 태그를 동적으로 파싱하지 못해 하드코딩 목록 외 메트릭의 알람이 생성되지 않는 것이다. 이 외에도 O(N) 풀스캔 성능 문제, 중복 API 호출, 이름 문자열 기반 알람 매칭, 함수 복잡도 초과, boto3 클라이언트 패턴 불일치, Collector 코드 중복 등이 포함된다.

수정 전략은 다음과 같다:
1. `alarm_manager.py`를 리팩터링하여 태그 동적 파싱 + `list_metrics` 기반 디멘션 해석 추가
2. 알람 검색을 prefix 기반으로 통일하고 메타데이터 기반 매칭으로 전환
3. 함수 분리로 복잡도 준수
4. `common/collectors/base.py`에 `CollectorProtocol` + `query_metric()` 공통 유틸리티 추출
5. 모든 모듈에서 `functools.lru_cache` 기반 boto3 싱글턴 패턴 통일

## AWS 서비스 제약 사항

### CloudWatch Alarm
| 항목 | 제한 |
|------|------|
| AlarmName | 1~255자 (ASCII) |
| AlarmDescription | 0~1024자 |
| Dimensions | 최대 30개 |
| AlarmActions | 최대 5개 |

### AWS 리소스 태그
| 항목 | 제한 |
|------|------|
| 태그 키 | 1~128자 (UTF-8) |
| 태그 값 | 0~256자 (UTF-8) |
| 리소스당 태그 수 | 최대 50개 (사용자 정의) |
| 허용 문자 | 문자, 숫자, 공백, `_ . : / = + - @` |
| 예약 접두사 | `aws:` (사용자 생성/수정 불가) |
| 대소문자 | 구분함 (`CostCenter` ≠ `costcenter`) |

### 설계 영향 분석

**알람 이름 255자 제한**:
현재 포맷 `[{resource_type}] {label} {display_metric} {direction}{threshold}{unit} ({resource_id})`에서 최악의 경우를 계산하면:
- `[EC2]` = 5자
- 공백 + label(Name 태그, 최대 256자이지만 실제로는 ~50자) + 공백 = ~52자
- display_metric(동적 메트릭 이름, 최대 ~118자) + 공백 = ~119자
- direction + threshold + unit = ~15자
- 공백 + `(` + resource_id(EC2: 19자, ELB ARN: ~120자) + `)` = ~122자
- 합계: 최대 ~313자 → 255자 초과 가능

**대응 방안**:
- `_pretty_alarm_name()`에서 255자 초과 시 label(resource_name)을 truncate
- ELB의 경우 resource_id(ARN)가 길므로 ARN suffix만 사용 (기존 `_extract_elb_dimension()` 패턴 활용)
- 동적 메트릭 이름이 긴 경우 display_metric을 truncate
- truncate 시 `...` 접미사 추가하여 잘림을 표시

**태그 키 128자 제한**:
`Threshold_` 접두사(10자)를 제외하면 메트릭 이름은 최대 118자. CloudWatch MetricName 자체가 255자까지 허용하므로, 태그 키로 표현 불가능한 긴 메트릭 이름이 존재할 수 있다.

**대응 방안**:
- `_parse_threshold_tags()`에서 태그 키 유효성 검증: `Threshold_` 접두사 + 1자 이상의 메트릭 이름
- 태그 값 유효성 검증: 양의 숫자로 파싱 가능한지 확인 (기존 `get_threshold()` 로직 재사용)

**리소스당 태그 50개 제한**:
`Monitoring=on` + `Name` + `Threshold_*` 태그들이 50개 한도를 공유. 실질적으로 동적 알람용 태그는 ~45개 이하.

**태그 허용 문자 제한**:
`Threshold_{MetricName}` 태그 키에서 MetricName 부분은 AWS 태그 허용 문자(`_ . : / = + - @`)만 사용 가능. CloudWatch MetricName에는 허용되지만 태그 키에는 허용되지 않는 문자가 있을 수 있으므로, 동적 파싱 시 태그 키 유효성을 검증해야 한다.

## 용어 정의

- **Bug_Condition (C)**: 하드코딩 목록에 없는 `Threshold_{MetricName}` 태그가 존재하는 리소스에 대해 알람 생성을 시도하는 입력 조건
- **Property (P)**: 태그에서 파싱된 모든 메트릭에 대해 `list_metrics` API로 디멘션을 해석하고 CloudWatch 알람이 정상 생성되는 동작
- **Preservation**: 기존 하드코딩 메트릭(CPU, Memory, Disk 등)의 알람 생성, 임계치 폴백, 알람 이름 포맷, SNS 알림 등 기존 동작이 변경 없이 유지되는 것
- **`_get_alarm_defs()`**: `alarm_manager.py`에서 리소스 유형별 하드코딩 알람 정의를 반환하는 함수
- **`_find_alarms_for_resource()`**: resource_id로 기존 알람을 검색하는 함수 (현재 O(N) 풀스캔)
- **`sync_alarms_for_resource()`**: 알람 임계치 불일치를 감지하고 업데이트하는 동기화 함수
- **`CollectorProtocol`**: Collector 모듈이 구현해야 하는 인터페이스 (신규)
- **`query_metric()`**: CloudWatch 메트릭 조회 공통 유틸리티 (신규)
- **동적 알람**: `Threshold_*` 태그에서 파싱되어 `list_metrics` API로 디멘션이 해석된 알람

## 버그 상세

### 버그 조건

버그는 사용자가 리소스 태그에 하드코딩 목록(`_EC2_ALARMS`, `_RDS_ALARMS`, `_ELB_ALARMS`)에 없는 메트릭의 `Threshold_{MetricName}={Value}` 태그를 입력했을 때 발생한다. `create_alarms_for_resource()`가 `_get_alarm_defs()` 결과만 순회하므로 태그에서 발견된 추가 메트릭은 무시된다.

부가적으로, 알람 검색 시 전체 풀스캔, 이름 문자열 기반 매칭, 중복 API 호출, 함수 복잡도 초과 등이 복합적으로 작용한다.

**형식 명세:**
```
FUNCTION isBugCondition(input)
  INPUT: input of type {resource_id: str, resource_type: str, resource_tags: dict}
  OUTPUT: boolean

  threshold_tags := {k: v FOR k, v IN input.resource_tags
                     WHERE k.startswith("Threshold_") AND k != "Threshold_Disk_*"}
  hardcoded_metrics := getHardcodedMetricKeys(input.resource_type)

  tag_metrics := {k.removeprefix("Threshold_") FOR k IN threshold_tags}
  extra_metrics := tag_metrics - hardcoded_metrics

  RETURN len(extra_metrics) > 0
END FUNCTION
```

### 예시

- `Threshold_NetworkIn=1000000` 태그가 있는 EC2 인스턴스 → `NetworkIn`은 `_EC2_ALARMS`에 없으므로 알람 미생성 (기대: `list_metrics`로 디멘션 해석 후 알람 생성)
- `Threshold_ReadLatency=0.01` 태그가 있는 RDS 인스턴스 → `ReadLatency`는 `_RDS_ALARMS`에 없으므로 알람 미생성 (기대: `AWS/RDS` 네임스페이스에서 디멘션 해석 후 알람 생성)
- `Threshold_CPU=90` 태그가 있는 EC2 인스턴스 → `CPU`는 `_EC2_ALARMS`에 있으므로 정상 생성 (버그 조건 아님)
- `Threshold_ProcessedBytes=5000000` 태그가 있는 NLB → `ProcessedBytes`는 `_ELB_ALARMS`에 없고 NLB 네임스페이스도 미지원 (기대: `AWS/NetworkELB` 네임스페이스 자동 해석)

## 기대 동작

### 보존 요구사항

**변경 없는 동작:**
- 하드코딩 메트릭(CPU, Memory, Disk, FreeMemoryGB, FreeStorageGB, Connections, RequestCount)의 알람 생성은 기존과 동일하게 동작
- 임계치 3단계 폴백 (태그 → 환경변수 → HARDCODED_DEFAULTS) 우선순위 유지
- 알람 이름 포맷 `[{resource_type}] {label} {display_metric} {direction}{threshold}{unit} ({resource_id})` 유지
- Monitoring=on 태그 추가/제거 시 알람 생성/삭제 + lifecycle 알림 발송
- MODIFY 이벤트 Auto-Remediation 동작
- DELETE 이벤트 알람 삭제 + lifecycle 알림
- EC2 Disk CWAgent `list_metrics` 동적 디멘션 조회
- RDS FreeMemoryGB/FreeStorageGB GB → bytes 변환
- SNS 알림 유형별 토픽 분리 및 메시지 포맷
- Daily Monitor 파이프라인: 수집 → 동기화 → 메트릭 조회 → 비교 → 알림

**범위:**
`Threshold_*` 태그가 하드코딩 목록에 있는 메트릭만 포함하는 리소스, 그리고 알람/메트릭과 무관한 모든 입력(Monitoring 태그 변경, MODIFY/DELETE 이벤트 등)은 이 수정에 의해 영향받지 않아야 한다.

## 가설적 근본 원인

버그 분석 결과, 다음과 같은 근본 원인이 식별되었다:

1. **하드코딩 메트릭 목록 한정 순회**: `create_alarms_for_resource()`가 `_get_alarm_defs()` 반환값만 순회하여 태그에서 발견된 추가 메트릭을 처리하는 경로가 없음. 태그 파싱 → `list_metrics` 디멘션 해석 → 알람 생성 파이프라인이 누락됨.

2. **전체 알람 풀스캔**: `_find_alarms_for_resource()`의 새 포맷 검색이 `AlarmTypes=["MetricAlarm"]`으로 전체 알람을 페이지네이션하며 `endswith(suffix)` 필터링. 알람 이름에 `resource_id`를 prefix로 포함하는 네이밍 규칙이 없어 prefix 검색 불가.

3. **이름 문자열 기반 알람 매칭**: `sync_alarms_for_resource()`에서 `_METRIC_DISPLAY`의 display name이 알람 이름에 포함되는지로 매칭. 동일 display name을 가진 다른 메트릭이나 이름 변경 시 오탐/미탐 발생.

4. **중복 API 호출**: `sync_alarms_for_resource()`가 `_find_alarms_for_resource()`로 이름만 조회 후, 각 메트릭별로 `describe_alarms`를 다시 호출하여 임계치 확인. 한 번의 조회로 전체 알람 정보를 캐싱하면 해결.

5. **함수 복잡도 초과**: `create_alarms_for_resource()` 28개 로컬 변수, `sync_alarms_for_resource()` 64개 statements. Disk 알람 로직이 일반 알람과 인라인으로 혼재.

6. **boto3 클라이언트 패턴 불일치**: `alarm_manager.py`는 `global` 변수 싱글턴, collectors/tag_resolver는 함수마다 `boto3.client()` 직접 생성. `functools.lru_cache` 패턴으로 통일 필요.

7. **Collector 코드 중복**: `_query_metric()` 함수가 ec2.py, rds.py, elb.py에 3벌로 독립 구현. `CollectorProtocol` 인터페이스 미정의.

## 정합성 속성

Property 1: Bug Condition - 태그 동적 파싱 알람 생성

_For any_ 리소스 입력에서 하드코딩 목록에 없는 `Threshold_{MetricName}` 태그가 존재하고 CloudWatch에 해당 메트릭 데이터가 있을 때, 수정된 `create_alarms_for_resource()` 함수는 해당 메트릭에 대한 CloudWatch 알람을 `list_metrics` API로 해석된 올바른 네임스페이스/디멘션으로 생성해야 한다(SHALL).

**검증 대상: 요구사항 2.1, 2.2**

Property 2: Preservation - 기존 하드코딩 메트릭 알람 보존

_For any_ 리소스 입력에서 하드코딩 목록에 있는 메트릭만 포함하는 태그 조합에 대해, 수정된 `create_alarms_for_resource()` 함수는 수정 전과 동일한 알람 이름, 네임스페이스, 디멘션, 임계치로 알람을 생성해야 하며, 기존 동작이 보존되어야 한다(SHALL).

**검증 대상: 요구사항 3.1, 3.2, 3.6, 3.7, 3.8**

Property 3: Bug Condition - 메타데이터 기반 알람 매칭

_For any_ 알람 동기화 입력에서 기존 알람이 존재할 때, 수정된 `sync_alarms_for_resource()` 함수는 알람 이름 문자열이 아닌 Namespace/MetricName/Dimensions 메타데이터를 기반으로 정확하게 매칭해야 한다(SHALL).

**검증 대상: 요구사항 2.4, 2.13**

Property 4: Preservation - 알람 검색 효율성

_For any_ resource_id에 대한 알람 검색에서, 수정된 `_find_alarms_for_resource()` 함수는 전체 알람 풀스캔 없이 prefix 기반 검색으로 동일한 결과를 반환해야 한다(SHALL).

**검증 대상: 요구사항 2.3**

Property 5: Constraint - 알람 이름 255자 제한 준수

_For any_ 리소스 입력(resource_name 최대 256자, 동적 메트릭 이름 최대 118자, resource_id 최대 120자 포함)에 대해, `_pretty_alarm_name()` 함수는 항상 255자 이하의 알람 이름을 반환해야 한다(SHALL). truncate 시 resource_id 부분은 보존되어야 한다.

**검증 대상: CloudWatch PutMetricAlarm API AlarmName 제약**

Property 6: Constraint - 태그 키/값 유효성 검증

_For any_ `Threshold_*` 태그에 대해, `_parse_threshold_tags()` 함수는 태그 키가 128자 이하이고 태그 값이 양의 숫자로 파싱 가능한 경우에만 동적 알람 대상으로 포함해야 한다(SHALL). 유효하지 않은 태그는 warning 로그와 함께 skip해야 한다.

**검증 대상: AWS 태그 제약 사항**

## 수정 구현

### 변경 사항

근본 원인 분석이 정확하다는 가정 하에:

**파일**: `common/alarm_manager.py`

**변경 1 - boto3 클라이언트 `lru_cache` 전환**:
- `global _cw_client` + `global` statement 제거
- `@functools.lru_cache(maxsize=None)` 데코레이터 적용
- `import functools` 추가

**변경 2 - 태그 동적 파싱 알람 생성**:
- `_parse_threshold_tags(resource_tags, resource_type)` 헬퍼 추가: `Threshold_*` 태그에서 하드코딩 목록에 없는 메트릭을 추출
  - 태그 키 유효성 검증: `Threshold_` + 1자 이상 메트릭 이름, 태그 허용 문자만 포함
  - 태그 값 유효성 검증: 양의 숫자로 파싱 가능 (기존 `get_threshold()` 로직 재사용)
  - `Threshold_Disk_*` 패턴은 기존 Disk 알람 로직에서 처리하므로 동적 파싱에서 제외
- `_resolve_metric_dimensions(resource_id, metric_name, resource_type)` 헬퍼 추가: `list_metrics` API로 네임스페이스/디멘션 자동 해석
  - resource_type별 기본 네임스페이스 매핑 (EC2→AWS/EC2+CWAgent, RDS→AWS/RDS, ELB→AWS/ApplicationELB+AWS/NetworkELB)
  - `list_metrics(MetricName=metric_name, Dimensions=[{Name: dimension_key, Value: resource_id}])` 호출
  - 결과가 없으면 해당 메트릭 skip (warning 로그)
- `create_alarms_for_resource()`에서 하드코딩 알람 생성 후 동적 태그 알람도 생성

**변경 3 - 알람 이름 255자 제한 준수 + 검색 prefix 통일**:
- `_pretty_alarm_name()`에 255자 truncate 로직 추가:
  - 전체 길이가 255자 초과 시 label(resource_name)을 먼저 truncate (`...` 접미사)
  - 그래도 초과 시 display_metric을 truncate
  - resource_id 부분은 알람 검색/매칭에 필수이므로 절대 truncate하지 않음
- 알람 이름에 `{resource_id}` prefix를 포함하도록 네이밍 규칙 변경: `{resource_id} [{resource_type}] ...`
- `_find_alarms_for_resource()`를 `AlarmNamePrefix=resource_id` 단일 검색으로 단순화
- 레거시 알람 호환을 위해 기존 prefix 검색도 유지

**변경 4 - 메타데이터 기반 알람 매칭**:
- `AlarmDescription`에 메트릭 키를 JSON 형태로 저장: `{"metric_key": "CPU", "resource_id": "i-xxx"}`
- `sync_alarms_for_resource()`에서 `describe_alarms` 1회 호출 후 `AlarmDescription`/`Namespace`/`MetricName`/`Dimensions` 기반 매칭
- 이름 문자열 매칭(`display in a`) 로직 제거

**변경 5 - 함수 분리**:
- `_create_disk_alarms()`: Disk 알람 생성 로직 분리
- `_create_standard_alarm()`: 단일 표준 알람 생성 로직 분리
- `_create_dynamic_alarm()`: 동적 태그 알람 생성 로직 분리
- `_sync_disk_alarms()`: Disk 동기화 로직 분리
- `_sync_standard_alarms()`: 표준 메트릭 동기화 로직 분리

**변경 6 - `except Exception` → `except ClientError`**:
- `_find_alarms_for_resource()`의 `except Exception` 2건을 `except ClientError`로 변경

---

**파일**: `common/collectors/base.py` (신규)

**변경 7 - CollectorProtocol + query_metric 공통화**:
- `CollectorProtocol` (typing.Protocol) 정의: `collect_monitored_resources()`, `get_metrics()`
- `query_metric()` 공통 유틸리티: CloudWatch `get_metric_statistics` 래퍼
- `@functools.lru_cache` 기반 `_get_cw_client()` 포함

---

**파일**: `common/collectors/ec2.py`, `common/collectors/rds.py`, `common/collectors/elb.py`

**변경 8 - Collector 공통 유틸리티 사용**:
- 각 모듈의 `_query_metric()` 삭제, `base.query_metric()` import하여 사용
- `boto3.client()` 직접 생성 → `base._get_cw_client()` 또는 모듈별 `@lru_cache` 싱글턴으로 전환

---

**파일**: `common/collectors/elb.py`

**변경 9 - NLB 지원 추가**:
- `collect_monitored_resources()`에서 LoadBalancer Type 확인 (ALB/NLB)
- NLB인 경우 `AWS/NetworkELB` 네임스페이스 사용
- `get_metrics()`에서 lb_type에 따라 네임스페이스 분기

---

**파일**: `common/tag_resolver.py`

**변경 10 - boto3 클라이언트 lru_cache 전환**:
- `boto3.client()` 직접 생성 → `@functools.lru_cache` 싱글턴 패턴

---

**파일**: `remediation_handler/lambda_handler.py`

**변경 11 - 지연 import 제거 + 중복 코드 추출**:
- `from common.alarm_manager import ...` 6건의 지연 import를 파일 상단으로 이동
- `_remove_monitoring()` 헬퍼 추출: 알람 삭제 + lifecycle 알림 발송 공통 로직
- `_cleanup_orphan_alarms()`의 `import boto3`, `import re` 지연 import를 파일 상단으로 이동

---

**파일**: `daily_monitor/lambda_handler.py`

**변경 12 - 고아 알람 확장**:
- `_cleanup_orphan_alarms()`에서 EC2 외 RDS/ELB 고아 알람도 정리
- boto3 클라이언트 `@lru_cache` 싱글턴 패턴 적용
- `_cleanup_orphan_alarms()` 내부의 `import boto3`, `import re` 지연 import를 파일 상단으로 이동

## 테스트 전략

### 검증 접근법

테스트 전략은 2단계로 진행한다: 먼저 수정 전 코드에서 버그를 재현하는 반례를 확인하고, 수정 후 버그가 해결되었으며 기존 동작이 보존되는지 검증한다.

### 탐색적 버그 조건 확인

**목표**: 수정 전 코드에서 버그를 재현하는 반례를 확인하여 근본 원인 분석을 검증한다. 분석이 틀렸다면 재가설이 필요하다.

**테스트 계획**: moto로 CloudWatch 메트릭을 등록하고, 하드코딩 목록에 없는 `Threshold_*` 태그를 가진 리소스에 대해 `create_alarms_for_resource()`를 호출하여 알람 미생성을 확인한다.

**테스트 케이스**:
1. **동적 메트릭 알람 미생성**: `Threshold_NetworkIn=1000000` 태그가 있는 EC2에 대해 알람 생성 시도 → 알람 미생성 확인 (수정 전 실패)
2. **NLB 메트릭 미지원**: NLB 리소스에 대해 `get_metrics()` 호출 → `AWS/NetworkELB` 네임스페이스 미사용 확인 (수정 전 실패)
3. **알람 풀스캔 확인**: 새 포맷 알람 검색 시 전체 알람 페이지네이션 발생 확인 (수정 전 실패)
4. **이름 문자열 매칭 오탐**: 동일 display name을 가진 다른 리소스의 알람이 매칭되는 케이스 확인 (수정 전 실패)

**예상 반례**:
- `create_alarms_for_resource()` 반환값에 동적 메트릭 알람이 포함되지 않음
- 원인: `_get_alarm_defs()` 하드코딩 목록만 순회, 태그 파싱 경로 부재

### 수정 확인 (Fix Checking)

**목표**: 버그 조건이 성립하는 모든 입력에 대해 수정된 함수가 기대 동작을 생성하는지 검증한다.

**의사코드:**
```
FOR ALL input WHERE isBugCondition(input) DO
  result := create_alarms_for_resource_fixed(input)
  ASSERT 동적 메트릭에 대한 알람이 result에 포함됨
  ASSERT 알람의 Namespace/Dimensions가 list_metrics 결과와 일치
  ASSERT 알람 임계치가 태그 값과 일치
END FOR
```

### 보존 확인 (Preservation Checking)

**목표**: 버그 조건이 성립하지 않는 모든 입력에 대해 수정된 함수가 수정 전과 동일한 결과를 생성하는지 검증한다.

**의사코드:**
```
FOR ALL input WHERE NOT isBugCondition(input) DO
  ASSERT create_alarms_for_resource_original(input) = create_alarms_for_resource_fixed(input)
END FOR
```

**테스트 접근법**: 보존 확인에는 property-based testing(hypothesis)을 권장한다:
- 입력 도메인 전체에 걸쳐 자동으로 많은 테스트 케이스를 생성
- 수동 단위 테스트가 놓칠 수 있는 엣지 케이스 포착
- 모든 비버그 입력에 대해 동작 불변을 강력하게 보장

**테스트 계획**: 수정 전 코드에서 하드코딩 메트릭만 포함하는 태그 조합의 동작을 관찰한 후, 수정 후에도 동일한 동작이 유지되는지 hypothesis PBT로 검증한다.

**테스트 케이스**:
1. **기존 EC2 알람 보존**: CPU/Memory/Disk 알람이 동일한 이름/임계치/디멘션으로 생성되는지 확인
2. **기존 RDS 알람 보존**: CPU/FreeMemoryGB/FreeStorageGB/Connections 알람이 GB→bytes 변환 포함 동일하게 생성되는지 확인
3. **임계치 폴백 보존**: 태그→환경변수→하드코딩 3단계 폴백 우선순위가 유지되는지 확인
4. **알람 이름 포맷 보존**: `_pretty_alarm_name()` 출력이 기존과 동일한지 확인

### 단위 테스트

- `_parse_threshold_tags()`: 다양한 태그 조합에서 동적 메트릭 추출 검증
- `_resolve_metric_dimensions()`: `list_metrics` API 결과에서 올바른 디멘션 해석 검증
- `_create_dynamic_alarm()`: 동적 알람 생성 시 올바른 파라미터 전달 검증
- `_find_alarms_for_resource()`: prefix 기반 검색으로 레거시/새 포맷 모두 커버 검증
- `_remove_monitoring()`: 알람 삭제 + lifecycle 알림 공통 헬퍼 검증
- `query_metric()` (base.py): CloudWatch 메트릭 조회 공통 유틸리티 검증
- NLB 네임스페이스 분기 검증

### Property-Based 테스트

- 임의의 `Threshold_*` 태그 조합을 생성하여 동적 메트릭 알람이 올바르게 생성되는지 검증 (hypothesis)
- 임의의 하드코딩 메트릭 태그 조합에서 기존 알람 생성 동작이 보존되는지 검증 (hypothesis)
- 임의의 알람 구성에서 메타데이터 기반 매칭이 이름 문자열 매칭보다 정확한지 검증 (hypothesis)
- 임의의 resource_id에 대해 prefix 기반 검색이 풀스캔과 동일한 결과를 반환하는지 검증 (hypothesis)

### 통합 테스트

- Daily Monitor 전체 파이프라인: 동적 태그 알람 포함 리소스의 수집 → 동기화 → 메트릭 조회 → 알림 흐름
- Remediation Handler: Monitoring 태그 변경 시 동적 알람 포함 생성/삭제 흐름
- 고아 알람 정리: EC2/RDS/ELB 모두의 고아 알람이 정리되는 전체 흐름
