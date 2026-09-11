# Phase 2 코드 리뷰 (2026-09-09)

09-09 하루 동안 들어간 것 — 채널 레지스트리·발송·라우터·인시던트·재알림·버스 정책·온보딩 템플릿·설정 화면 — 을
**코드를 직접 읽고** 검토했다. 라이브에서 확인한 사실(dev 스택 파라미터, 상태 머신 정의)은 따로 표시했다.
"동작한다"(09-09 E2E 검증 통과)와 "운영에서 버틴다"는 다르다는 관점에서 봤다.

## 요약

| # | 발견 | 심각도 | 상태 | 근거 |
|---|---|---|---|---|
| H1 | **죽은 실행의 그룹은 끝내 발송되지 않는다** — sweep은 finalize만 하고 Deliver를 부르지 않는다 | 높음 | ✅ `27f20dd` | `alert_group_worker/lambda_handler.py:212-224`, 워커에 라우터 호출 없음 |
| H2 | **인시던트 갱신이 서로 덮어쓴다** — 라우터·ack·재알림이 전부 "읽고-통째로-쓰기", 포인터 생성도 경합 | 높음 | | `alert_router/lambda_handler.py:104-154`, `routes/incidents.py:117-133`, `alert_router:350-378` |
| M1 | 인시던트 해소가 "해소 그룹이 Deliver까지 도달"에만 의존 — 자가 회복 경로 없음 | 중간 | ✅ `27f20dd` | `alert_router:263-266`, `:140` |
| M2 | Deliver 재시도가 스로틀을 못 버틴다 — 예약 동시성 10, `States.ALL` 5s·10s 두 번 → H1로 유실 | 중간 | ✅ `27f20dd` | `template.yaml:873`, `:1071` |
| M3 | 인시던트 축 ≠ 그룹 축 — 미매핑 계정은 전부 `inc##SEV-x` 하나로 뭉치고 H2 경합을 키운다 | 중간 | `common/alert_state.py:66` vs `alert_router:111-113` |
| M4 | 재알림은 등급·고객사만 매칭 — 계정/리소스 타입 조건 채널은 재알림을 못 받는다 | 중간 | `alert_router:418-420`, `notification_channel.py:246-252` |
| M5 | Slack mrkdwn 이스케이프 누락 — 알람 이름에 `<` `>`가 들어간다 | 중간 | `notification_adapters.py:219-240` |
| L1 | 버스 정책 read-back 검증은 일부 인터리빙만 잡는다, 드리프트 점검 없음 | 낮음 | `routes/accounts.py:107-119` |
| L2 | `POST /alert/channels`가 본문 `channel_id`를 받아 조건 없이 put — 기존 채널을 덮어쓴다 | 낮음 | `notification_channel.py:177`, `routes/notification_channels.py:164` |
| L3 | **(라이브)** dev에 `AlertEmailSender`·`AlertConsoleUrl`이 비어 있다 — 이메일 채널은 저장되지만 못 보내고, 알림에 링크가 없다 | 낮음 | `describe-stacks` 실측 |
| L4 | 범용 웹훅: urllib가 리다이렉트를 따라가며 `Authorization`을 들고 https→http로 내려갈 수 있다 | 낮음 | `notification_send.py:56-61` |
| L5 | 잡동사니 — 타임라인 캡이 첫 항목을 버림, 라우터 타임아웃 예산, SES 클라이언트 매 호출 생성 | 낮음 | 아래 |

**잘 된 것** (바꾸지 말 것): claim-then-send로 최대 한 번(`_claim`), 자격증명이 *선언* 하나로 검증·응답 가림·오류 가림까지
같이 움직이는 어댑터 구조, GSI 최종 일관성을 키만 읽고 기본 표에서 일관 읽기로 우회한 것, 버스 정책 read-modify-write,
`__global__` 센티넬, 4xx 무재시도, 확인자를 세션 신원에서만 받는 것, `TestEveryAdapter` 적합성 테스트.

---

## H1 — 죽은 실행의 그룹은 끝내 발송되지 않는다

