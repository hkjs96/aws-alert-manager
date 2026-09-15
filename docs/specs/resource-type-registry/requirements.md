# 리소스 타입 레지스트리 — 요구사항 (2026-09-15)

## User Story

백엔드 개발자로서, AWS 리소스 타입을 추가하거나 타입 전반에 걸친 변경(태그 캐시, 메트릭 배치, 등급 정책)을
할 때 **한 곳만 고치고** 나머지가 따라오길 원한다. 지금은 한 타입이 12개 파일 15곳에 흩어져 있어 횡단 변경이
반쪽에서 멈추고(태그 캐시 26개 중 15개), 정의에서 파생되는 맵 3개를 손으로 다시 적어 드리프트를 테스트로 막고 있다.

## 요구사항 (EARS)

- **R1 단일 정의.** WHEN 리소스 타입이 존재하면 THE 시스템 SHALL 그 타입의 알람 정의·네임스페이스·디멘션 키·
  표시명·기본 임계치·생명주기 이벤트·나열/정체/생존 판정 방법을 **단일 스펙 객체** 하나에 담는다.
- **R2 파생 뷰 동일성.** WHEN 스펙 레지스트리에서 `SUPPORTED_RESOURCE_TYPES`·`_HARDCODED_METRIC_KEYS`·
  `_NAMESPACE_MAP`·`_DIMENSION_KEY_MAP`·`_METRIC_DISPLAY`·`HARDCODED_DEFAULTS`·`MONITORED_API_EVENTS`·`_API_MAP`·
  `_RESOURCE_TYPE_TO_COLLECTOR`·`TAGGED_SERVICES`를 파생하면 THE 파생값 SHALL 이관 시점의 손 맵과 **집합 동일**
  해야 하며, 그 동일성은 스냅숏 테스트로 증명된다.
- **R3 타입 추가 비용.** WHEN 새 리소스 타입을 추가하면 THE 편집 지점 SHALL 스펙 파일 1개 + 테스트 + CFN
  EventPattern(파생 불가) 이하여야 한다.
- **R4 횡단 변경 비용.** WHEN 나열·메트릭 조회·태그 조회 방식에 횡단 변경을 하면 THE 변경 SHALL 범용 수집기
  한 곳에서 끝나야 하며, 스펙에 `enumerate`/`metrics` 오버라이드를 둔 타입만 별도 확인 대상이 된다.
- **R5 동작 무변화.** WHEN 어느 이관 단계를 끝내든 THE alarm-sync 드라이런이 만드는 알람 이름·차원 집합 SHALL
  이관 전과 동일해야 한다(알람 이름이 정체이므로 이것이 회귀의 정의다).
- **R6 RGT 폴백.** IF 고객사 역할에 `tag:GetResources`가 없거나 RGT 프라임이 0건이면 THEN THE 범용 수집기 SHALL
  스펙의 `enumerate`(기존 서비스별 나열)로 폴백해 결과가 예전과 같아야 한다.
- **R7 생존 판정 보수성.** THE `resolve_alive_ids` SHALL RGT 결과를 근거로 삼지 않는다 — 태그가 벗겨진 리소스를
  고아로 오판하지 않기 위해 서비스 describe API로만 존재를 판정한다.
- **R8 템플릿 정합.** WHEN CFN 템플릿의 CloudTrail `detail.eventName` 목록과 스펙의 lifecycle 이벤트 집합이 어긋나면
  THE 단위 테스트 SHALL 실패한다(3곳 동기화 → 1곳 + 테스트).
- **R9 이유가 있는 예외.** WHEN 스펙이 파생 규칙에서 벗어나는 항목(옛 임계치 키, 퍼센트 변형, 동적 알람 전용 키,
  RGT 대신 `enumerate`)을 가지면 THE 스펙 SHALL 그 항목마다 **이유 문자열**을 필수로 갖는다 — 맵은 이유를 말해
  주지 않았고, 그래서 23개 여분 키의 출처를 다시 조사해야 했다.

## 비목표

- 알람 정의를 YAML/JSON으로 외부화하지 않는다(설계 D1).
- `ListMetrics` 기반 메트릭 자동 발견을 하지 않는다(D2).
- 알람 의미(메트릭·임계치·평가 정책)를 바꾸지 않는다. 프런트엔드를 건드리지 않는다.

## Acceptance Criteria

1. 파생 스냅숏 테스트가 통과한 상태에서 손 맵 3개가 삭제돼 있다.
2. 새 타입 하나(예: Kinesis Data Streams)를 스펙 파일 1개 + 테스트 + 템플릿 이벤트로 추가하는 시연이 된다.
3. 16개 타입이 `GenericCollector`로 옮겨진 뒤 alarm-sync 드라이런 집합 비교가 0 diff다.
4. 태그 캐시 적용률이 "26개 중 15개"가 아니라 "범용 경로 100% + 오버라이드 N개(각각 이유 명시)"로 표현된다.
5. `/new-collector` 체크리스트가 스펙 작성 규칙으로 대체돼 있다.
