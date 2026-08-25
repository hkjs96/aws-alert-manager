# Metric Insights 하이브리드 알람 — 설계 초안 (Draft)

> Status: Draft / 검토 대기
> 목적: 공통 메트릭은 Metric Insights 쿼리 알람으로 통합해 알람 수·sync 부담을 줄이고,
> 리소스별 커스텀이 필요한 알람만 기존 태그 기반 개별 알람으로 유지한다.

## 1. 배경 / 문제

현재 엔진은 **리소스 × 메트릭 = N개**의 개별 CloudWatch 알람을 생성하고,
Daily Monitor가 매일 전체를 스캔하여 태그와 알람 상태를 reconcile 한다.

| 현재 한계 | 영향 |
|----------|------|
| 신규 리소스는 daily sync(최대 24h) 또는 CloudTrail 이벤트가 와야 알람 생김 | 커버리지 지연 |
| 리소스 수에 비례해 알람 개수·관리 비용 선형 증가 | 알람 sprawl, 비용 |
| sync가 Lambda compute에 의존 | 운영 부품/장애 표면 |

경쟁 방식(타팀)은 **Metric Insights 쿼리 알람** 하나로 플릿 전체를 커버하여
신규/삭제 리소스를 자동 탐지한다(compute 0). 단, 쿼리=단일 임계치라 **리소스별 커스텀 임계치는 불가**.

→ 양쪽 장점을 취하는 **하이브리드**가 목표.

## 2. 핵심 아이디어

메트릭을 **2개 트랙**으로 분류한다.

| 트랙 | 대상 | 알람 방식 | 임계치 |
|------|------|----------|--------|
| **Fleet 트랙** | 균일 임계치로 충분한 공통 메트릭 (예: EC2 CPU, RDS CPU) | Metric Insights 쿼리 알람 1개 (`GROUP BY` 리소스 식별자) | 계정/리소스타입 단위 단일값 |
| **Custom 트랙** | `Threshold_*` 태그로 개별 조정된 리소스, 또는 Metric Insights 미지원 메트릭 (Memory %, Disk %, FreeStorage 등 환산 필요 메트릭) | 기존 태그 기반 개별 알람 (현행 유지) | 리소스별 |

### 분기 규칙

```
메트릭이 Metric Insights 지원 네임스페이스/메트릭인가?
  NO  → Custom 트랙 (현행)
  YES → 해당 리소스에 Threshold_<metric> 커스텀 태그가 있는가?
          YES → Custom 트랙 (개별 알람으로 오버라이드)
          NO  → Fleet 트랙 (Metric Insights 쿼리가 커버)
```

→ Fleet 알람은 "커스텀 태그가 없는 리소스"만 대상으로 해야 **이중 알람**을 피한다.
   Metric Insights 쿼리에 `WHERE`로 제외하기 어려우므로, 운영 단순화를 위해
   **1단계에서는 Fleet 트랙을 "기본 임계치 안전망"으로, Custom 트랙을 "오버라이드"로** 양립시키되
   동일 메트릭 중복 알람 발생 시 Custom을 우선(노티 디듀프는 SNS/알람 설명으로 식별)한다.
   (정밀 제외는 2단계 과제 — §7 참조)

## 3. Metric Insights 쿼리 예시

EC2 CPU (리소스별 시계열을 GROUP BY로 펼친 단일 알람):

```sql
SELECT MAX(CPUUtilization)
FROM SCHEMA("AWS/EC2", InstanceId)
GROUP BY InstanceId
```

- CloudWatch 알람은 위 쿼리에 임계치 `> 80`을 걸어 **그룹 중 하나라도 초과 시 ALARM**.
- 신규 인스턴스는 쿼리가 자동 포함, 종료 인스턴스는 자동 제외 → reconcile 불필요.
- 단, "어느 인스턴스가 터졌는지"는 알람 자체로는 모름 → SNS 메시지에서 Metric Insights
  결과를 다시 조회하거나, CloudWatch 콘솔 링크로 안내 (§5 노티 보강).

