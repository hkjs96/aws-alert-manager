# 성능 측정 — 무엇을 재고, 어떻게 읽나

이 문서는 **애플리케이션 퍼포먼스**(사용자가 체감하는 UI·API 응답)를 재는 체계를 설명한다.
2026-08-31 이전에는 계측이 전혀 없어 "빨라졌다"는 주장에 근거가 없었다.

## 설계 결정: 왜 커스텀 메트릭이 아니라 로그인가

CloudWatch 커스텀 메트릭(EMF 포함)은 **메트릭당 $0.30/월**이다. 라우트 29개 × 통계 조합이면
월 수십 달러가 되고, 이는 이 시스템 전체 운영비($0.35/월)의 100배다.
Logs Insights는 같은 질문(어느 라우트가 느린가, p95는 얼마인가)에 답하면서
로그 수집 무료 구간(5GB/월) 안에 들어간다 — 실측 수집량은 월 500KB 수준이다.

**결론: 구조화 로그 + Logs Insights 온디맨드 쿼리.** 상시 대시보드가 필요해지면
그때 핵심 지표 3~5개만 EMF로 승격한다.

## 로그 포맷

한 줄 = 고정 마커 + 공백 없는 JSON. Lambda 로그 포맷(TEXT/JSON) 설정과 무관하게
정규식 `parse`로 읽을 수 있다.

```
PERF_METRIC {"metric":"api_request","duration_ms":123.45,"route":"GET /resources","status":200,"cold":false,"bytes":8421}
PERF_METRIC {"metric":"daily_stage","duration_ms":6021.3,"stage":"inventory_sync","account":"self","discovered":33,"ok":true}
PERF_METRIC {"metric":"web_vital","vital":"LCP","page":"/dashboard","value":1234.57,"rating":"good","connection":"4g"}
```

> ⚠️ 마커 `PERF_METRIC`과 **공백 없는 구분자**는 아래 쿼리의 정규식이 의존하는 계약이다.
> `backend/common/perf_log.py`와 `frontend/app/api/vitals/route.ts`가 동일 규약을 쓰며,
> `backend/tests/test_perf_log.py::test_line_is_parseable_by_insights_regex`가 이를 고정한다.

## 무엇을 재나

| metric | 어디서 | 축 | 의미 |
|---|---|---|---|
| `api_request` | api_handler Lambda | `route`, `status`, `cold`, `bytes` | 백엔드 API 처리 시간. 라우트는 `{id}`로 정규화돼 리소스 ID가 축을 오염시키지 않는다 |
| `daily_stage` | daily_monitor Lambda | `stage`, `account`, `ok` + 단계별 건수 | 일일 런의 단계별 소요 (`inventory_sync`, `orphan_cleanup`, `collect_resources`) |
| `web_vital` | Amplify SSR (브라우저 → `/api/vitals`) | `vital`, `page`, `rating`, `connection` | 실사용자 체감 (LCP·INP·CLS·TTFB·FCP + Next.js 하이드레이션) |

## 로그 그룹

| 대상 | 로그 그룹 |
|---|---|
| API | `/aws/lambda/aws-monitoring-engine-api-handler-dev` |
| 일일 런 | `/aws/lambda/aws-monitoring-engine-daily-monitor-dev` |
| Web Vitals | Amplify SSR 컴퓨트 로그 (`/aws/amplify/d2ssyfndl4orxp` 계열 — 콘솔 Hosting → Monitoring에서 확인) |

## 쿼리

### 1. API 라우트별 p50/p95 (콜드 스타트 제외)

콜드 스타트를 섞으면 "느린 API"와 "가끔 느린 초기화"가 구분되지 않으므로 분리한다.

```
fields @timestamp, @message
| filter @message like /PERF_METRIC .*"metric":"api_request"/
| parse @message /"route":"(?<route>[^"]*)"/
| parse @message /"duration_ms":(?<ms>[0-9.]+)/
| parse @message /"status":(?<status>[0-9]+)/
| parse @message /"cold":(?<cold>true|false)/
| filter cold = "false"
| stats count() as n, avg(ms) as avg_ms, pct(ms,50) as p50, pct(ms,95) as p95, max(ms) as max_ms by route
| sort p95 desc
```

