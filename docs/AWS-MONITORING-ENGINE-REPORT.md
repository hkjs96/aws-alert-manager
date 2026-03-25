# AWS Monitoring Engine — 기능 소개 및 테스트 보고서

> 2026-03-25 | v20260324f | us-east-1

---

## Slide 1: AWS Monitoring Engine 개요

### 무엇을 하는가?

AWS 리소스(EC2, RDS, ALB, NLB, TG)에 대한 CloudWatch 알람을 **자동으로 생성·동기화·정리**하는 서버리스 엔진

### 핵심 원칙

- **태그 기반 제어** — `Monitoring=on` 태그만 달면 알람 자동 생성
- **임계치 커스터마이징** — `Threshold_CPU=90` 같은 태그로 개별 조정
- **Zero 수동 관리** — 리소스 생성/삭제/태그 변경 시 알람 자동 반응

### 구성 요소

| 컴포넌트 | 역할 | 트리거 |
|---------|------|--------|
| Daily Monitor | 전체 리소스 스캔 → 알람 생성/동기화 | 매일 00:00 UTC (EventBridge) |
| Remediation Handler | 리소스 변경 이벤트 → 즉시 반응 | CloudTrail 이벤트 (실시간) |
| Common Layer | 공유 모듈 (알람 관리, 태그 해석, 수집기) | Lambda Layer |

---

## Slide 2: 아키텍처

```
┌─────────────────────────────────────────────────────────────┐
│                        EventBridge                          │
│  ┌──────────────┐              ┌──────────────────────┐     │
│  │ Cron 00:00   │              │ CloudTrail Rule      │     │
│  │ (매일)       │              │ (Create/Delete/Tag)  │     │
│  └──────┬───────┘              └──────────┬───────────┘     │
└─────────┼──────────────────────────────────┼────────────────┘
          ▼                                  ▼
┌──────────────────┐              ┌──────────────────────┐
│  Daily Monitor   │              │ Remediation Handler  │
│  Lambda          │              │ Lambda               │
└────────┬─────────┘              └──────────┬───────────┘
         │                                   │
         └──────────┬────────────────────────┘
                    ▼
         ┌─────────────────────┐
         │   Common Layer      │
         │  ┌───────────────┐  │
         │  │ alarm_manager │  │  ← 알람 CRUD + sync
         │  │ tag_resolver  │  │  ← 임계치 조회
         │  │ collectors/   │  │  ← EC2/RDS/ELB 수집
         │  │ sns_notifier  │  │  ← SNS 알림
         │  └───────────────┘  │
         └──────────┬──────────┘
                    ▼
    ┌───────────────────────────────┐
    │  AWS Services                 │
    │  CloudWatch / SNS / EC2 / RDS │
    │  ELB / CloudTrail             │
    └───────────────────────────────┘
```

---

## Slide 3: 태그 기반 알람 제어 — 기본 동작

### Step 1: Monitoring=on 태그 설정

리소스에 `Monitoring=on` 태그만 달면 **기본 알람이 자동 생성**됨

### EC2 기본 알람 예시

| 메트릭 | 기본 임계치 | 알람 이름 예시 |
|--------|-----------|---------------|
| CPUUtilization | >80% | [EC2] my-server CPUUtilization >80% (i-xxx) |
| mem_used_percent | >80% | [EC2] my-server mem_used_percent >80% (i-xxx) |
| disk_used_percent | >80% | [EC2] my-server disk_used_percent(/) >80% (i-xxx) |
| StatusCheckFailed | >0 | [EC2] my-server StatusCheckFailed >0 (i-xxx) |

### Step 2: 임계치 커스터마이징 (선택)

| 태그 | 효과 |
|------|------|
| `Threshold_CPU=90` | CPU 알람 임계치를 90%로 변경 |
| `Threshold_Memory=70` | Memory 알람 임계치를 70%로 변경 |
| 태그 미설정 | 기본값 사용 (80%) |

### 임계치 조회 우선순위

```
태그 (Threshold_CPU=90)  →  환경변수 (DEFAULT_CPU_THRESHOLD)  →  하드코딩 기본값 (80)
```

---

## Slide 4: 지원 리소스 및 기본 알람

### EC2 (4개 메트릭)
CPU, Memory, Disk(경로별), StatusCheckFailed

### RDS (6개 메트릭)
CPU, FreeMemoryGB, FreeStorageGB, Connections, ReadLatency, WriteLatency

### ALB (3개 메트릭)
RequestCount, HTTPCode_ELB_5XX_Count, TargetResponseTime

