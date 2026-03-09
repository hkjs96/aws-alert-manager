# AWS Monitoring Engine

EC2 / RDS / ELB 리소스를 AWS 태그 기반으로 자동 모니터링하는 서버리스 엔진.

- **Daily Monitor**: 매일 09:00 KST에 메트릭 점검 → 임계치 초과 시 SNS 알림
- **Remediation Handler**: CloudTrail 이벤트 감지 → 무단 변경 자동 복구 + 생명주기 알림

배포 방법은 [DEPLOY.md](./DEPLOY.md) 참고.

---

## 모니터링 활성화 방법

리소스에 아래 태그를 붙이면 자동으로 모니터링 대상에 포함됩니다.

| 태그 키 | 값 | 필수 여부 |
|--------|-----|---------|
| `Monitoring` | `on` | **필수** |

`Monitoring=on` 태그가 없으면 어떤 리소스도 수집/알림 대상이 되지 않습니다.

---

## 임계치 태그 (선택)

태그를 붙이지 않으면 CloudFormation 파라미터로 설정한 기본값이 적용됩니다.
리소스별로 다른 임계치가 필요할 때만 아래 태그를 추가하세요.

### EC2

| 태그 키 | 설명 | 기본값 |
|--------|------|-------|
| `Threshold_CPU` | CPU 사용률 임계치 (%) | 80 |
| `Threshold_Memory` | 메모리 사용률 임계치 (%) — CWAgent 필요 | 80 |
| `Threshold_Disk_root` | 루트(`/`) 디스크 사용률 임계치 (%) — CWAgent 필요 | 80 |
| `Threshold_Disk_{경로}` | 특정 경로 디스크 임계치 (%) — CWAgent 필요 | 80 |

**Disk 경로 태그 규칙**

| 경로 | 태그 키 |
|------|--------|
| `/` | `Threshold_Disk_root` |
| `/data` | `Threshold_Disk_data` |
| `/var/log` | `Threshold_Disk_var_log` |

### RDS

| 태그 키 | 설명 | 기본값 |
|--------|------|-------|
| `Threshold_CPU` | CPU 사용률 임계치 (%) | 80 |
| `Threshold_FreeMemoryGB` | 여유 메모리 임계치 (GB, 이 값 미만이면 알림) | 2 |
| `Threshold_FreeStorageGB` | 여유 스토리지 임계치 (GB, 이 값 미만이면 알림) | 10 |
| `Threshold_Connections` | DB 연결 수 임계치 | 100 |

### ELB (ALB)

| 태그 키 | 설명 | 기본값 |
|--------|------|-------|
| `Threshold_RequestCount` | 분당 요청 수 임계치 | 10000 |

### Target Group

| 태그 키 | 값 | 설명 |
|--------|-----|------|
| `Monitoring` | `on` | Target Group 모니터링 활성화 |
| `Threshold_HealthyHostCount` | 숫자 | 정상 호스트 수 임계치 (이 값 미만이면 알림) |
| `Threshold_RequestCount` | 숫자 | 분당 요청 수 임계치 |

---

## 태그 설정 예시

### EC2 — 기본 모니터링만

```
Monitoring = on
```

### EC2 — CPU/메모리 임계치 커스텀

```
Monitoring        = on
Threshold_CPU     = 90
Threshold_Memory  = 85
```

### RDS — 연결 수 임계치 커스텀

```
Monitoring                = on
Threshold_CPU             = 75
Threshold_Connections     = 200
Threshold_FreeStorageGB   = 20
```

---

## SNS 알림 구독

배포 후 아래 SNS 토픽에 이메일 구독을 추가해야 알림을 받을 수 있습니다.

| 토픽 이름 | 알림 종류 |
|----------|---------|
| `aws-monitoring-engine-alert-{env}` | 임계치 초과 알림 |
| `aws-monitoring-engine-remediation-{env}` | 무단 변경 자동 복구 완료 |
| `aws-monitoring-engine-lifecycle-{env}` | 리소스 삭제 / 모니터링 해제 |
| `aws-monitoring-engine-error-{env}` | 시스템 오류 |

---

## Auto-Remediation 동작

`Monitoring=on` 태그가 있는 리소스에 무단 변경이 감지되면 자동으로 조치합니다.

| 리소스 | 감지 이벤트 | 자동 조치 |
|--------|-----------|---------|
| EC2 | 인스턴스 타입/속성 변경 | 인스턴스 중지 |
| RDS | DB 인스턴스 설정 변경 | DB 중지 |
| ELB | 로드밸런서 속성/리스너 변경 | 로드밸런서 삭제 |

> 리소스 삭제(`Monitoring=on` 태그 있는 경우) 또는 `Monitoring` 태그 제거 시에는 SNS 알림만 발송합니다.
