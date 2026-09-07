# 구현 계획 — 1.4.2 상태 테이블(D9) → 1.4.3 Grouping(D10)

`review-2026-09-07.md` §7의 "Phase 2 전" 첫 두 항목. 이 둘이 끝나야 발송(Phase 2)을 붙일 수 있다.

| 단계 | 산출물 | 받아들임 기준 (라이브) |
|---|---|---|
| **A. 상태 테이블** | `AlertStateTable`, `common/alert_state.py`, 인제스터 상태 읽기·쓰기 | **25번 토글 → NOTIFY 1건** (지금은 ~10번마다 1건) |
| **B. Grouping** | `grp#` 상태, Step Functions 상태 머신, `alert_group_worker` Lambda | **1분에 500건 → 실행 1개**, 이벤트 전부 `final_action` 기록 |
| C. Auto-pause 값 | Phase 0 실측 후 정책값만 | (B에 메커니즘 포함, 값 0이면 대기 없음) |

---

## A. 상태 테이블 (1.4.2)

### A1. 스키마

```
AlertStateTable   PK state_key (S)   on-demand   TTL ttl

fp#{fingerprint}                                  fingerprint = series_id
  last_notified_at     S  마지막으로 알린(알렸을) 발화 시각
  episode_open         BOOL  ALARM 진입 후 아직 해소 전인가
  episode_started_at   S
  episode_notified     BOOL  현재 에피소드의 발화를 알렸는가  → decide(already_notified=)
  recent_episodes      L[S]  ALARM 진입 시각, 최근 30개·7일 이내만  → is_flapping()
  quarantined_until    S  flapping 격리 종료 시각
  version              N  낙관적 잠금
  ttl                  N  now + 30일 (쓸 때마다 갱신)

grp#{group_key}                                   group_key = "{customer_id}#{severity}"
  status               S  open | closed
  opened_at            S
  execution_arn        S  (StartExecution 뒤에 채움 — 비어 있으면 실행이 없다는 뜻)
  version              N
  ttl                  N  now + 1일
```

### A2. 순수 모듈 `common/alert_state.py`

저장소를 모르는 함수 3개. 인제스터·워커·테스트가 같은 걸 쓴다.

```python
def inputs_from_state(state: dict | None, *, now) -> StateInputs
    # → last_notified_at, is_flapping, already_notified
    # is_flapping = quarantined_until > now  or  is_flapping(len(최근 7일 에피소드), 7)

def apply_event(state: dict | None, ev: AlertEvent, decision: Decision, *, now, policy) -> dict
    # 새 상태. **멱등** — 같은 이벤트를 두 번 넣어도 결과가 같다(타임스탬프 기준 중복 제거).
    #   firing:   recent_episodes에 occurred_at 추가(이미 있으면 무시), episode_open=True
    #             NOTIFY면 last_notified_at=occurred_at, episode_notified=True
    #             DEFER면 episode_notified=False (그룹 실행이 나중에 확정 → write-back)
    #             flapping 새로 감지 시 quarantined_until = now + policy.quarantine_sec
    #   clearing: episode_open=False
    #   그 외(config_change 등): 변경 없음

def group_key(ev: AlertEvent) -> str
```

**멱등이어야 하는 이유:** EventBridge는 at-least-once다. 같은 이벤트가 두 번 와도 에피소드가 두 번 세어지면 flapping 판정이 틀린다.

### A3. 인제스터 흐름 (변경)

```
1. 정규화, severity
2. GetItem fp#          → inputs_from_state()
3. decide(ev, policy, **inputs, now=occurred_dt)
4. UpdateItem fp#  조건: version = 읽은 값 (없었으면 attribute_not_exists)
     ├ 성공 → 5
     └ ConditionalCheckFailed → 같은 지문의 이벤트가 동시에 처리됨. 2로 돌아가 재판정 (최대 3회)
           3회 실패 → NOTIFY로 fail-open + WARN 로그 (알림 유실보다 중복이 낫다 — 현행 원칙)
5. PutItem 이력 (기존과 같음, 무조건 덮어쓰기 — 같은 키·같은 내용이라 안전)
6. (B에서 추가) NOTIFY/DEFER면 그룹 열기
```

**상태를 먼저, 이력을 나중에 쓴다.** 반대로 하면 이력 쓰기 뒤 크래시 → 재시도 → 이력은 이미 있음 → 상태가 영영 갱신 안 됨. 상태 갱신은 A2대로 멱등이라 재시도에 안전하고, 이력 put은 키가 같으니 덮어써도 같다.

