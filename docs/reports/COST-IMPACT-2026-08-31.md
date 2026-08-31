# 비용 영향 조사 — 2026-08-31 변경분 (운영 비용 전수)

대상: 이번 주(08-25~08-31) main에 반영·배포된 변경 전부 — 성능 배치(GetMetricData·AlarmIndex·batch_writer·
512MB), 주간 메트릭 스냅샷, 그리고 오늘의 5건(레이아웃 스트리밍, alarm_identity, FE 벌크/병렬, RGT 태그 캐시,
Shadow 재보정). 과금 주체를 **고객사 계정**(AssumeRole로 호출되는 CloudWatch/Describe API·알람)과
**우리 관리 계정**(Lambda·DynamoDB·Logs·API GW·Amplify)으로 나눠 본다.

## 0. 결론

1. **알람 비용은 변하지 않는다.** 알람 개수·해상도·구성을 바꾼 변경이 없다(M-of-N은 평가 방식만). 고객사 계정
   기준 리소스 200개 ≈ 알람 710개 ≈ **$71/월** 그대로이며, 이것이 전체 비용의 99%다.
2. **유일한 신규 과금 항목은 GetMetricData**(무료 구간 없음, $0.01/1,000 metrics). 리소스 200개 기준
   **+$0.39/월**(일일 점검 $0.18 + 주간 스냅샷 $0.21) — 알람 비용의 0.5%. 그 대가로 일반 CloudWatch API 요청은
   월 36,660 → 360건(무료 구간이지만 9 TPS 스로틀 여유 확보), 태그 API ~890 → ~8콜(전부 무료 API).
3. **우리 계정 비용은 오히려 감소.** 고객사 10개·리소스 200개 모델 기준 **$0.72 → $0.45/월**
   (Lambda −82%: 메모리 2배지만 실행시간 1/20, Logs −40%, DDB ≈). 절대액이 작아 이 시스템의 본질적 비용은
   "달러"가 아니라 **시간·API 쿼터·고객사 알람 개수**다.
4. **다음 단계(PoC 임계치 적용·태그 인덱스·백필)의 추가 비용 ≈ $0** — 알람 수 불변, PutMetricAlarm/TagResource는
   무료 구간 API. 대안이었던 Anomaly Detection은 알람당 +2 메트릭(**+$0.20/알람 → 700개면 +$140/월**)이라 비권고 근거가 재확인된다.
5. **dev 실측(8월)**: 시스템 몫 **≈ $0.35/월**(CloudWatch $0.10 + Amplify 빌드 $0.24 + DDB/SQS $0.01, Lambda·API GW 무료 구간). 계정 청구액 중 눈에 띄는 CloudTrail $5.86은 다른 프로젝트의 2번째 트레일(`poc-db-drift-trail`)이다.
6. **정리 권고**: Lambda 로그 보존 기간 미설정(무기한) → 30~90일. 금액보다 위생 문제.

## 1. 단가 (us-east-1, 2026-08-31 AWS 공식 페이지 확인)

| 항목 | 단가 | 무료 구간 | 비고 |
|---|---|---|---|
| CloudWatch 알람(표준 해상도) | $0.10/알람메트릭/월 | 10개 | 고해상도 $0.30, 컴포지트 $0.50, Anomaly Detection은 +2 메트릭 |
| CloudWatch API 요청(Describe/Put/GetMetricStatistics/ListMetrics) | $0.01/1,000 | **월 100만 건** | 계정 전체 합산 |
| CloudWatch **GetMetricData** | $0.01/1,000 metrics requested | **없음(항상 과금)** | 쿼리 1건 = 메트릭 1건(통계 5개 초과 시 추가 카운트) |
| Lambda(x86) | $0.20/100만 요청 + $0.0000166667/GB-s | 100만 요청 + 40만 GB-s/월 | INIT 구간도 과금 |
| DynamoDB 온디맨드 | WRU $0.625/100만, RRU $0.125/100만, 저장 $0.25/GB-월 | (프로비저닝 25 WCU/RCU) | 서울 리전은 WRU ≈ $0.78/100만 |
| CloudWatch Logs(Lambda vended) | 수집 $0.50/GB(첫 10TB), 보관 $0.03/GB-월 | 5GB | 보존 기간 미설정 시 무기한 |
| EventBridge Scheduler | $1.00/100만 호출 | **1,400만/월** | 스케줄 3개 → 월 ~40회 |
| API Gateway HTTP API | $1.00/100만 요청 | 100만(신규 12개월) | |
| Amplify Hosting | 빌드 $0.01/분, SSR $0.30/100만 요청 + $0.20/GB-h, 전송 $0.15/GB, 저장 $0.023/GB-월 | 빌드 1,000분·SSR 50만 요청·100 GB-h·전송 15GB(신규 12개월) | |
| RGT `GetResources`/`TagResources`, STS AssumeRole, EC2/RDS/ELB 등 Describe·태그 API | **무료** | — | 오늘 줄인 ~890콜은 원래도 $0 |