### NLB (5개 메트릭)
ProcessedBytes, ActiveFlowCount, NewFlowCount, TCP_Client_Reset, TCP_Target_Reset

### TG — Target Group (2~4개 메트릭)
HealthyHostCount, UnHealthyHostCount, RequestCountPerTarget(ALB TG만), TGResponseTime(ALB TG만)

---

## Slide 5: 동적 알람 — Threshold_* 태그로 자유롭게 추가

### 하드코딩 목록에 없는 메트릭도 태그로 알람 생성 가능

```
EC2 인스턴스 태그:
  Threshold_NetworkIn = 5000000000
  Threshold_NetworkPacketsOut = 1000000
  Threshold_EBSReadOps = 5000
```

### 동작 흐름

```
1. Threshold_* 태그 파싱 → 하드코딩 목록에 없는 메트릭 추출
2. CloudWatch list_metrics API → 네임스페이스/디멘션 자동 해석
3. put_metric_alarm → 알람 생성
```

### 조건
- CloudWatch에 해당 메트릭 데이터가 실제 존재해야 함
- 태그 값은 양의 숫자여야 함

---

## Slide 6: Threshold_*=off — 알람 선택적 비활성화

### 기능 설명

특정 메트릭의 알람을 **명시적으로 끄고 싶을 때** `off` 값 사용

```
EC2 인스턴스 태그:
  Monitoring = on          ← 모니터링 활성화
  Threshold_CPU = off      ← CPU 알람만 비활성화
```

### 동작

| 경로 | off 태그 설정 시 |
|------|-----------------|
| 신규 생성 (create) | 해당 메트릭 알람 생성 스킵 |
| 동기화 (sync) | 기존 알람 자동 삭제 |

### off vs 태그 미설정

| 상태 | 의미 | 결과 |
|------|------|------|
| `Threshold_CPU=off` | 명시적 비활성화 | 알람 생성 안 함 + 기존 알람 삭제 |
| 태그 없음 | 기본값 사용 | 기본 임계치(80%)로 알람 생성 |
| `Threshold_CPU=90` | 커스텀 임계치 | 90%로 알람 생성 |

---

## Slide 7: Sync 동기화 — Daily Monitor의 핵심 로직

### 매일 실행되는 동기화 흐름

```
1. Monitoring=on 리소스 전체 스캔
2. 리소스별 기존 알람 조회
3. 태그 임계치 vs 기존 알람 임계치 비교
   → 동일: ok
   → 변경: updated (재생성)
   → 신규: created
   → 태그 제거: deleted
   → off 설정: deleted
4. 결과 리포트: {created: N, updated: N, ok: N, deleted: N}
```

### Sync 결과 예시

```json
{
  "created": 0,
  "updated": 0,
  "ok": 65,
  "deleted": 0
}
```

---

## Slide 8: 실제 테스트 환경

### 인프라 (us-east-1)

| 리소스 | 이름 | 비고 |
|--------|------|------|
| EC2 #1 | dev-ec2-lab-01 | 동적 태그 다수 설정 |
| EC2 #2 | dev-ec2-lab-02 | off/동적 알람 테스트 대상 |
| ALB | dev-alb-lab | 디멘션 필터링 테스트 대상 |
| NLB | dev-nlb-lab | 동적 태그 설정 |
| TG (ALB) | dev-tg-alb-lab | TG 알람 테스트 |
| TG (NLB) | dev-tg-nlb-lab | TG 알람 테스트 |

### 배포

| 항목 | 값 |
|------|-----|
| CFN 스택 | aws-monitoring-engine-dev |
| 코드 버전 | v20260324f |
| 단위 테스트 | 435 passed |

---

## Slide 9: 테스트 ① 디멘션 필터링 — AZ 자동 제외

### 문제 (Before)

ALB의 `HTTPCode_ELB_4XX_Count` 동적 알람에 **불필요한 AvailabilityZone 디멘션** 포함

```
Before: Dimensions = [LoadBalancer, AvailabilityZone=us-east-1b]
→ 특정 AZ의 4XX만 감지 (전체 ALB 트래픽 미반영)
```

### 수정 후 (After)

`_select_best_dimensions()` 헬퍼가 AZ 없는 조합을 우선 선택

```
After: Dimensions = [LoadBalancer]
→ ALB 전체 트래픽의 4XX 감지 ✅
```

### 테스트 절차 및 결과

| 단계 | 액션 | 결과 |
|------|------|------|
| 1 | 기존 HTTPCode_ELB_4XX_Count 알람 삭제 | — |
| 2 | Lambda invoke → 알람 재생성 | — |
| 3 | 새 알람 디멘션 확인 | LoadBalancer만 포함 ✅ |