## 4. 적용 후보 메트릭 (1단계)

| 리소스 | 메트릭 | Metric Insights | 트랙 |
|--------|--------|----------------|------|
| EC2 | CPUUtilization | ✅ AWS/EC2 | Fleet |
| EC2 | StatusCheckFailed | ✅ | Fleet |
| EC2 | mem_used_percent (CWAgent) | ✅ CWAgent | Fleet (단, 태그 오버라이드 잦음) |
| EC2 | disk_used_percent (CWAgent) | △ path 디멘션 | Custom 유지 |
| RDS | CPUUtilization | ✅ AWS/RDS | Fleet |
| RDS | FreeMemoryGB / FreeStorageGB | ✅ but 바이트→% 환산 필요 | Custom 유지 |
| ALB | HTTPCode_ELB_5XX_Count | ✅ AWS/ApplicationELB | Fleet |

> 1단계는 **EC2 CPU + RDS CPU**만 PoC로 적용해 효과/한계 검증 후 확대.

## 5. 구현 영향 범위

| 영역 | 변경 |
|------|------|
| `alarm_registry.py` | 알람 정의에 `track: "fleet" \| "custom"` 필드 추가. Metric Insights 메트릭 화이트리스트 정의 |
| `alarm_builder.py` | Fleet 트랙용 `_create_metrics_insights_alarm()` 추가 (`Metrics`에 `Expression`(쿼리) 단일 항목) |
| `alarm_manager.py` / `alarm_sync.py` | Fleet 알람은 리소스 단위가 아니라 **(account, region, resource_type, metric) 단위 1개**로 관리. sync 시 리소스 루프에서 제외 |
| `daily_monitor` | Fleet 알람은 리소스 수와 무관하게 멱등 보장(이미 있으면 skip). 커스텀 태그 가진 리소스만 개별 sync |
| `template.yaml` | 추가 IAM 불필요(기존 PutMetricAlarm로 충분). SNS 동일 |
| 노티(`sns_notifier`) | Fleet 알람 발화 시 "초과 리소스 목록"을 Metric Insights `GetMetricData`로 재조회해 메시지에 첨부 |

## 6. 비용/효과 추정

- 알람 수: EC2 100대 CPU = 기존 100개 → Fleet 1개 (Metric Insights 알람 단가는 더 높으나 개수 급감으로 순감 예상; PoC에서 실측)
- sync 부하: Fleet 트랙 메트릭은 리소스 루프에서 제외 → daily_monitor 처리량 감소
- 커버리지 지연: 신규 리소스 CPU 알람은 **즉시**(쿼리 자동 포함)

## 7. 미결정 / 리스크

- [ ] **이중 알람 제거**: Custom 오버라이드가 있는 리소스를 Fleet 쿼리에서 제외하는 방법 (Metric Insights `WHERE` + 태그 조인 불가 → 태그 기반 제외는 어려움). 1단계는 중복 허용 + 설명 디듀프.
- [ ] **어느 리소스가 터졌나** 식별: Metric Insights 알람은 그룹 단일 상태만 → 노티 보강 필수.
- [ ] Metric Insights 지원 네임스페이스/메트릭 한계 확인 (CWAgent 커스텀 네임스페이스 GROUP BY 동작 검증 필요).
- [ ] 멀티계정: AssumeRole 후 대상 계정 CloudWatch에서 쿼리 알람 생성 (현 DI 패턴으로 충족).
- [ ] 알람 이름/거버넌스(§6) 포맷을 Fleet 알람에 맞게 확장: `[{type}] {metric} {op}{threshold} (Fleet)`.

## 8. PoC 수용 기준

1. EC2 CPU Fleet 알람 1개로 N대 인스턴스 임계 초과 감지 (신규 인스턴스 자동 포함 확인).
2. `Threshold_CPU=90` 태그 단 인스턴스는 개별 알람으로 오버라이드 동작.
3. 알람 발화 시 SNS 메시지에 초과 인스턴스 ID 포함.
4. 기존 태그 기반 알람 회귀 0건 (435+ 테스트 통과).
