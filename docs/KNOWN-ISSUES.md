# AWS Monitoring Engine — 알려진 이슈 및 AWS 제약사항

운영 중 발견된 AWS 서비스 제약사항과 그에 따른 엔진 동작을 기록한다.

---

## KI-001: NLB Target Group의 TargetType=alb일 때 메트릭 미발행

### 현상
NLB의 Target Group에 ALB를 타겟으로 등록하면 (TargetType=`alb`),
CloudWatch가 `HealthyHostCount` / `UnHealthyHostCount` 메트릭을 발행하지 않는다.
알람을 생성해도 영구적으로 `INSUFFICIENT_DATA` 상태가 된다.

### 원인 (AWS 공식 문서)
AWS NLB CloudWatch 메트릭 문서에 명시:

> "HealthyHostCount / UnHealthyHostCount statistics do not include
> any Application Load Balancers registered as targets."

NLB → ALB 구성은 L4/L7 계층 브릿지 용도로 사용되며,
ALB 자체가 "호스트"가 아니라 로드밸런서이므로 health count 메트릭 대상에서 제외된다.

### 영향 범위
- NLB TG 중 TargetType=`alb`인 경우에만 해당
- TargetType=`instance` 또는 `ip`인 NLB TG는 정상 동작
- ALB TG는 TargetType과 무관하게 정상 동작

### 엔진 대응 (v20260324d)
1. **Collector** (`common/collectors/elb.py`):
   - `_collect_target_groups()`에서 `tags["_target_type"] = tg.get("TargetType", "instance")` 저장
2. **Alarm Manager** (`common/alarm_manager.py`):
   - `_get_alarm_defs()`: `_target_type == "alb"`이면 빈 리스트 반환 → 알람 생성 스킵
   - `sync_alarms_for_resource()`: `alarm_defs`가 빈 리스트이고 기존 알람이 있으면 전부 삭제

### 참고
- AWS 문서: https://docs.aws.amazon.com/elasticloadbalancing/latest/network/load-balancer-cloudwatch-metrics.html
- 적용 버전: v20260324d
- 관련 코드: `_get_alarm_defs()` TG 분기, `sync_alarms_for_resource()` early-return 삭제 로직

---

## KI-002: NLB TG에 ALB 전용 메트릭 알람 생성 불가

### 현상
NLB에 연결된 Target Group에 `RequestCountPerTarget`, `TargetResponseTime` 알람을 생성하면
`INSUFFICIENT_DATA` 상태가 된다.

### 원인
이 메트릭들은 `AWS/ApplicationELB` 네임스페이스에서만 발행된다.
NLB TG는 `AWS/NetworkELB` 네임스페이스를 사용하므로 해당 메트릭이 존재하지 않는다.

### 엔진 대응 (v20260324b)
- `_NLB_TG_EXCLUDED_METRICS = {"RequestCountPerTarget", "TGResponseTime"}`
- `_get_alarm_defs()`: `_lb_type == "network"`이면 위 메트릭을 제외한 알람 정의만 반환
- NLB TG는 `HealthyHostCount`, `UnHealthyHostCount` 2개 알람만 생성

### 참고
- 적용 버전: v20260324b
- 관련 스펙: `.kiro/specs/tg-alarm-lb-type-split/`

---

## KI-003: ALB ELB5XX 알람 INSUFFICIENT_DATA

### 현상
ALB의 `HTTPCode_ELB_5XX_Count` 알람이 `INSUFFICIENT_DATA` 상태로 유지된다.

### 원인
5XX 에러가 발생하지 않으면 CloudWatch가 해당 메트릭 데이터포인트를 발행하지 않는다.
이는 정상 동작이며, 에러가 발생하면 `ALARM` 또는 `OK` 상태로 전환된다.

### 엔진 대응
- `TreatMissingData="missing"` 설정으로 데이터 없을 때 상태 유지
- 별도 조치 불필요 (정상 동작)

---

## KI-004: CWAgent 미설치 시 Memory/Disk 알람 INSUFFICIENT_DATA

### 현상
EC2 인스턴스에 CloudWatch Agent가 설치되지 않은 경우,
`mem_used_percent` / `disk_used_percent` 알람이 `INSUFFICIENT_DATA` 상태가 된다.

### 원인
Memory/Disk 메트릭은 CWAgent가 수집하여 `CWAgent` 네임스페이스로 발행한다.
에이전트 미설치 시 메트릭 자체가 존재하지 않는다.

### 엔진 대응
- `TreatMissingData="missing"` 설정
- Disk 알람: CWAgent 메트릭이 없으면 `_get_disk_dimensions()`에서 빈 리스트 반환 → 알람 생성 스킵 + 경고 로그
- Memory 알람: 알람은 생성되지만 `INSUFFICIENT_DATA` 상태로 대기 (에이전트 설치 후 자동 활성화)
- CWAgent 설치 가이드: [CWAGENT.md](../CWAGENT.md)