상태 머신은 `… → Finalize(워커) → Deliver(라우터)`다. 실행이 FAILED/TIMED_OUT/ABORTED로 죽으면
`AlertGroupFailureRule`이 워커의 `sweep`을 부르는데, `sweep`은 **`close` + `finalize`만** 한다
(`alert_group_worker/lambda_handler.py:218-219`). 워커 어디에도 라우터를 부르는 코드가 없다.

즉 F4에서 "죽은 실행을 대신 확정한다"고 한 것은 **이력의 `final_action`을 채운다**는 뜻이지 **알림을 보낸다**는 뜻이
아니다. 구성원은 `final_action=notify`로 남는데 Slack에는 아무것도 안 간다. 화면(F7)은 "알림 대상"이라고 보여 준다.
**가장 조용한 종류의 유실이다** — 실패 알람은 울리지만, 그 뒤 "그래서 그 알림은 갔나"를 아무도 묻지 않는다.

이게 실제로 일어나는 경로: Deliver 단계에서 라우터가 두 번 연속 실패하면(M2 — 스로틀이 가장 흔한 원인) 실행이
FAILED → sweep → 발송 없음.

**고치는 법:** `sweep`이 finalize 뒤에 라우터를 호출한다(`lambda.invoke(InvocationType="Event", Payload={"group": …})`).
라우터는 `_claim`이 있으니 이미 보낸 그룹이면 `already_delivered`로 조용히 끝난다 — 중복 위험 없이 항상 불러도 된다.
워커 역할에 `lambda:InvokeFunction`(라우터 ARN 한정)과 환경변수 `ALERT_ROUTER_FUNCTION`이 필요하다.
테스트: sweep 뒤 라우터 호출 페이로드가 그룹을 담는지, 이미 배달된 그룹은 두 번 안 가는지.

## H2 — 인시던트 갱신이 서로 덮어쓴다

인시던트 표에 쓰는 곳이 셋이고 전부 **읽고 → 메모리에서 바꾸고 → 통째로 쓴다**:

| 쓰는 곳 | 방식 | 코드 |
|---|---|---|
| 라우터 `_sync_incident` | `get_item` → `merge_events`/`resolve` → **`put_item`** | `alert_router:125, 144` |
| API `ack_incident` | `get_item` → `acknowledge` → **`put_item`** | `routes/incidents.py:117, 133` |
| 재알림 `_claim_renotify` | Scan 결과 → `SET renotified_at, timeline = :전체` (조건은 `renotified_at`만) | `alert_router:361-373` |

같은 축의 실행이 겹치는 건 예외가 아니라 **일상**이다: 그룹은 `group_wait` 뒤에 닫히고 새 이벤트는 새 그룹을 여는데,
앞 그룹은 Grace → Collect → **PauseWait(auto-pause, 분 단위)** → Finalize → Deliver를 아직 돌고 있다. 폭풍 중에 사람이
확인 버튼을 누르는 것도 정확히 이 시점이다.

일어나는 일:

- **확인 소실.** 사람이 ack(put) → 라우터가 그 직전에 읽은 사본에 새 발화를 합쳐 put → `status`가 `triggered`로
  되돌아가고 `acknowledged_by`·`mtta_sec`이 사라진다. 화면에서 "확인됨"이 잠깐 보였다가 풀린다. 재알림 대상에서도 빠진다.
- **구성원 소실.** 반대 순서면 ack의 put이 라우터가 방금 더한 구성원을 지운다. `should_resolve`는 **남은 구성원만**
  본다(`incident.py:147-150`) → 아직 울리는 알람이 있는데 사건이 해소된다. MTTR이 거짓이 된다.
- **포인터 경합.** 두 실행이 동시에 포인터를 읽고(없음) 각자 `new_incident` → 각자 put. 같은 초면 `new_incident_id`가
  같아(`incident.py:43-46`, 초 단위 stamp) 뒤 것이 앞 것을 덮고, 다른 초면 사건이 둘 생기고 포인터는 마지막 것만
  가리킨다. 밀려난 사건은 **영원히 `triggered`** 로 남는다 — 아무도 가리키지 않아 해소도 병합도 안 된다.
- **재알림 타임라인 덮어쓰기.** `_claim_renotify`는 Scan 시점의 타임라인 전체를 `SET`한다. 그 사이 라우터가 더한
  `alarm` 항목이 사라진다. (재알림 자체의 중복은 `renotified_at` 조건으로 막혀 있다 — 그건 맞다.)

