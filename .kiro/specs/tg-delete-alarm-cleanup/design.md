# TG 삭제 알람 정리 버그픽스 디자인

## Overview

Target Group(TG) 삭제 시 `DeleteTargetGroup` CloudTrail 이벤트가 시스템의 3개 레이어(EventBridge 룰, 모니터링 이벤트 상수, Lambda 이벤트 파싱)에서 모두 누락되어 TG 관련 CloudWatch 알람이 정리되지 않는 버그를 수정한다.

수정 전략: 기존 `DeleteLoadBalancer` / `TerminateInstances` / `DeleteDBInstance` 삭제 이벤트 처리 패턴과 동일한 방식으로 `DeleteTargetGroup`을 3개 레이어에 추가한다. 기존 `_handle_delete()` 로직은 변경하지 않으며, 이벤트 파싱 단계에서 TG ARN을 추출하고 `resource_type="TG"`로 분류하는 것만 추가한다.

## Glossary

- **Bug_Condition (C)**: `DeleteTargetGroup` CloudTrail 이벤트가 발생했을 때 시스템이 이를 감지하지 못하는 조건
- **Property (P)**: `DeleteTargetGroup` 이벤트 발생 시 TG 알람 삭제 + lifecycle SNS 알림 발송이 정상 동작하는 것
- **Preservation**: 기존 DELETE/MODIFY/TAG_CHANGE 이벤트 처리가 변경 없이 동작하는 것
- **`_API_MAP`**: `remediation_handler/lambda_handler.py`의 이벤트명 → (resource_type, id_extractor) 매핑 딕셔너리
- **`MONITORED_API_EVENTS`**: `common/__init__.py`의 CloudTrail 모니터링 대상 API 이벤트 상수
- **`CloudTrailModifyRule`**: `template.yaml`의 EventBridge 룰. CloudTrail 이벤트를 필터링하여 Remediation Handler Lambda를 트리거

## Bug Details

### Bug Condition

`DeleteTargetGroup` CloudTrail 이벤트가 발생했을 때, 시스템의 3개 레이어 모두에서 해당 이벤트를 인식하지 못해 Remediation Handler가 호출되지 않거나, 호출되더라도 파싱에 실패한다.

**Formal Specification:**
```
FUNCTION isBugCondition(event)
  INPUT: event of type CloudTrailEvent (EventBridge 래핑)
  OUTPUT: boolean

  event_name := event.detail.eventName
  RETURN event_name == "DeleteTargetGroup"
         AND event_name NOT IN CloudTrailModifyRule.eventPattern.detail.eventName
         AND event_name NOT IN MONITORED_API_EVENTS["DELETE"]
         AND event_name NOT IN _API_MAP
END FUNCTION
```

### Examples

- TG ARN `arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/my-tg/abc123`이 삭제됨 → EventBridge 룰이 `DeleteTargetGroup`을 캡처하지 않아 Lambda 미호출 → TG의 HealthyHostCount, UnHealthyHostCount, RequestCountPerTarget, TGResponseTime 알람이 `INSUFFICIENT_DATA` 상태로 영구 잔존
- `Monitoring=on` 태그가 있는 TG가 삭제됨 → `RESOURCE_DELETED` lifecycle SNS 알림 미발송 → 운영자가 TG 삭제 사실을 인지하지 못함
- `Monitoring` 태그가 없는 TG가 삭제됨 → 알람이 있었다면 삭제되어야 하지만 이벤트 자체가 도달하지 않아 정리 불가
- 가설적으로 EventBridge를 우회하여 `DeleteTargetGroup` 이벤트가 Lambda에 직접 도달하더라도 → `_API_MAP`에 매핑이 없어 `ValueError("Unsupported eventName")` 발생 → `parse_error` 반환

## Expected Behavior

### Preservation Requirements

**Unchanged Behaviors:**
- `TerminateInstances` → EC2 알람 삭제 + lifecycle 알림 (기존 동작 유지)
- `DeleteDBInstance` → RDS 알람 삭제 + lifecycle 알림 (기존 동작 유지)
- `DeleteLoadBalancer` → ALB/NLB 알람 삭제 + lifecycle 알림 (기존 동작 유지)
- `ModifyInstanceAttribute` 등 MODIFY 이벤트 → Auto-Remediation 로직 (기존 동작 유지)
- `CreateTags`/`DeleteTags` 등 TAG_CHANGE 이벤트 → 태그 변경 처리 로직 (기존 동작 유지)
- `Monitoring` 태그가 없는 리소스 삭제 시 lifecycle SNS 알림 미발송 (기존 동작 유지)

**Scope:**
`DeleteTargetGroup` 이벤트가 아닌 모든 입력은 이 수정에 의해 영향받지 않아야 한다. 변경은 순수 추가(additive)이며 기존 코드 경로를 수정하지 않는다.

## Hypothesized Root Cause

`DeleteTargetGroup` 이벤트가 시스템에 추가되지 않은 것이 근본 원인이다. 3개 레이어 모두에서 누락:

1. **EventBridge 룰 누락**: `template.yaml`의 `CloudTrailModifyRule` EventPattern `detail.eventName` 리스트에 `DeleteTargetGroup`이 없음. 따라서 AWS가 해당 이벤트를 발생시켜도 Remediation Handler Lambda가 트리거되지 않음.

2. **모니터링 이벤트 상수 누락**: `common/__init__.py`의 `MONITORED_API_EVENTS["DELETE"]` 리스트에 `DeleteTargetGroup`이 없음. `_get_event_category()` 함수가 `None`을 반환하여 이벤트 카테고리 판별 실패.

3. **Lambda 이벤트 파싱 매핑 누락**: `remediation_handler/lambda_handler.py`의 `_API_MAP` 딕셔너리에 `DeleteTargetGroup` 엔트리가 없음. `parse_cloudtrail_event()`가 `ValueError("Unsupported eventName: 'DeleteTargetGroup'")` 발생.

이 3개 누락은 독립적이며, 모두 수정해야 정상 동작한다. EventBridge 룰만 수정하면 Lambda는 호출되지만 파싱 실패. 파싱만 수정하면 EventBridge가 이벤트를 전달하지 않음.

## Correctness Properties

Property 1: Bug Condition - DeleteTargetGroup 이벤트 파싱 및 알람 정리

_For any_ `DeleteTargetGroup` CloudTrail 이벤트에서 `requestParameters.targetGroupArn`에 유효한 TG ARN이 포함된 경우, 수정된 `parse_cloudtrail_event()` 함수는 해당 ARN을 `resource_id`로 추출하고 `resource_type="TG"`, `event_category="DELETE"`로 파싱하여 `_handle_delete()`를 통해 TG 알람 삭제 및 lifecycle 알림을 정상 수행해야 한다(SHALL).

**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**

Property 2: Preservation - 기존 DELETE/MODIFY/TAG_CHANGE 이벤트 동작 보존

_For any_ `DeleteTargetGroup`이 아닌 기존 지원 이벤트(`TerminateInstances`, `DeleteDBInstance`, `DeleteLoadBalancer`, `ModifyInstanceAttribute` 등), 수정된 코드는 수정 전과 동일한 `ParsedEvent`를 생성하고 동일한 핸들러 경로를 실행하여 기존 동작을 완전히 보존해야 한다(SHALL).

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6**

## Fix Implementation

### Changes Required

근본 원인 분석이 정확하다는 가정 하에:


**File 1**: `template.yaml`

**Resource**: `CloudTrailModifyRule`

**Specific Changes**:
1. **EventPattern에 `DeleteTargetGroup` 추가**: `detail.eventName` 리스트에 `DeleteTargetGroup` 항목 추가
   - 위치: 기존 `DeleteLoadBalancer` 항목 바로 아래
   - EventBridge source `aws.elasticloadbalancing`은 이미 포함되어 있으므로 추가 불필요

**File 2**: `common/__init__.py`

**Constant**: `MONITORED_API_EVENTS`

**Specific Changes**:
1. **`DELETE` 리스트에 `DeleteTargetGroup` 추가**: 기존 `DeleteLoadBalancer` 항목 아래에 추가
   - `_get_event_category("DeleteTargetGroup")`이 `"DELETE"`를 반환하도록 함

**File 3**: `remediation_handler/lambda_handler.py`

**Dictionary**: `_API_MAP`

**Specific Changes**:
1. **TG ARN 추출 함수 추가**: `_extract_tg_id(params)` 함수 신규 작성
   - `params.get("targetGroupArn")` 반환
   - `DeleteTargetGroup` API의 `requestParameters` 구조: `{"targetGroupArn": "arn:aws:elasticloadbalancing:..."}`
2. **`_API_MAP`에 `DeleteTargetGroup` 매핑 추가**: `("TG", _extract_tg_id)` 엔트리 추가
   - `resource_type`을 `"TG"`로 직접 지정하므로 `_resolve_elb_type()` 분기를 타지 않음
   - 기존 `_handle_delete()` 로직이 그대로 `delete_alarms_for_resource(arn, "TG")`를 호출

**변경하지 않는 것**:
- `_handle_delete()` 함수: TG 타입을 이미 처리할 수 있는 범용 구조
- `_resolve_elb_type()` 함수: `resource_type`이 `"ELB"`일 때만 호출되며, TG는 `_API_MAP`에서 직접 `"TG"` 지정
- `alarm_manager.py`의 `delete_alarms_for_resource()`: TG 알람 검색/삭제 이미 지원
- `alarm_manager.py`의 `_find_alarms_for_resource()`: `resource_type="TG"` prefix 검색 이미 지원

## Testing Strategy

### Validation Approach

테스트 전략은 2단계로 진행한다: (1) 수정 전 코드에서 버그를 재현하는 탐색적 테스트, (2) 수정 후 코드에서 버그 수정 확인 + 기존 동작 보존 확인.

### Exploratory Bug Condition Checking

**Goal**: 수정 전 코드에서 `DeleteTargetGroup` 이벤트가 실패하는 것을 확인하여 근본 원인 분석을 검증한다.

**Test Plan**: `DeleteTargetGroup` 이벤트를 시뮬레이션하여 `parse_cloudtrail_event()`에 전달하고, `ValueError("Unsupported eventName")` 발생을 확인한다.