## 2. 변경별 영향 (리소스 200개·알람 710개 계정 기준, 월)

| 변경 (커밋) | 과금 주체 | 영향 항목 | 방향 | 규모 |
|---|---|---|---|---|
| GetMetricData record/replay 배치 (`MetricBatch`) | 고객사 | GetMetricStatistics 600콜/일(무료 구간) → GetMetricData 600 metrics/일(과금) | **▲** | **+$0.18** — 유일한 순증. 대신 CW API 쿼터 소모 -18k/월 |
| 주간 메트릭 스냅샷 (`3b0bdaf`) | 고객사 | GetMetricData 710 시리즈×7통계/주 | ▲ | +$0.21 (통계 5개/메트릭 규칙이 적용되면 +$0.06) |
| 주간 메트릭 스냅샷 | 우리 | MetricHistoryTable 쓰기 21k WRU/월 + 저장 91일 ≈ 19MB | ▲ | +$0.02 |
| 런 스코프 AlarmIndex (`72db2a4`) | 고객사 | DescribeAlarms 622 → 12콜/일 | ▼ | 무료 구간 내 $0 → $0 (스로틀 9 TPS 여유) |
| DDB batch_writer + Scan→GSI Query (`8d45742`) | 우리 | 쓰기 항목 수 동일(콜만 감소), 읽기 전체 Scan → 계정별 Query | ▼ | 읽기 RRU −90% (10계정 기준 −$0.15) |
| 워커 256→512MB, 타임아웃 900s | 우리 | 런당 71 GB-s(285s) → 13 GB-s(26s) | **▼** | **−82%** (10계정 −$0.29) |
| 설정 드리프트 / SEV별 M-of-N (`3c519d6`,`0ac4080`) | — | 알람 수·구성 변경 없음(평가 기간만) | = | $0 |
| 레이아웃 Suspense 스트리밍 + GlobalFilterBar 서버 props (`a124dc5`) | 우리 | API GW·api_handler 호출 −2건/페이지 진입(고객사·계정 목록 클라이언트 재fetch 제거); SSR 요청 수 불변 | ▼ | 페이지뷰 200/일 기준 −12k 요청/월 ≈ −$0.02 |
| alarm_identity 듀얼 리드 (`400df67`) | — | CPU 수십 ms | = | $0 |
| 벌크 Enable/Disable 실구현 (`1071369`) | 우리 | 이전엔 가짜 성공(호출 0) → 이제 리소스별 PUT N건(API GW + api_handler ~1s) | ▲ | 100건 벌크 = $0.0001 + Lambda $0.0004. "실제 동작의 대가" |
| CreateAlarm 병렬 POST / RecentAlarms 상한 | — | 요청 수 동일(순서만) | = | $0 |
| RGT 태그 캐시 (`706b315`) | 고객사 | 리소스별 태그 API ~890콜 → GetResources ~8콜 — **양쪽 다 무료 API** | = | $0 (시간 −24%, 실측 dev) |
| Shadow 재보정 (`bce6e84`) | 우리 | 주 1회 MetricHistory Query(대상 시리즈 ~15% ≈ 110건) + 제안 행 ≤ 수십 건(TTL 35일) | ▲ | < $0.01. **CloudWatch 호출 없음 → 고객사 $0** |
| 스케줄 2개 추가(스냅샷·재보정) | 우리 | Scheduler 월 +8회 | = | 무료 구간 |
| Amplify 빌드 | 우리 | 푸시당 빌드 ~3분 × $0.01 (8월 실측 22회 평균 2.8분, 청구 23.5분) | ▲ | 오늘 6회 ≈ $0.18 (무료 1,000분 내면 $0) |

## 3. 규모별 월 비용 (모델)

계정당 리소스 N, 알람 = N × 3.55(레지스트리 29타입 평균 정의 수), 일일 메트릭 점검 3개/리소스, 스냅샷 7통계.
"이전" = 08-25 이전 구조(256MB·리소스별 API), "이후" = 현재 main.

### 3-1. 고객사 계정 (CloudWatch)

| N | 알람 수 | 알람 비용 | 일반 API 요청/월 (이전 → 이후) | GetMetricData/월 (이후) | 총 변화 |
|---|---|---|---|---|---|
| 33 (dev 실제) | 117 | $11.71 | 6,049 → 360 (무료 구간) | 6,484 → **+$0.065** | +0.6% |
| 200 | 710 | $71.00 | 36,660 → 360 | 39,300 → **+$0.39** | +0.6% |
| 1,000 | 3,550 | $355.00 | 183,300 → 360 | 196,500 → **+$1.97** | +0.6% |