**고치는 법** — 인시던트 모듈이 순수(dict → dict)라는 장점은 유지하면서 **낙관적 잠금**을 붙인다:

1. 항목에 `version`(정수)을 둔다. 세 쓰기 모두 읽은 `version`을 조건으로 건다:
   `ConditionExpression: version = :read` (새 항목은 `attribute_not_exists(incident_id)`), `SET version = :read + 1`.
   `ConditionalCheckFailedException`이면 다시 읽고 다시 적용한다(최대 3회). 이 재시도는 `_sync_incident`·`ack_incident`
   에서 각각 감싼다.
2. 포인터 생성은 `put_item(ConditionExpression=attribute_not_exists(state_key))`. 실패하면 **그 포인터가 가리키는
   사건에 합친다** — 새 사건을 만들지 않는다.
3. `_claim_renotify`는 타임라인을 `list_append`로 붙이거나, 1번의 버전 조건에 얹는다.

테스트: 가짜 표가 `version` 조건을 흉내 내게 하고, "읽은 뒤 다른 쓰기가 끼어든" 시나리오를 ack·라우터·재알림 각각에
넣는다. 라이브 프로브: 같은 축에 알람 두 개를 2초 간격으로 울리고 그 사이 ack — 사건이 하나이고 확인이 남는지.

## M1 — 인시던트 해소가 Deliver 도달에만 의존한다

`deliver_group`은 `final_action == notify`인 구성원이 없으면 **인시던트를 건드리기 전에** 돌아간다
(`alert_router:263-266`). 해소 판정(`_open_fingerprints` → `should_resolve`)은 오직 해소 이벤트가 담긴 그룹이
Deliver까지 **성공적으로** 도달했을 때만 돈다(`:140`).

설계상 해소 이벤트는 발화를 알렸으면 항상 `NOTIFY/cleared`이므로(`alert_suppression.py:189`) 정상 경로에서는 맞다.
문제는 그 그룹이 죽었을 때(H1)다. 그러면 원인 알람은 OK로 돌아왔는데(`fp#`의 `episode_open=False`) 사건은 열린 채다:

- 확인된 사건이면 **매시간 영원히 재알림**된다(`needs_renotify`는 상태만 본다). 사람이 할 수 있는 건 없다 — 해소 API가 없다.
- 확인 안 된 사건이면 다음 발화가 옛 사건에 합쳐진다. MTTA·MTTR이 옛 시각 기준으로 계산된다.

**고치는 법:** 5분 주기 실행(`renotify_due`)을 **정합성 회복 틱**으로 넓힌다. Scan 필터를 `status <> resolved`로 바꾸고,
열린 사건마다 `_open_fingerprints(members)`를 확인해 하나도 안 열려 있으면 `resolve` + 포인터 삭제. `fp#`가 진실의
원천이므로 이 판정은 Deliver 경로와 같은 근거를 쓴다. 비용: 열린 사건 수 × 구성원 수만큼의 GetItem, 5분마다 — 무시할 수준.
H1을 고쳐도 이건 남겨야 한다 — 이벤트 유실·버그·수동 삭제 어떤 원인이든 5분 안에 스스로 맞춰지는 경로가 하나는 있어야 한다.

## M2 — Deliver 재시도가 스로틀을 못 버틴다

라우터는 `ReservedConcurrentExecutions: 10`(`template.yaml:873`)이고 Deliver의 재시도는
`States.ALL, 5s, MaxAttempts 2, BackoffRate 2`(`:1071`) — 즉 5초 뒤, 10초 뒤 두 번이다. 재알림 틱도 같은 함수를 쓴다.

폭풍에서 그룹은 고객사×계정×등급마다 하나씩 열린다. 고객사 20곳 × 등급 2~3개면 동시 실행 40~60개가 Deliver에
들어오고, 라우터는 채널마다 최대 16.5초(3회 × 5초 + 백오프)를 붙잡을 수 있다. 11번째부터는
`Lambda.TooManyRequestsException` → 15초 안에 두 번 다 실패 → 실행 FAILED → **H1** → 유실. 정확히 알림이 가장
필요한 순간에 가장 많이 잃는다.