**Test Cases**:
1. **파싱 실패 테스트**: `DeleteTargetGroup` 이벤트를 `parse_cloudtrail_event()`에 전달 → `ValueError` 발생 확인 (수정 전 코드에서 실패)
2. **이벤트 카테고리 미분류 테스트**: `_get_event_category("DeleteTargetGroup")` → `None` 반환 확인 (수정 전 코드에서 실패)
3. **`_API_MAP` 미등록 테스트**: `"DeleteTargetGroup" not in _API_MAP` 확인 (수정 전 코드에서 실패)

**Expected Counterexamples**:
- `parse_cloudtrail_event()` 호출 시 `ValueError("Unsupported eventName: 'DeleteTargetGroup'")` 발생
- 원인: `_API_MAP`에 `DeleteTargetGroup` 매핑 부재 + `MONITORED_API_EVENTS["DELETE"]`에 미등록

### Fix Checking

**Goal**: 수정 후 `DeleteTargetGroup` 이벤트가 정상 파싱되고 알람 삭제 + lifecycle 알림이 동작하는지 검증한다.

**Pseudocode:**
```
FOR ALL event WHERE isBugCondition(event) DO
  parsed := parse_cloudtrail_event(event)
  ASSERT parsed.resource_type == "TG"
  ASSERT parsed.event_category == "DELETE"
  ASSERT parsed.resource_id == event.detail.requestParameters.targetGroupArn
  result := _handle_delete(parsed)
  ASSERT delete_alarms_for_resource가 호출됨
  ASSERT Monitoring=on이면 send_lifecycle_alert가 호출됨
END FOR
```

### Preservation Checking

**Goal**: 수정 후 기존 DELETE/MODIFY/TAG_CHANGE 이벤트의 파싱 결과와 핸들러 동작이 수정 전과 동일한지 검증한다.

**Pseudocode:**
```
FOR ALL event WHERE NOT isBugCondition(event) DO
  ASSERT parse_cloudtrail_event_fixed(event) == parse_cloudtrail_event_original(event)
END FOR
```

**Testing Approach**: Property-based testing(hypothesis)을 사용하여 기존 지원 이벤트 전체에 대해 파싱 결과가 동일한지 검증한다. 변경이 순수 추가(additive)이므로 기존 `_API_MAP` 엔트리와 `MONITORED_API_EVENTS` 엔트리가 변경되지 않았음을 직접 확인하는 것도 유효하다.

**Test Cases**:
1. **EC2 DELETE 보존**: `TerminateInstances` 이벤트 파싱 결과가 수정 전과 동일한지 확인
2. **RDS DELETE 보존**: `DeleteDBInstance` 이벤트 파싱 결과가 수정 전과 동일한지 확인
3. **ALB/NLB DELETE 보존**: `DeleteLoadBalancer` 이벤트 파싱 결과가 수정 전과 동일한지 확인
4. **MODIFY 이벤트 보존**: `ModifyInstanceAttribute` 등 MODIFY 이벤트 파싱 결과가 수정 전과 동일한지 확인
5. **TAG_CHANGE 이벤트 보존**: `CreateTags`/`DeleteTags` 등 TAG_CHANGE 이벤트 파싱 결과가 수정 전과 동일한지 확인

### Unit Tests

- `parse_cloudtrail_event()`: `DeleteTargetGroup` 이벤트 → `resource_type="TG"`, `event_category="DELETE"`, `resource_id=targetGroupArn` 확인
- `_get_event_category("DeleteTargetGroup")` → `"DELETE"` 반환 확인
- `_handle_delete()`: TG 타입 + `Monitoring=on` → `delete_alarms_for_resource` + `send_lifecycle_alert` 호출 확인
- `_handle_delete()`: TG 타입 + `Monitoring` 태그 없음 → `delete_alarms_for_resource` 호출, `send_lifecycle_alert` 미호출 확인
- `_extract_tg_id()`: `targetGroupArn` 키에서 ARN 추출 확인
- `_extract_tg_id()`: `targetGroupArn` 키 없을 때 `None` 반환 확인

### Property-Based Tests

- 랜덤 TG ARN 생성 → `DeleteTargetGroup` 이벤트 파싱 → `resource_type="TG"`, `event_category="DELETE"` 일관성 검증
- 기존 지원 이벤트 중 랜덤 선택 → 파싱 결과의 `resource_type`/`event_category`가 기존 매핑과 일치하는지 검증 (보존 속성)
- 랜덤 TG ARN + `Monitoring=on` → `_handle_delete()` 호출 시 `delete_alarms_for_resource` + `send_lifecycle_alert` 호출 검증

### Integration Tests

- `lambda_handler()`에 `DeleteTargetGroup` 이벤트 전달 → `{"status": "ok"}` 반환 + 알람 삭제/lifecycle 알림 동작 확인
- `lambda_handler()`에 기존 `TerminateInstances` 이벤트 전달 → 기존과 동일한 동작 확인
- `template.yaml` EventPattern에 `DeleteTargetGroup`이 포함되어 있는지 정적 검증
