# 버그 수정 요구사항 문서

## 소개

AWS 모니터링 엔진의 태그 기반 동적 알람 시스템에 다수의 결함이 존재한다. 핵심 문제는 사용자가 리소스 태그에 임의의 메트릭 이름과 임계치를 입력해도 하드코딩된 메트릭 목록만 처리하여 알람이 생성되지 않는 것이다. 이 외에도 디멘션 자동 해석 불가, O(N) 풀스캔 성능 문제, 중복 API 호출, 고아 알람 미처리, 코드 중복/복잡도 초과 등 13개의 결함이 확인되었다.

## 버그 분석

### 현재 동작 (결함)

1.1 WHEN 사용자가 리소스 태그에 `Threshold_NetworkIn=1000000` 같은 하드코딩 목록에 없는 새 메트릭 임계치를 입력하면 THEN `_get_alarm_defs()`가 `_EC2_ALARMS`, `_RDS_ALARMS`, `_ELB_ALARMS` 하드코딩 리스트만 반환하여 해당 메트릭의 알람이 생성되지 않는다

1.2 WHEN 하드코딩 목록에 없는 메트릭에 대해 알람을 생성하려 하면 THEN `dimension_key`가 하드코딩되어 있어 새 메트릭의 네임스페이스와 디멘션을 자동으로 파악하지 못한다

1.3 WHEN `_find_alarms_for_resource()`가 새 포맷 알람을 검색하면 THEN 전체 MetricAlarm을 페이지네이션하며 O(N) 풀스캔하여 알람 수천 개 이상일 때 Lambda timeout 위험이 있다

1.4 WHEN `sync_alarms_for_resource()`가 실행되면 THEN `_find_alarms_for_resource()`로 이름 조회 후 각 메트릭별로 다시 `describe_alarms`를 호출하여 동일 알람을 2~3회 중복 조회한다

1.5 WHEN `_cleanup_orphan_alarms()`가 실행되면 THEN EC2 인스턴스의 고아 알람만 처리하고 RDS/ELB의 고아 알람은 정리하지 않는다

1.6 WHEN `create_alarms_for_resource()`가 실행되면 THEN 28개 로컬 변수를 사용하고 Disk 알람 로직이 일반 알람과 인라인으로 혼재되어 함수 복잡도가 초과된다

1.7 WHEN `sync_alarms_for_resource()`가 실행되면 THEN 64개 statements로 구성되어 함수 복잡도가 초과된다

1.8 WHEN `alarm_manager.py`에서 boto3 클라이언트를 사용하면 THEN 모듈 레벨 싱글턴 패턴을 사용하지만, 나머지 모듈(collectors, tag_resolver)은 함수 호출마다 새로 생성하여 패턴이 불일치한다

1.9 WHEN `remediation_handler`의 `_handle_tag_change()`가 실행되면 THEN 지연 import가 6회 반복되고 알람 삭제 + lifecycle 알림 코드가 복사-붙여넣기로 중복된다

1.10 WHEN ec2.py, rds.py, elb.py 각 Collector에서 메트릭을 조회하면 THEN `_query_metric` 함수가 3벌로 독립 구현되어 코드가 중복된다

1.11 WHEN 새 Collector를 추가하려 하면 THEN `_COLLECTOR_MODULES` 리스트를 직접 수정해야 하고 Protocol/ABC 인터페이스가 미정의되어 있다

1.12 WHEN ELB Collector가 메트릭을 수집하면 THEN ALB(`AWS/ApplicationELB`) 네임스페이스만 지원하고 NLB(`AWS/NetworkELB`) 메트릭이 누락된다

1.13 WHEN `sync_alarms_for_resource()`에서 기존 알람과 메트릭을 매칭하면 THEN `_METRIC_DISPLAY`의 display name 문자열이 알람 이름에 포함되어 있는지로 매칭하여 오탐/미탐 위험이 있다

### 기대 동작 (정상)

2.1 WHEN 사용자가 리소스 태그에 `Threshold_{MetricName}={Value}` 형식으로 임의의 메트릭 임계치를 입력하면 THEN 시스템은 태그를 동적으로 파싱하여 해당 메트릭에 대한 CloudWatch 알람을 자동 생성해야 한다 (SHALL)

2.2 WHEN 하드코딩 목록에 없는 메트릭에 대해 알람을 생성할 때 THEN 시스템은 CloudWatch `list_metrics` API를 활용하여 네임스페이스와 디멘션을 자동으로 해석해야 한다 (SHALL)

2.3 WHEN `_find_alarms_for_resource()`가 알람을 검색할 때 THEN 시스템은 알람 이름 prefix 또는 태그 기반 검색으로 O(1) 또는 O(log N) 수준의 효율적 검색을 수행해야 한다 (SHALL)