**고치는 법:** Deliver에 스로틀 전용 재시도를 `States.ALL` 앞에 둔다 —
`ErrorEquals: [Lambda.TooManyRequestsException, Lambda.ServiceException, Lambda.AWSLambdaException, Lambda.SdkClientException]`,
`IntervalSeconds 10, MaxAttempts 6, BackoffRate 2`(최대 ~10분). 예약 동시성도 10은 낮다 — 바깥 호출을 묶는 목적이면
30 정도가 맞고, Slack 속도 제한은 어차피 채널당 429 재시도로 흡수된다. `AlertRouterErrorsAlarm`에 `Throttles` 지표도 넣는다.

## M3 — 인시던트 축 ≠ 그룹 축

그룹 키는 `{customer_id or account_id}#{severity}`(`alert_state.py:66`, F5) — 미매핑 계정은 계정별로 나뉜다.
인시던트 포인터는 `{customer_id}#{severity}`(`alert_router:111-113`)를 **그룹 항목의 `customer_id`에서 다시** 만든다.
미매핑 계정은 `customer_id`가 비어 있으므로 포인터가 전부 `inc##SEV-3`이 된다.

결과: 미매핑 계정 여럿의 알람이 사건 하나로 뭉친다(F5가 그룹에서 막은 바로 그 현상). 게다가 이 계정들의 그룹은
서로 다른 실행이라 **동시에** 같은 포인터를 두고 H2의 경합을 벌인다. 재알림도 `_channels("")` → 전역 채널만 본다.

**고치는 법:** 포인터 축을 그룹이 이미 갖고 있는 `group["group_key"]`로 한다. 사건에는 `customer_id`(비어 있을 수 있음)와
`account_id`를 따로 저장한다. `new_incident_id`도 같은 축으로.

## M4 — 재알림은 등급·고객사만 매칭한다

`renotify_due`는 `select(channels, {"severity", "customer_id"})`로 채널을 고른다(`alert_router:418-420`).
`matches`는 조건 축이 있으면 이벤트의 그 값이 목록에 있어야 하는데(`notification_channel.py:251`), 이벤트에 `account_id`·
`resource_type`이 없으니 `""`이 되어 **조건이 있는 채널은 전부 탈락**한다. "계정 111만" 또는 "RDS만"으로 좁힌 채널은
첫 알림은 받고 재알림은 못 받는다. 조건 채널만 가진 고객사는 재알림 기능이 없는 것과 같다.

**고치는 법:** 사건에 구성원의 `account_ids`·`resource_types`를 집합으로 누적해 두고(merge 시), 재알림 매칭은
"채널 조건 값 중 하나라도 사건의 집합에 있으면 통과"로 한다. `matches`에 집합 값을 받는 분기를 더하면 된다.

## M5 — Slack mrkdwn 이스케이프 누락

`_render_slack`은 `summary_line()`·`reason`을 그대로 넣는다(`notification_adapters.py:220-231`). Slack은 `&` `<` `>`를
제어 문자로 읽는다 — `<…>`는 링크/멘션으로 파싱되고 사라질 수 있다. 우리 알람 이름은 **비교 연산자를 포함하도록
만들어져 있다**: `[EC2] i-1 CPUUtilization > 80%`, `FreeStorageSpace < 10GB`. 09-09 라이브 검증은 `>`만 있는 이름이라
통과했고, `<`가 있는 이름(`<`부터 다음 `>`까지)은 확인된 바 없다. `state_reason`에는 CloudWatch가 `[…]`·`(…)` 외에
임의 문자열을 넣는다.

**고치는 법:** `_render_slack`에 `&→&amp;`, `<→&lt;`, `>→&gt;` 치환을 넣는다(URL 링크 `<url|자세히 보기>`는 치환 뒤에
붙인다). 어댑터 적합성 테스트에 `<`가 있는 제목이 페이로드에 원형으로 남지 않는지 추가.

## L1 — 버스 정책 검증의 한계

