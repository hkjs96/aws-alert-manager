# Bugfix Requirements Document

## Introduction

알람 이름 포맷에 두 가지 문제가 있다:
1. direction과 threshold 사이에 공백이 없어 가독성이 떨어진다 (`>=1` → `>= 1`)
2. suffix의 resource_id에 `TagName:` 접두사가 없어 리소스 식별이 불명확하다 (`(dev-e2e-redis)` → `(TagName: dev-e2e-redis)`)

영향 범위:
- `common/alarm_naming.py` — `_pretty_alarm_name()` 알람 이름 생성
- `common/alarm_builder.py` — 동적 알람 이름 생성 (suffix 부분만 해당)
- `common/alarm_search.py` — `_find_alarms_for_resource()` suffix 매칭
- `daily_monitor/lambda_handler.py` — `_classify_alarm()` 정규식 파싱
- `.kiro/steering/alarm-rules.md` — 알람 네이밍 가이드 문서
- 테스트 파일 — 알람 이름 포맷 assertion

기존 알람은 모두 삭제된 상태(테스트 스택 해체)이므로 마이그레이션은 불필요하다.

## Bug Analysis

### Current Behavior (Defect)

1.1 WHEN `_pretty_alarm_name()`이 알람 이름을 생성할 때 THEN direction과 threshold 사이에 공백이 없다 (예: `>=1` instead of `>= 1`)

1.2 WHEN `_pretty_alarm_name()`이 알람 이름의 suffix를 생성할 때 THEN resource_id에 `TagName:` 접두사가 없다 (예: `(dev-e2e-redis)` instead of `(TagName: dev-e2e-redis)`)

1.3 WHEN `_create_dynamic_alarm()`이 동적 알람 이름의 suffix를 생성할 때 THEN resource_id에 `TagName:` 접두사가 없다 (예: `(i-1234)` instead of `(TagName: i-1234)`)

1.4 WHEN `_find_alarms_for_resource()`가 알람을 검색할 때 THEN suffix 매칭이 `({short_id})` 포맷을 사용하여 새 포맷 `(TagName: {short_id})` 알람을 찾지 못한다

1.5 WHEN `_classify_alarm()`이 알람 이름에서 resource_id를 파싱할 때 THEN 정규식이 `(TagName: {resource_id})` 포맷의 `TagName: ` 접두사를 포함한 값을 캡처하여 순수 resource_id 추출에 실패한다

### Expected Behavior (Correct)

2.1 WHEN `_pretty_alarm_name()`이 알람 이름을 생성할 때 THEN direction과 threshold 사이에 공백을 포함해야 한다 (예: `>= 1`, `< 2`)

2.2 WHEN `_pretty_alarm_name()`이 알람 이름의 suffix를 생성할 때 THEN `(TagName: {short_id})` 포맷을 사용해야 한다

2.3 WHEN `_create_dynamic_alarm()`이 동적 알람 이름의 suffix를 생성할 때 THEN `(TagName: {short_id})` 포맷을 사용해야 한다

2.4 WHEN `_find_alarms_for_resource()`가 알람을 검색할 때 THEN suffix 매칭이 `(TagName: {short_id})` 포맷을 사용해야 한다

2.5 WHEN `_classify_alarm()`이 알람 이름에서 resource_id를 파싱할 때 THEN 정규식이 `(TagName: {resource_id})` 포맷에서 `TagName: ` 접두사를 제외한 순수 resource_id를 추출해야 한다

### Unchanged Behavior (Regression Prevention)

3.1 WHEN 알람 이름이 255자를 초과할 때 THEN label → display_metric 순으로 truncate하는 기존 로직이 유지되어야 한다

3.2 WHEN ALB/NLB/TG 리소스의 알람을 생성할 때 THEN suffix의 resource_id는 기존과 동일하게 Short_ID(`{name}/{hash}`)를 사용해야 한다 (TagName: 접두사만 추가)

3.3 WHEN `_find_alarms_for_resource()`가 레거시 포맷 알람을 검색할 때 THEN 레거시 prefix 기반 검색(`resource_id` prefix)이 계속 동작해야 한다

3.4 WHEN `_classify_alarm()`이 알람 이름을 파싱할 때 THEN resource_type 추출 (`[EC2]`, `[RDS]` 등)은 기존과 동일하게 동작해야 한다

3.5 WHEN `AlarmDescription`에 메타데이터를 저장할 때 THEN `resource_id` 필드에는 기존과 동일하게 전체 ARN/ID를 저장해야 한다 (이름 포맷 변경과 무관)
