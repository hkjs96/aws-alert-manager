# Monitoring 태그 계약 — 태그가 의도, 인벤토리는 관측 (2026-09-16)

## 배경

"감시 여부"를 어디에 두느냐는 질문(09-16)에 대한 답은 **AWS 리소스의 `Monitoring` 태그가 진실**이고, 우리 인벤토리의
`monitoring` 플래그는 그 관측이라는 것이다. 이것은 AWS 문서의 권장과 같다.

- Best practices for tagging AWS resources, "Tags for automation": 자동화 작업의 opt-in/opt-out을 태그로.
- AWS Backup(태그 기반 리소스 할당)·Systems Manager(태그 타깃)·DevOps Guru(태그/스택 커버리지)가 같은 패턴. AWS Config·
  Resource Explorer는 "찾고 기록하는" 인벤토리이지 의도를 저장하는 곳이 아니다.
- 거버넌스는 Organizations 태그 정책(키 표준화·대소문자·허용 값·enforced)과 SCP(삭제·누락 방지)로.
- 태그 쓰기 권한은 `aws:TagKeys` 조건으로 키를 제한(최소 권한).

태그 방식의 두 장점이 결정적이다: IaC 고객이 태그 한 줄로 켜고, 리소스가 교체(ASG·재생성)돼도 새 리소스가 태그를 따라 자동
감시된다. 인벤토리 플래그만 두면 ID가 바뀔 때 조용히 감시에서 빠진다. 콘솔 토글은 태그 쓰기로 간다(= 고객이 하는 일을 대신
하는 것). 쓰기 권한을 끝내 못 받는 고객을 위한 "인벤토리 오버라이드"는 필요해질 때 예외 경로로 추가한다(이번 범위 밖).

## 현재 구조(사실)와 구멍

| 구성 | 현재 | 구멍 |
|---|---|---|
| 태그 쓰기 | UI 토글 → `PUT /resources/{id}/monitoring` → RGT `tag_resources` | 온보딩 역할·API 핸들러 역할이 21개 서비스 태깅을 **키 제한 없이** 허용 |
| 태그 → 알람 즉시 반영 | remediation이 CloudTrail 태그 이벤트에 반응 | 생명주기 TAG_CHANGE가 29타입 중 **EC2·RDS·ALB·SQS 4타입**. SQS는 파라미터 모양(`tags` dict·`tagKeys`)을 못 읽어 사실상 무반응. 나머지 25타입은 daily run까지 최대 하루 |
| 벌크 토글 | `POST /bulk/monitoring` → SQS `toggle_monitoring` | 태그·인벤토리를 안 쓰고 알람만 만들어 daily run이 되돌림 |
| 인벤토리 플래그 | discovery(daily)가 태그에서 파생 | 태그로 켠 리소스가 콘솔엔 다음 discovery까지 꺼진 것으로 보임 |
| 고객 규약 | 없음 | 키·값·대소문자·태그 정책 예시가 온보딩 가이드에 없음 |

## 결정

- **D1 권한**: 태깅 statement를 셋으로 나눈다. ① `tag:TagResources`(조건 키 자체가 없음 — RGT는 서비스 액션에 위임하고 조건은
  거기서 평가됨) ② `aws:TagKeys` 조건을 지원하는 서비스 액션 19개에 `Null aws:TagKeys=false` + `ForAllValues:StringEquals
  aws:TagKeys=[Monitoring]` ③ 조건 키를 지원하지 않는 `s3:PutBucketTagging`(태그 셋 전체 교체 — RGT가 `s3:GetBucketTagging`으로
  읽어 합친다)·`route53:ChangeTagsForResource`는 조건 없이, 이유를 주석에. Service Authorization Reference를 액션마다 읽어 확정
  (2026-09-16). API Gateway는 `apigateway:PUT/PATCH/POST`가 이미 같은 조건을 갖는다.
- **D2 정합 런**: 25타입의 CloudTrail 추출기를 만들지 않는다. 대신 **한 시간마다 `mode=tag_reconcile`** — daily 흐름에서 메트릭·
  임계치 알림·런 히스토리를 뺀 것: 인벤토리 동기화(태그 → `monitoring` 플래그, 알람 스냅숏) → 고아 정리(태그 off·삭제 리소스의
  알람 삭제) → 수집기 나열(Monitoring=on) → 리소스별 알람 sync. Scheduler → Orchestrator(`mode` 전달, 계정 팬아웃) → Worker.
  비용은 API 콜 수백/시간·DynamoDB 쓰기 수십/시간으로 사실상 0. 런 히스토리는 쓰지 않는다(시간마다 한 줄씩 daily 목록을 덮는다) —
  `PERF_METRIC reconcile_stage` 로그로 본다. CloudTrail 경로(4타입 즉시)는 그대로 두고 SQS 파라미터 모양을 고친다.
- **D3 벌크**: `POST /bulk/monitoring`은 리소스별 PUT과 **같은 순서**로 간다 — 인벤토리에서 리소스 확인 → 태그 쓰기 → 인벤토리
  플래그 → 알람은 SQS `create_alarms`/`delete_alarms`로 비동기. 워커의 `toggle_monitoring` 액션은 삭제. 요청 계약은
  `{resource_ids, resource_type, monitoring}`, 응답에 `failed`(인벤토리에 없거나 태그 실패) 목록.
- **D4 규약 문서**: 온보딩 가이드에 키 `Monitoring`, 값 `on`/`off`(값은 대소문자 무시, 키는 정확히), `Threshold_*`와의 관계,
  태그 정책 JSON 예시, 삭제 방지 SCP 예시.

## 하지 않는 것

- 인벤토리 오버라이드(읽기 전용 고객용) — 필요해질 때 별건.
- 25타입 CloudTrail 태그 이벤트 추출기 — D2가 대신한다.
- 태그 값 스키마 확장(`on`/`off` 외).