`_grant_alert_forwarding`은 쓰기 뒤 다시 읽어 **자기가 읽었던 Sid + 자기 Sid**가 남았는지 본다(`routes/accounts.py:113-118`).
이 검사가 잡는 인터리빙은 "내 쓰기와 내 read-back 사이에 남이 덮었다"뿐이다. 다음은 못 잡는다:

    A 읽음(∅) → B 읽음(∅) → A 씀[A] → A 확인 ✓ → B 씀[B] → B 확인 ✓ (B가 읽은 건 ∅였으니 missing=∅)

A의 권한이 사라지고 **둘 다 `granted`** 다. 관리자 둘이 1초 안에 계정을 등록해야 하니 드물지만, 드러나는 방식이
"그 계정 알람이 안 온다"라 P3에서 막으려던 바로 그 실패다.

**고치는 법:** 완벽한 잠금 대신 **드리프트 점검**을 둔다 — 계정 표의 계정 집합과 버스 정책의 Sid 집합을 비교해 빠진 걸
다시 붙이고 로그로 남긴다. M1의 5분 틱에 얹으면 된다(권한: `events:DescribeEventBus`·`PutPermission`을 라우터에
주기보다 워커나 별도 함수가 낫다 — 결정 필요). 부수: `ForAllValues:StringEquals`는 키가 없으면 통과한다. `PutEvents`는
`source`·`detail-type`이 필수라 실제로 뚫리진 않지만, 단일값 키 `events:source`는 `StringEquals`가 정확하다.

## L2 — 채널 생성이 기존 채널을 덮어쓴다

`validate_channel`은 본문의 `channel_id`를 받아들이고(`notification_channel.py:177`), `create_channel`은 조건 없이
`put_item`한다(`routes/notification_channels.py:164`). 같은 고객사에서 기존 ID로 POST하면 그 채널의 설정·자격증명이
통째로 바뀐다. 화면은 ID를 안 보내니 UI로는 못 하지만, API 계약상 POST가 PUT 노릇을 한다.

**고치는 법:** 생성 경로에서 본문 `channel_id`를 무시하거나, `ConditionExpression=attribute_not_exists(channel_id)`로
409를 낸다. 후자가 계약이 분명하다.

## L3 — (라이브) dev의 발송 파라미터가 비어 있다

`describe-stacks` 실측: `AlertEmailSender=""`, `AlertConsoleUrl=""`, `AdminEmails`는 설정됨.

- 이메일 채널은 카탈로그(`/alert/channel-types`)에 뜨고 저장도 되지만, 발송 시 `보내는 주소가 설정되지 않았습니다`로
  즉시 실패한다(`notification_send.py:112`). 실패는 `delivery_results`에만 남는다 — 설정 화면은 모른다.
- 알림에 "자세히 보기" 링크가 없다. 사건 ID는 찍히지만 클릭할 곳이 없다.

**고치는 법:** `list_types`가 어댑터의 **가용 여부**를 같이 내보내고(`ses_email`은 `ALERT_EMAIL_SENDER`가 있어야 가용),
화면은 불가용 유형을 비활성으로 그린다. dev에는 Amplify URL을 `AlertConsoleUrl`로 넣는다. `AlertEmailSender`는 SES
검증이 선행돼야 하므로 사용자 결정.

## L4 — 범용 웹훅의 리다이렉트

`urllib.request.urlopen`은 기본으로 리다이렉트를 따라가고, 그때 `Authorization` 헤더를 그대로 들고 간다. https로
검증한 URL이 http로 302하면 토큰이 평문으로 나간다. 사용자가 자기 URL을 넣는 것이니 위협 모델은 좁지만, 자격증명을
응답에서도 로그에서도 가리는 정책과 어긋난다.

**고치는 법:** 리다이렉트를 따르지 않는 opener(`HTTPRedirectHandler`를 뺀 `build_opener`)를 쓰고 3xx는 실패로 기록한다.

## L5 — 잡동사니

- **타임라인 캡이 첫 항목을 버린다.** `_capped`는 뒤 100개만 남긴다(`incident.py:107-108`). 폭풍이 길면 `triggered`
  항목이 사라져 화면에서 사건의 시작이 안 보인다. 첫 항목은 고정하고 나머지를 자른다.