일반 API 요청은 고객사가 다른 용도로 100만 건을 소진한 경우에만 과금($0.37/월 @200개)되며, 그 경우 오히려 −$0.36 절감.

### 3-2. 우리 관리 계정 (Lambda + DynamoDB + Logs, 고객사 계정 수 A)

| N | A | 이전 | 이후 | 내역(이후) |
|---|---|---|---|---|
| 33 | 1 | $0.010 | $0.010 | Lambda $0.003 · DDB $0.006 · Logs $0.0005 |
| 200 | 1 | $0.056 | $0.045 | Lambda $0.007 · DDB $0.037 · Logs $0.001 |
| 200 | 10 | $0.72 | **$0.45** | Lambda $0.07 · DDB $0.37 · Logs $0.01 |
| 1,000 | 10 | $2.15 | $2.12 | Lambda $0.23 · DDB $1.85 · Logs $0.05 |

Lambda 무료 구간(40만 GB-s/월)을 적용하면 위 Lambda 항목은 사실상 $0. 여기에 **고정 성격** 항목이 붙는다:
Amplify SSR·전송(트래픽 비례, 소규모면 무료 구간), API Gateway(월 100만 미만이면 ~$1 이하), SNS 알림(이메일
$2/10만 건), CloudTrail 관리 이벤트(첫 사본 무료). 이 시스템의 관리 계정 비용은 **월 한 자릿수 달러**가 상한이다.

## 4. dev 계정 실측 (949501913924, us-east-1, Cost Explorer + CloudWatch 메트릭)

### 4-1. 8월 청구액 중 이 시스템 몫

| 서비스 (Cost Explorer, 2026-08) | 금액 | 사용 유형 | 우리 스택? |
|---|---|---|---|
| AmazonCloudWatch | **$0.102** | GMD-Metrics 4,237건 = $0.042 (일일 점검·스냅샷 검증 런), AlarmMonitorUsage 0.98 알람-월 = $0.06 (검증용 알람 11개 단기) | ✔ |
| AWS Amplify | **$0.236** | BuildDuration 23.5분 = $0.235 (이달 빌드 22회, 평균 2.8분), SSR 컴퓨트 $0.0007, 전송 $0.0004 | ✔ |
| Amazon DynamoDB | $0.002 | WriteRequestUnits 3,735 | ✔ |
| Amazon SQS | $0.005 | 요청 17,454 (FIFO 큐 폴링) | ✔ |
| AWS Lambda / API Gateway | $0 | 무료 구간(14일 daily-monitor 34회·평균 53.5s·512MB ≈ 910 GB-s; API GW 요청 3건) | ✔ |
| **소계 (시스템 몫)** | **≈ $0.35/월** | | |
| AWS CloudTrail | $5.86 | `PaidEventsRecorded` 17개 리전 — **2번째 멀티리전 트레일 `poc-db-drift-trail`**(Control Tower 기본 트레일이 무료 1사본). 우리 템플릿엔 Trail 리소스 없음 | ✘ (musinsa-db-resource-tf) |
| Kiro $100 · Tax $11.4 · KMS $1.95 · Config·GuardDuty·Secrets·Cost Explorer $2.4 | — | 계정 공통 | ✘ |

7월도 동일 패턴(CloudWatch $0.119, DynamoDB $0.002, Amplify $0.003). 즉 **이 시스템의 관리 계정 실측 비용은 월
$0.35 수준이고 그중 2/3가 Amplify 빌드 분**이다. 모델(§3-2, 33개·1계정 $0.01)보다 큰 이유는 Amplify 빌드와
검증용 알람이 모델 밖 항목이기 때문.

### 4-2. 14일 사용량 (08-17 ~ 08-31)

| 항목 | 값 | 해석 |
|---|---|---|
| daily-monitor 호출 34회, 평균 53.5s, 최대 900s, 합 1,820s | 512MB 기준 910 GB-s/14일 → 월 ≈ 2,000 GB-s ≈ $0.03 (무료 40만 GB-s 내) | 최대 900s는 256MB 시절 타임아웃 사고. 08-31 이후 런은 17~22s |
| orchestrator 17회 × 2.5s (128MB) | 5 GB-s | 무시 |
| DynamoDB 14일 소비 | inventory W 1,037 / R 35, monitor-runs W 68 / R 195, metric-history W 98 / R 21 | 월 환산 ≈ 2,600 WRU + 540 RRU ≈ $0.002 |
| CloudWatch Logs 수집(계정 전체) | 258 KB / 14일; 저장 총 3.5 MB(api-handler 1.7 MB, daily-monitor 1.0 MB), 보존 무기한 | 비용 무시 수준(월 $0.0001). R2는 위생 항목 |
| API Gateway HTTP | 3 요청 / 14일 | dev는 UI 사용이 거의 없음 |
| Amplify | 22 빌드, 총 62.5분(청구 23.5분 — 일부 무료 구간) | 푸시당 ~3분 = $0.03 |