2.4 WHEN `sync_alarms_for_resource()`가 실행될 때 THEN 시스템은 알람 정보를 한 번만 조회하고 캐싱하여 중복 `describe_alarms` 호출을 제거해야 한다 (SHALL)

2.5 WHEN `_cleanup_orphan_alarms()`가 실행될 때 THEN 시스템은 EC2뿐 아니라 RDS, ELB의 고아 알람도 정리해야 한다 (SHALL)

2.6 WHEN `create_alarms_for_resource()`가 실행될 때 THEN Disk 알람 로직이 별도 함수로 분리되어 함수 복잡도가 적정 수준이어야 한다 (SHALL)

2.7 WHEN `sync_alarms_for_resource()`가 실행될 때 THEN 함수가 적절히 분리되어 statements 수가 50개 이하여야 한다 (SHALL)

2.8 WHEN boto3 클라이언트를 사용할 때 THEN 모든 모듈에서 일관된 싱글턴 패턴을 사용해야 한다 (SHALL)

2.9 WHEN `remediation_handler`에서 알람 삭제 + lifecycle 알림을 처리할 때 THEN 공통 헬퍼 함수로 추출하여 코드 중복을 제거하고 지연 import를 정리해야 한다 (SHALL)

2.10 WHEN Collector에서 CloudWatch 메트릭을 조회할 때 THEN 공통 `_query_metric` 유틸리티를 사용하여 코드 중복을 제거해야 한다 (SHALL)

2.11 WHEN 새 Collector를 추가할 때 THEN Protocol 또는 ABC 인터페이스를 구현하면 자동으로 등록되어야 한다 (SHALL)

2.12 WHEN ELB Collector가 메트릭을 수집할 때 THEN ALB와 NLB 모두의 메트릭을 지원해야 한다 (SHALL)

2.13 WHEN 알람과 메트릭을 매칭할 때 THEN 알람 메타데이터(Namespace, MetricName, Dimensions) 기반으로 정확하게 매칭해야 한다 (SHALL)

### 변경 없는 동작 (회귀 방지)

3.1 WHEN 하드코딩 목록에 있는 기존 메트릭(CPU, Memory, Disk, FreeMemoryGB, FreeStorageGB, Connections, RequestCount)에 대해 알람을 생성하면 THEN 시스템은 기존과 동일하게 알람을 생성해야 한다 (SHALL CONTINUE TO)

3.2 WHEN `Threshold_{metric_name}` 태그 → 환경변수 → HARDCODED_DEFAULTS 3단계 폴백으로 임계치를 조회하면 THEN 시스템은 기존 우선순위를 유지해야 한다 (SHALL CONTINUE TO)

3.3 WHEN Monitoring=on 태그가 추가/제거되면 THEN 시스템은 기존과 동일하게 알람 생성/삭제 및 lifecycle 알림을 발송해야 한다 (SHALL CONTINUE TO)

3.4 WHEN MODIFY 이벤트가 감지되면 THEN 시스템은 기존과 동일하게 Auto-Remediation을 수행해야 한다 (SHALL CONTINUE TO)

3.5 WHEN DELETE 이벤트가 감지되면 THEN 시스템은 기존과 동일하게 알람 삭제 및 lifecycle 알림을 발송해야 한다 (SHALL CONTINUE TO)

3.6 WHEN EC2 Disk 알람을 생성할 때 THEN 시스템은 기존과 동일하게 CWAgent `list_metrics`에서 path/device/fstype 디멘션을 동적으로 조회해야 한다 (SHALL CONTINUE TO)

3.7 WHEN RDS FreeMemoryGB/FreeStorageGB 알람을 생성할 때 THEN 시스템은 기존과 동일하게 GB → bytes 단위 변환을 적용해야 한다 (SHALL CONTINUE TO)

3.8 WHEN 알람 이름을 생성할 때 THEN 시스템은 기존 `[{resource_type}] {label} {display_metric} {direction}{threshold}{unit} ({resource_id})` 포맷을 유지해야 한다 (SHALL CONTINUE TO)

3.9 WHEN SNS 알림을 발송할 때 THEN 시스템은 기존 알림 유형별 토픽 ARN 분리 및 메시지 포맷을 유지해야 한다 (SHALL CONTINUE TO)

3.10 WHEN Daily Monitor가 실행될 때 THEN 시스템은 기존과 동일하게 리소스 수집 → 알람 동기화 → 메트릭 조회 → 임계치 비교 → 알림 발송 파이프라인을 유지해야 한다 (SHALL CONTINUE TO)
