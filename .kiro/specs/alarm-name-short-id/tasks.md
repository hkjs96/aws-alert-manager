# Implementation Plan: Alarm Name Short ID

## Overview

ALB/NLB/TG 알람 이름 suffix에 Full_ARN 대신 Short_ID(`{name}/{hash}`)를 사용하도록 변경한다. TDD 사이클(레드-그린-리팩터링)을 준수하며, `common/alarm_manager.py` 내부 변경에 한정한다.

## Tasks

- [x] 1. `_shorten_elb_resource_id()` 함수 구현 (TDD)
  - [x] 1.1 테스트 작성: `_shorten_elb_resource_id()` 단위 테스트
    - `tests/test_alarm_manager.py`에 `TestShortenElbResourceId` 클래스 추가
    - ALB ARN → `{name}/{hash}` 반환 검증
    - NLB ARN → `{name}/{hash}` 반환 검증
    - TG ARN → `{name}/{hash}` 반환 검증
    - EC2 instance ID (`i-xxx`) → 그대로 반환 검증
    - RDS identifier → 그대로 반환 검증
    - ARN이 아닌 문자열 → 그대로 반환 (방어적 처리)
    - 빈 문자열 → 빈 문자열 반환
    - 이미 Short_ID 형태인 입력 → 동일 결과 (멱등성)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 5.3_

  - [x] 1.2 `_shorten_elb_resource_id()` 함수 구현
    - `common/alarm_manager.py`에 함수 추가
    - `resource_type`이 ALB/NLB/TG일 때만 ARN 파싱, 그 외는 원본 반환
    - ARN 파싱 실패 시 원본 반환 (방어적 처리)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 5.1, 5.3_

  - [ ]* 1.3 Property 1 테스트: ALB/NLB/TG Short_ID 추출 정확성
    - **Property 1: ALB/NLB/TG Short_ID 추출 정확성**
    - **Validates: Requirements 1.1, 1.2, 1.3**
    - 테스트 파일: `tests/test_pbt_short_id.py`
    - hypothesis 전략: 랜덤 ALB/NLB/TG ARN 생성 → 결과가 `{name}/{hash}` 패턴이고 `arn:`, `loadbalancer/`, `app/`, `net/`, `targetgroup/` 접두사 미포함 검증

  - [ ]* 1.4 Property 2 테스트: EC2/RDS 무변환
    - **Property 2: EC2/RDS 무변환**
    - **Validates: Requirements 1.4**
    - 테스트 파일: `tests/test_pbt_short_id.py`
    - hypothesis 전략: 랜덤 EC2 ID / RDS identifier 생성 → 입력 == 출력 검증

  - [ ]* 1.5 Property 7 테스트: Short_ID 추출 멱등성
    - **Property 7: Short_ID 추출 멱등성**
    - **Validates: Requirements 5.3**
    - 테스트 파일: `tests/test_pbt_short_id.py`
    - hypothesis 전략: 랜덤 ALB/NLB/TG ARN → `f(f(x)) == f(x)` 검증

  - [ ]* 1.6 Property 8 테스트: Short_ID와 Dimension 값 차이
    - **Property 8: Short_ID와 Dimension 값 차이**
    - **Validates: Requirements 5.2**
    - 테스트 파일: `tests/test_pbt_short_id.py`
    - hypothesis 전략: 랜덤 ALB/NLB ARN → `_shorten_elb_resource_id()` != `_extract_elb_dimension()` 검증

- [x] 2. `_pretty_alarm_name()` suffix에 Short_ID 적용 (TDD)
  - [x] 2.1 테스트 작성: ALB/NLB/TG suffix 변경 검증
    - `tests/test_alarm_manager.py`의 `TestHelpers`에 테스트 추가
    - ALB ARN → 알람 이름이 `({name}/{hash})`로 끝나는지 검증
    - NLB ARN → 알람 이름이 `({name}/{hash})`로 끝나는지 검증
    - TG ARN → 알람 이름이 `({name}/{hash})`로 끝나는지 검증
    - EC2/RDS → 기존 동작 유지 검증 (기존 테스트 회귀 없음)
    - _Requirements: 2.1, 2.2_

  - [x] 2.2 `_pretty_alarm_name()` 구현 변경
    - suffix 생성 부분에서 `_shorten_elb_resource_id(resource_id, resource_type)` 호출 추가
    - `_pretty_alarm_name()` 시그니처 변경 없음 (`resource_type`은 이미 존재)
    - _Requirements: 2.1, 2.2, 2.3_

  - [ ]* 2.3 Property 3 테스트: 알람 이름 Short_ID suffix
    - **Property 3: 알람 이름 Short_ID suffix**
    - **Validates: Requirements 2.1, 2.4**
    - 테스트 파일: `tests/test_pbt_short_id.py`
    - hypothesis 전략: 랜덤 ALB/NLB/TG ARN + metric + threshold → `_pretty_alarm_name()` 결과가 `({short_id})`로 끝나는지 검증