**경쟁 조건이 실제로 푸는 것:** 같은 series의 ALARM 2건이 수 초 간격으로 동시 처리되면 지금은 둘 다 NOTIFY다. 조건부 갱신이면 한쪽만 이기고 진 쪽은 재판정에서 `last_notified_at`을 보고 dedup이 된다. Phase 2에서 발송은 이 "이긴 뒤"에만 한다(claim-then-send).

### A4. 없애는 것

- `_last_notified_at()`의 이력 Query(Limit=20) — B1의 원인. 삭제.
- 인제스터 롤의 이력 `dynamodb:Query` — 더 이상 안 쓴다. 대신 상태 테이블 `GetItem`/`UpdateItem`.

### A5. 정책 추가

`SuppressionPolicy`에 `flapping_quarantine_sec` (기본 3600)과 `flapping_window_days` (기본 7). 환경변수 `ALERT_FLAPPING_QUARANTINE_SEC`.

### A6. 테스트

- `test_alert_state.py` — 순수 함수: 전이 표대로, **멱등**(같은 이벤트 2회 = 1회), 30개 상한·7일 창, flapping 감지→격리→격리 만료→재감지, PBT: 임의 이벤트 열에 대해 `apply_event`가 예외 없고 `recent_episodes`가 정렬·중복 없음
- `test_alert_ingestor.py` — 조건부 갱신 실패 → 재판정 → dedup; 3회 실패 → NOTIFY fail-open; **상태 먼저 이력 나중** 순서; 이력 put 실패 시 예외 그대로(기존)
- 라이브: **25번 토글**(ALARM/OK × 25) → NOTIFY 1, dedup 24, cleared 25. 지금 코드로는 NOTIFY 3이 나온다 — 이 차이가 곧 B1이 고쳐졌다는 증거

### A7. 배포·IAM

`AlertStateTable` 신설, `AlertIngestorRole`에 `GetItem`/`UpdateItem`(상태), 이력 `Query` 제거, 환경변수 `ALERT_STATE_TABLE`. 배포 후 `AccessDenied` grep — 지난번 Query 누락과 같은 종류의 실수를 같은 방법으로 잡는다.

---

## B. Grouping + 그룹 단위 타이머 (1.4.3 / 1.4.3b)

### B1. 그룹 열기 (인제스터, A3의 6번)

```
NOTIFY 또는 DEFER일 때만:
  GetItem grp#{key}
  ├ 없음 / closed → PutItem grp# {status: open, opened_at: occurred_at}  조건: 없거나 closed
  │                   ├ 성공 → StartExecution(name=deterministic, input={key, opened_at, customer_id, severity})
  │                   │          → UpdateItem grp# execution_arn
  │                   └ 조건 실패 → 남이 방금 열었다. 아무것도 안 한다
  └ open
      ├ execution_arn 있음 → 아무것도 안 한다 (실행이 깨어날 때 이력에서 읽는다)
      └ execution_arn 없음 → 연 쪽이 StartExecution 전에 죽었다. 내가 StartExecution 시도
```

**실행 이름은 결정적이다:** `{sha1(group_key)[:16]}-{opened_at:%Y%m%d%H%M%S}`. Step Functions는 같은 이름·같은 입력의 StartExecution을 멱등 처리한다(실행 중이면 그 ARN을 돌려줌). 그래서 "연 쪽이 죽음 → 다음 이벤트가 다시 시작"이 안전하다. `#`·공백은 이름에 못 쓰므로 해시한다.

SUPPRESS된 이벤트는 그룹을 열지 않는다 — 억제된 것만으로 실행을 만들면 폭풍의 억제 이벤트 수만큼 실행이 생긴다.

### B2. 상태 머신 (Standard)

```
GroupWait        Wait  $.group_wait_sec         (기본 30, 정책)
CloseGroup       Task  worker: grp# status=closed          ← 조회보다 먼저 닫는다 (B3)
Collect          Task  worker: 이력에서 opened_at 이후 이 그룹의 NOTIFY/DEFER·ALARM 이벤트
NeedPause?       Choice  $.pause_sec > 0 이고 DEFER가 있나
PauseWait        Wait  $.pause_sec
Recheck          Task  worker: 각 지문의 fp# episode_open 확인 → 해소된 것은 final=suppress/auto_pause
Notify           Task  worker: (Phase 2 전까지) 그룹 요약 로그 + 이벤트별 final_action write-back
```

전이 6~8개/그룹. 하루 그룹 500개 기준 월 $3.

### B3. 닫고 나서 조회한다 — 늦게 온 이벤트