### 2. 콜드 스타트 영향

```
fields @timestamp, @message
| filter @message like /PERF_METRIC .*"metric":"api_request"/
| parse @message /"duration_ms":(?<ms>[0-9.]+)/
| parse @message /"cold":(?<cold>true|false)/
| stats count() as n, pct(ms,50) as p50, pct(ms,95) as p95 by cold
```

### 3. 에러율

```
fields @timestamp, @message
| filter @message like /PERF_METRIC .*"metric":"api_request"/
| parse @message /"route":"(?<route>[^"]*)"/
| parse @message /"status":(?<status>[0-9]+)/
| stats count() as total, sum(status >= 500) as errors, sum(status >= 500) * 100.0 / count() as error_pct by route
| sort error_pct desc
```

### 4. 일일 런 단계별 소요 추이

```
fields @timestamp, @message
| filter @message like /PERF_METRIC .*"metric":"daily_stage"/
| parse @message /"stage":"(?<stage>[^"]*)"/
| parse @message /"duration_ms":(?<ms>[0-9.]+)/
| stats avg(ms) as avg_ms, max(ms) as max_ms by bin(1d), stage
| sort @timestamp desc
```

### 5. Web Vitals — 페이지별 p75 (Google 기준선)

Core Web Vitals는 관례적으로 **p75**로 판정한다.
기준: LCP ≤ 2500ms good / ≤ 4000ms needs-improvement, INP ≤ 200ms, CLS ≤ 0.1.

```
fields @timestamp, @message
| filter @message like /PERF_METRIC .*"metric":"web_vital"/
| parse @message /"vital":"(?<vital>[^"]*)"/
| parse @message /"page":"(?<page>[^"]*)"/
| parse @message /"value":(?<v>[0-9.]+)/
| stats count() as n, pct(v,75) as p75, pct(v,95) as p95 by page, vital
| sort vital, p75 desc
```

### 6. Web Vitals — rating 분포 (good/needs-improvement/poor)

```
fields @timestamp, @message
| filter @message like /PERF_METRIC .*"metric":"web_vital"/
| parse @message /"vital":"(?<vital>[^"]*)"/
| parse @message /"rating":"(?<rating>[^"]*)"/
| stats count() as n by vital, rating
| sort vital, n desc
```

## 베이스라인 잡는 법

1. **트래픽을 만든다.** dev는 14일간 API 요청이 3건뿐이라 데이터가 없다. 실제 화면을 몇 분
   돌아다니거나(대시보드 → 리소스 → 상세 → 알람), 부하를 흉내내야 한다.
2. **콜드/웜을 분리해 기록한다** (쿼리 2). 첫 요청은 INIT 비용이 붙는다.
3. **날짜와 커밋을 함께 남긴다.** 아래 표에 append하면 이후 최적화의 전/후 비교가 된다.

### 측정 기록

| 날짜 | 커밋 | 대상 | 지표 | 값 |
|---|---|---|---|---|
| 2026-08-31 | `706b315` | daily run (리소스 33) | 전체 소요 | 17.0s (태그 캐시 이전 22.4s) |
| — | — | API p95 | — | **미측정** — 트래픽 필요 |
| — | — | LCP p75 | — | **미측정** — 트래픽 필요 |

## 비용

- 로그 수집 $0.50/GB. 현재 실측 수집량 258KB/14일 → 계측 추가 후에도 월 1MB 미만 예상.
- Logs Insights 쿼리는 스캔한 데이터 기준 과금이나, 수 MB 규모라 사실상 $0.
- Web Vitals 전송은 페이지뷰당 1요청(sendBeacon). Amplify SSR 무료 구간 50만 요청/월.
  트래픽이 늘면 `WebVitals.tsx`의 `SAMPLE_RATE`를 낮춰 조절한다.