- [x] 3. `_create_dynamic_alarm()` suffix에 Short_ID 적용 (TDD)
  - [x] 3.1 테스트 작성: 동적 알람 suffix 변경 검증
    - `tests/test_alarm_manager.py`에 동적 알람 ALB/NLB/TG suffix 테스트 추가
    - 동적 태그 알람 생성 시 suffix가 Short_ID인지 검증
    - _Requirements: 2.4_

  - [x] 3.2 `_create_dynamic_alarm()` 구현 변경
    - suffix 생성 부분에서 `_shorten_elb_resource_id(resource_id, resource_type)` 호출 추가
    - _Requirements: 2.4_

- [x] 4. Checkpoint — `_shorten_elb_resource_id`, `_pretty_alarm_name`, `_create_dynamic_alarm` 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. `_find_alarms_for_resource()` 레거시+새 포맷 호환 검색 (TDD)
  - [x] 5.1 테스트 작성: Short_ID suffix + Full_ARN suffix 검색 호환성
    - `tests/test_alarm_manager.py`에 테스트 추가 (moto 기반)
    - 새 Short_ID suffix 알람만 존재 → 정상 검색 검증
    - 레거시 Full_ARN suffix 알람만 존재 → 정상 검색 검증
    - 혼재 상태 → 중복 없이 합산 검증
    - EC2/RDS → 기존 검색 로직 변경 없음 검증
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [x] 5.2 `_find_alarms_for_resource()` 구현 변경
    - Short_ID suffix와 Full_ARN suffix 모두 검색하도록 `suffixes` set 사용
    - `_collect()` 내부 suffix 필터를 `any(name.endswith(s) for s in suffixes)`로 변경
    - `seen` set 중복 제거 기존 로직 유지
    - _Requirements: 3.1, 3.2, 3.3, 3.4_

  - [ ]* 5.3 Property 5 테스트: 검색 결과 중복 없음
    - **Property 5: 검색 결과 중복 없음**
    - **Validates: Requirements 3.3**
    - 테스트 파일: `tests/test_pbt_short_id.py`
    - hypothesis 전략: moto 기반 알람 생성 후 `_find_alarms_for_resource()` 결과에 중복 없음 검증

- [x] 6. AlarmDescription Full_ARN 유지 확인 (TDD)
  - [x] 6.1 테스트 작성: AlarmDescription에 Full_ARN 유지 검증
    - `tests/test_alarm_manager.py`에 테스트 추가
    - ALB/NLB/TG ARN으로 알람 생성 후 `_build_alarm_description()` → `_parse_alarm_metadata()` 라운드트립
    - `resource_id` 필드에 원본 Full_ARN 포함 검증
    - _Requirements: 4.1_

  - [ ]* 6.2 Property 6 테스트: AlarmDescription에 Full_ARN 유지
    - **Property 6: AlarmDescription에 Full_ARN 유지**
    - **Validates: Requirements 4.1**
    - 테스트 파일: `tests/test_pbt_short_id.py`
    - hypothesis 전략: 랜덤 ARN → `_build_alarm_description()` → `_parse_alarm_metadata()` 라운드트립, `resource_id` == 원본 ARN 검증

- [x] 7. Checkpoint — 전체 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

- [x] 8. 기존 PBT 확장: 255자 제한에 ALB/NLB/TG Short_ID 반영
  - [x]* 8.1 Property 4 테스트: 255자 제한 (ALB/NLB/TG 포함)
    - **Property 4: 255자 제한 (ALB/NLB/TG 포함)**
    - **Validates: Requirements 2.3**
    - `tests/test_pbt_alarm_name_constraint.py`의 `resource_types` 전략에 `"ALB"`, `"NLB"`, `"TG"` 추가
    - `resource_ids` 전략에 ALB/NLB/TG ARN 패턴 추가
    - `test_alarm_name_preserves_resource_id` 테스트의 suffix 검증을 Short_ID 기반으로 업데이트
    - 기존 255자 제한 테스트가 새 타입에도 적용되는지 검증

- [x] 9. 거버넌스 §6 알람 이름 포맷 규칙 업데이트
  - [x] 9.1 `.kiro/steering/coding-governance.md` §6 업데이트
    - 알람 이름 포맷 설명에 ALB/NLB/TG의 경우 `({short_id})` 사용 명시
    - Short_ID 정의 추가: `{name}/{hash}` (ARN에서 추출)
    - _Requirements: 2.1_

- [x] 10. Final checkpoint — 전체 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- TDD 사이클 준수: 각 구현 태스크에서 테스트 먼저 작성 (레드) → 최소 구현 (그린) → 리팩터링
- Property tests validate universal correctness properties from design document (Property 1-8)
- `AlarmDescription`의 `resource_id`는 항상 Full_ARN 유지 — 변경 없음 확인만 수행
- `_extract_elb_dimension()`은 변경하지 않음 — Short_ID와 Dimension은 독립적
- Checkpoints ensure incremental validation