- **라우터 타임아웃 예산.** 120초 vs 최악 50채널 × 16.5초. 현실적으론 채널이 서너 개라 괜찮지만, 채널 수 상한(50)과
  타임아웃이 서로를 모른다. 채널당 예산을 남은 시간으로 잘라야 한다(`context.get_remaining_time_in_millis`).
- **SES 클라이언트를 매 호출 만든다**(`notification_send.py:64`). 모듈 수준 캐시로.
- **`list_channels` 스캔**은 모든 고객사의 채널 이름·조건을 보여 준다(자격증명은 안 나간다). 유저별 고객사 스코핑
  (`project_authz_scoping`)이 들어올 때 같이 잠가야 한다.
- **재알림 Scan**은 표가 90일 TTL이라 작지만, 5분마다 전체를 훑는다. 열린 사건만 보는 GSI(`status`)가 더 맞다 — M1로
  틱의 일이 늘면 그때.

---

## 처리 이력

### 1. H1 + M1 + M2 — 발송 내구성 (`27f20dd`, dev `v20260909T075933`)

- **H1** `sweep`이 finalize 뒤 라우터를 비동기 호출한다(`_hand_off_to_router`, 워커에 `lambda:InvokeFunction`
  + `ALERT_ROUTER_FUNCTION`). 구성원이 하나라도 있으면(이미 확정된 행 포함) 넘긴다. 설정이 빠졌으면 `no_router`로
  **크게** 남긴다 — 조용히 넘어가는 것이 이 버그의 본질이었다.
- **M1** 5분 틱이 `tick()`이 됐다: 열린 사건 전부(`status <> resolved`)를 훑어 `fp#`로 원인이 전부 OK면 조건부
  UpdateItem으로 닫는다(타임라인은 `list_append`, 포인터는 이 사건을 가리킬 때만 삭제). 그 **뒤에** 재알림 —
  방금 닫은 사건을 다시 띄우지 않기 위해. 룰의 페이로드(`{"action":"renotify"}`)는 그대로다.
- **M2** Deliver에 `Lambda.TooManyRequestsException`·`ServiceException`·`AWSLambdaException`·`SdkClientException`
  전용 재시도(10s × 6, 최대 ~10분)를 `States.ALL` 앞에. 라우터 예약 동시성 10 → 30, `[AlertRouter] 스로틀` 알람.

**라이브 검증 (dev, 09-09 08:06 UTC):** 알람 발화 → GroupWait 중 `StopExecution` → 실행 `ABORTED` →
워커 `Swept … delivery=handed_off`(08:06:12.205) → 라우터 `claimed:true, sent=1`(08:06:12.571, 366ms 뒤) →
Slack HTTP 200 → 이력 `final_reason=swept:aborted, delivered=True` → 사건 `triggered`. 이후 OK → 정상 Deliver가
사건을 `resolved`(MTTR 45s). 정합성 틱: 원인이 이미 OK인 확인된 사건을 심고 룰 페이로드로 호출 →
`resolved=1`, MTTR 산출, 타임라인 `[triggered, resolved]`, 포인터 제거; 원인이 아직 울리는 사건은 `acknowledged` 유지.
세 함수 로그에 `AccessDenied` 없음. M2는 폭풍이 있어야 실측 가능 — 템플릿·상태 머신 정의로만 확인.

프로브에서 배운 것: `TreatMissingData=notBreaching`인 프로브 알람은 CloudWatch가 ~15초 뒤 **스스로** OK로 되돌린다
(알람 이력 "no datapoints … treated as NonBreaching"). 상태를 붙잡아 두려면 `missing`으로 만들 것.

### 2. H2 + M3 — 인시던트 정합성 (`277af15`, dev `v20260909T085020`)

- **H2** 새 모듈 `common/incident_store.py`: `load()`가 (사건, 버전)을 돌려주고 `save()`는 **읽은 버전일 때만**
  put한다(새 항목 `attribute_not_exists(incident_id)`, 버전 없는 옛 행 `exists & attribute_not_exists(version)`,
  그 밖 `version = n`). 충돌은 `IncidentConflict`. 라우터 `_sync_incident`·API `ack`·재알림 표시가 전부 이걸 쓰고,
  라우터와 ack는 충돌 시 다시 읽어 재적용(3회), 재알림은 이번 틱을 건너뛴다. 정합성 틱의 UpdateItem은
  `ADD version 1`로 다른 쓰기의 버전을 무효화한다. **새 사건은 포인터를 먼저** 조건부로 건다(`_point`: 없었으면
  `attribute_not_exists`, 해소된 옛 사건을 가리켰으면 `incident_id = 본 값`) — 남이 먼저 걸었으면 그 사건에 합친다.
  같은 초 재개방은 1초 뒤 스탬프. `common/incident.py`는 여전히 순수하다.