조회 → 닫기 순이면 조회와 닫기 사이에 도착한 이벤트는 `grp# open`을 보고 아무것도 안 하는데 실행은 이미 조회를 끝냈다 → **아무도 처리하지 않는다.** 닫기 → 조회 순이면 닫힌 뒤 도착한 이벤트는 새 그룹을 열고, 닫히기 전 도착한 이벤트는 조회에 잡힌다. 빈틈이 없다.

### B4. 워커 `alert_group_worker` (새 Lambda)

인제스터와 분리한다 — 역할이 다르고(이력 Query·UpdateItem, 상태 Get·Update, 인제스터엔 없는 권한) 폭주 시 예약 동시성도 따로 가져가야 한다.

- Collect: GSI `customer_day-index` Query. **날짜 경계**: `opened_at` 날짜 ≠ 지금 날짜면 두 파티션을 읽는다. 필터: `occurred_at ≥ opened_at`, `severity`, `state=ALARM`, `suppressed=false`(= NOTIFY/DEFER).
- Recheck: 지문마다 `fp#` GetItem → `episode_open`이 false면 유예 중 해소된 것.
- write-back: 이력 `UpdateItem` — `final_action`, `final_reason`, `group_id`. **억제율 집계는 `final_action`이 있으면 그것을, 없으면 `suppressed`를 쓴다**(1.5 쿼리에 반영).
- `PERF_METRIC alert_group size=N deferred=M dropped=K wait_sec=…`

### B5. 테스트

- 순수: `group_key`, 실행 이름 규칙(길이·허용 문자), 날짜 경계 파티션 계산
- 인제스터: 그룹 열기 경쟁(조건 실패 → 무동작), `execution_arn` 없는 open 그룹 → StartExecution 재시도, SUPPRESS는 그룹을 안 연다
- 워커: Collect 필터·두 파티션, Recheck에서 해소 지문 제외, write-back 값
- 라이브 1: 이벤트 3건(발화·해소·재발화) → 실행 1, `final_action` 3건
- 라이브 2 (폭풍): 같은 고객사·등급으로 **1분에 500건** → 실행 1개, 이력 500건 전부 `group_id` 동일. 인제스터 스로틀 알람이 울리는지도 본다(예약 50)

### B6. 배포·IAM

- 상태 머신 + 실행 롤(`lambda:InvokeFunction` 워커)
- 인제스터 롤: `states:StartExecution`, grp# Put/Get/Update
- 워커 롤: 이력 Query(GSI 포함)·UpdateItem, 상태 Get/Update
- 워커 `ReservedConcurrentExecutions: 20`
- 환경변수: `ALERT_GROUP_WAIT_SEC`(30), `ALERT_STATE_MACHINE_ARN`

---

## 결정이 필요한 것

### U6. dedup 창의 의미 — 4시간이 맞나

Alertmanager의 `repeat_interval` 4h는 **아직 울리고 있는 알람을 다시 알리는 주기**다. 그런데 CloudWatch는 전이만 보내므로(ALARM→ALARM 재전송 없음) 우리 dedup이 실제로 막는 것은 **해소 뒤 재발화**뿐이다. 라이브 실증이 정확히 그것이었다(발화→해소→재발화 = dedup).

4h면: 10:00 발화(알림) → 10:10 해소 → 10:30 **재발화가 3시간 지속** → 14:00까지 아무도 모른다. 토글 노이즈를 잡으려다 진짜 재발을 묻는다.

**제안:** 메커니즘은 그대로 두고 의미를 둘로 나눈다.
- `repeat_interval_sec` → **재발화 병합 창**: 이 안의 재발화는 같은 에피소드의 연장으로 본다. 기본 **15분**(Phase 0 실측으로 조정 — "해소 후 N분 내 재발화 비율" 표를 추가).
- 4h는 Phase 3의 **미해소 리마인더 주기**로 옮긴다(온콜이 ack 안 한 인시던트 재알림).

flapping 격리(≥3/일)가 반복 토글을 따로 잡으므로 병합 창을 짧게 해도 노이즈가 새지 않는다.

### 기본값 (실측 전 임시)

| 항목 | 값 | 근거 |
|---|---|---|
| `group_wait_sec` | 30 | Alertmanager 기본 |
| `repeat_interval_sec` | 900 (U6 채택 시) / 14400 (현행) | 위 |
| `flapping_quarantine_sec` | 3600 | 임의 — 격리 동안 에피소드는 계속 기록되므로 만료 시 재판정됨 |
| `auto_pause_sec` | {} (없음) | Phase 0 실측 후 |

## 순서와 규모

A(상태) 먼저 단독 배포·검증 → B(그룹). A 없이 B를 하면 `already_notified`·flapping이 계속 비어 있어 그룹 실행이 판정할 재료가 없다. 각각 커밋 2~3개, 배포 1회씩.