---

## Slide 10: 테스트 ② Threshold_CPU=off — 알람 비활성화

### 테스트 절차

| 단계 | 액션 | 결과 |
|------|------|------|
| 1 | dev-ec2-lab-02에 `Threshold_CPU=off` 태그 설정 | — |
| 2 | Lambda invoke (sync) | — |
| 3 | CPU 알람 존재 여부 확인 | CPU 알람 없음 ✅ |
| 4 | 다른 알람 확인 | Memory, Disk, StatusCheck 정상 유지 ✅ |

### 알람 목록 (off 적용 후)

```
[EC2] dev-ec2-lab-02 StatusCheckFailed >0          ← 유지
[EC2] dev-ec2-lab-02 disk_used_percent(/) >0.05%   ← 유지
[EC2] dev-ec2-lab-02 mem_used_percent >80%          ← 유지
(CPU 알람 없음)                                     ← off 적용 ✅
```

### off 태그 제거 후

| 단계 | 액션 | 결과 |
|------|------|------|
| 1 | `Threshold_CPU` 태그 삭제 | — |
| 2 | Lambda invoke | CPU 알람 기본값(80%)으로 복원 ✅ |

---

## Slide 11: 테스트 ③ 동적 알람 — 생성/업데이트/삭제

### 3a. 태그 추가 → 알람 생성

| 단계 | 액션 | 결과 |
|------|------|------|
| 1 | `Threshold_NetworkIn=5000000000` 태그 추가 | — |
| 2 | Lambda invoke | `[EC2] dev-ec2-lab-02 NetworkIn >5000000000` 생성 ✅ |

### 3b. 임계치 변경 → 알람 업데이트

| 단계 | 액션 | 결과 |
|------|------|------|
| 1 | 태그를 `10000000000`으로 변경 | — |
| 2 | Lambda invoke | 알람 임계치 `10000000000`으로 반영 ✅ |

### 3c. 태그 제거 → 알람 삭제

| 단계 | 액션 | 결과 |
|------|------|------|
| 1 | `Threshold_NetworkIn` 태그 삭제 | — |
| 2 | Lambda invoke | NetworkIn 알람 삭제됨 ✅ |

---

## Slide 12: 테스트 결과 종합

### 인프라 테스트 (AWS 실환경)

| # | 테스트 항목 | 결과 |
|---|------------|------|
| 1 | AZ 디멘션 자동 제외 | ✅ PASS |
| 2 | Threshold_CPU=off 비활성화 | ✅ PASS |
| 3a | 동적 알람 생성 (태그 추가) | ✅ PASS |
| 3b | 동적 알람 업데이트 (임계치 변경) | ✅ PASS |
| 3c | 동적 알람 삭제 (태그 제거) | ✅ PASS |

### 단위 테스트

| 항목 | 수치 |
|------|------|
| 전체 테스트 | 435 passed |
| PBT (Property-Based Testing) | 12 파일 |
| 회귀 | 0건 |

---

## Slide 13: 발견 이슈 및 조치

### sync 경로에서 off 태그 처리 누락

| 항목 | 내용 |
|------|------|
| 증상 | `Threshold_CPU=off` 설정 시 CPU 알람이 기본값 80으로 재생성됨 |
| 원인 | `_sync_standard_alarms()`에서 off 체크 없이 임계치 비교 → 숫자 변환 실패 → 기본값 폴백 |
| 영향 | sync 경로에서만 발생 (create 경로는 정상) |
| 수정 | `_sync_standard_alarms()`, `_sync_disk_alarms()` 진입부에 off 체크 추가 |
| 검증 | 435 tests passed + AWS 실환경 재검증 완료 |

---

## Slide 14: 향후 계획

| 항목 | 상태 | 설명 |
|------|------|------|
| EC2/RDS/ALB/NLB/TG 기본 알람 | ✅ 완료 | Monitoring=on 자동 생성 |
| 동적 태그 알람 | ✅ 완료 | Threshold_* 태그 기반 |
| Threshold_*=off | ✅ 완료 | 선택적 비활성화 |
| Sync 동적 알람 | ✅ 완료 | 생성/삭제/업데이트 |
| CREATE 이벤트 즉시 반응 | ✅ 완료 | 리소스 생성 시 알람 즉시 생성 |
| 멀티 리전 지원 | 🔲 예정 | 현재 us-east-1 단일 리전 |
| 알람 대시보드 자동 생성 | 🔲 예정 | CloudWatch Dashboard 연동 |