- **M3** 포인터 축 = `group["group_key"]` 그대로(`pointer_for_axis`), 사건에 `axis`·`account_id` 저장. 매핑된
  고객사는 기존 키와 같아 마이그레이션 없음. 옛 행은 `axis_of()`가 고객사#등급으로 되돌린다.
- 덤: `to_dict`가 `version`을 int로 정규화하지 않아 API가 `"1"`(문자열)로 내보내던 것 — 프로브가 잡았다.

**라이브 검증 (dev, 09-09 09:02 UTC):** ① 실제 DynamoDB에서 버전 조건 6/6 — 옛 행(버전 없음)→0으로 읽고 저장하면 1,
같은 버전 재저장·새 항목 조건·stale 버전 전부 `IncidentConflict`(페이크가 아니라 실물 조건식으로 확인).
② 알람 A 발화 → 사건 v1(`axis=EMU-EM2#SEV-3`, 포인터 일치) → API 확인 v2(MTTA 6s) → 알람 B 발화 → 라우터 병합
후 **`acknowledged` 유지**, 구성원 2, v3 → 둘 다 OK → `resolved`(MTTR 86s) v4, 타임라인
`[triggered, alarm, acknowledged, alarm, resolved]`, 포인터 제거. 사건은 내내 하나. `AccessDenied` 없음.
경합 자체(같은 순간의 두 쓰기)는 라이브로 재현하기 어려워 단위 테스트(`TestIncidentRaces` 6건, ack 경합 3건,
store 9건)로 고정했다.

### 3. M4 + M5 — 재알림 매칭·Slack 렌더링 (`71aa6e2`)

- **M4** `merge_events`가 구성원의 `account_id`·`resource_type`을 `account_ids`·`resource_types` 집합으로 누적하고,
  `match_fields(incident)`가 그 집합을 매칭용 뷰로 낸다. `matches()`는 이벤트 값이 **목록**이면 하나라도 허용 목록에
  있으면 통과(빈 목록은 빈 값과 같다). 재알림은 이 뷰로 채널을 고른다.
- **M5** `_render_slack`이 `& < >`를 이스케이프한다(`_slack_escape`). 링크 문법 `<url|자세히 보기>`는 이스케이프 **뒤에** 붙인다.

**라이브 검증 (dev, 09-09 09:33 UTC):** 계정 조건(`949501913924`) 채널과 RDS 조건 채널을 등록하고, 2시간 전 확인된
사건(구성원 계정 = 우리 계정, 리소스 타입 EC2, 제목 `… < 10GB & > 5%`)을 심어 틱 → `renotified=1, sent=1`(계정 채널만),
사건 `acknowledged` 유지·`version=2`·`resolved=0`. Slack 표시(`<`·`&`·`>` 글자 그대로)는 사용자 확인 대상 —
이스케이프 자체는 단위 테스트가 고정한다.

## 권장 순서

1. ~~**H1 + M1 + M2** — 발송 내구성~~ ✅. 셋이 같은 이야기다: "죽어도 결국 간다, 못 갔으면 5분 안에 스스로 맞춘다."
2. **H2 + M3** — 인시던트 정합성. 버전 조건 + 포인터 조건부 생성 + 축 통일.
3. **M4, M5** — 재알림·Slack 렌더링. 작고 독립적.
4. **L2, L3, L4** — API 계약·dev 파라미터·리다이렉트.
5. **L1, L5** — 드리프트 점검은 M1의 틱에 얹는다.

라이브 재검증은 1·2를 끝낸 뒤 한 번에: 같은 축 알람 2개를 2초 간격으로 + 그 사이 ack, 실행 하나를 강제 중단(`StopExecution`)
→ Slack 도착·사건 단일·확인 유지·5분 내 해소를 본다.