### 4-3. 오늘 변경 전후 (로그 실측, 리소스 33개·Monitoring=on 0개)

| 런 | 소요 | 메모리 | 비고 |
|---|---|---|---|
| 08-31 08:17 (identity 배포 후) | 22.4s | 217 MB | 태그 캐시 이전 |
| 08-31 08:42 (태그 캐시 배포 후) | **17.0s** | 269 MB | 프라임 3회 각 1콜, hits=22 negatives=1 |
| 08-31 09:02 재보정 Shadow 수동 실행 | 10.5s | 270 MB | resources=0 → 조회·쓰기 없음 |

## 5. 리스크·정리 권고

| # | 항목 | 내용 | 권고 |
|---|---|---|---|
| R1 | GetMetricData 항상 과금 | 리소스 1,000개 × 고객사 10개면 월 ≈ $20. 알람 비용($3,550)의 0.6%라 수용 범위 | 스냅샷 통계를 7 → 5개(avg/max/min/p95/p99)로 줄이면 −30%. 필요 시 |
| R2 | Lambda 로그 보존 미설정 | 템플릿에 `AWS::Logs::LogGroup`이 없어 자동 생성 그룹은 **무기한** 보관 (dev 실측 3.5 MB — 금액은 무시 수준, 위생 항목) | `RetentionInDays: 30`(dev)/90(prod) 지정 |
| R3 | Amplify 빌드 분 | 푸시마다 ~3분(8월 22회·청구 23.5분 = $0.24, 시스템 비용의 2/3). 무료 1,000분/월 초과 시 $0.01/분 | 문서·백엔드만 바뀐 커밋은 빌드 스킵(`amplify.yml` 조건 또는 브랜치 분리) 검토 |
| R4 | MetricHistory 성장 | TTL 91일로 상한 고정(200개 기준 19MB) | 없음 |
| R5 | Shadow 행 성장 | TTL 35일, 대상 시리즈 ~15%만 기록 | 없음 |
| R6 | 고객사 API 무료 구간 합산 | 우리 몫은 월 ~360건이라 무시 가능 | 없음 |
| R7 | 512MB → 비용 증가 오해 | GB-s는 메모리×시간. 시간이 1/20로 줄어 총 GB-s −82% | (arm64는 별도 결정 — 실익 −20%×극소액) |

## 6. 다음 단계 예상 비용

| 후보 | 고객사 계정 | 우리 계정 | 판정 |
|---|---|---|---|
| P2 PoC — 제안 임계치 실제 적용 | PutMetricAlarm 갱신(무료 구간 API), 알람 수 불변 → **$0** | 없음 | 비용 무관, 오탐 감소 효과만 |
| P1 태그 인덱스 + 백필 | TagResource(알람 태깅, 무료 구간) + 1회 DescribeAlarms 전수 → **$0** | 없음 | 비용 무관 |
| Shadow 제안 API/UI | 없음 | DDB Query 소량 | 비용 무관 |
| (대안) CloudWatch Anomaly Detection 전면 전환 | 알람당 +2 메트릭 = **+$0.20/알람** → 710개 +$142/월, 3,550개 +$710/월 | — | **비권고 유지** |
| (대안) Metrics Insights 알람 | 분석 메트릭 수 과금 — 알람 수가 아니라 스캔 범위 비례 | — | 스펙 정정 항목(`docs/specs/metric-insights-hybrid`) |

## 7. 산식·가정

- 알람 정의 수 3.55/리소스: `backend/common/alarm_registry.py` 29타입 평균(`_get_alarm_defs`). 재보정 대상 비율 15%.
- GetMetricData 카운트: 쿼리 1건 = 1 metric requested. AWS 문구 "메트릭당 통계 5개까지 1건"을 적용하면 스냅샷 7통계는
  2건으로 계산되어 스냅샷 비용은 위 표의 약 30%.
- Lambda 실행시간: dev 실측(리소스 33개 17s)에서 리소스당 +0.08s 선형 외삽. 이전 구조는 roadmap P3 실측(190~380s).
- 로그: 런당 25KB + 0.3KB/리소스. DDB 항목 1KB 이하 가정(WRU 1).
- 모델 스크립트: 세션 스크래치패드 `cost_model.py`(단가 상수·산식 포함) — 필요 시 `scripts/`로 옮겨 유지.
- 리전: 우리 스택 us-east-1 기준. 고객사가 ap-northeast-2여도 CloudWatch 알람·API·GetMetricData 단가는 동일.
