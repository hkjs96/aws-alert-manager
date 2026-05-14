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
1. **Collector** (`backend/common/collectors/elb.py`):
   - `_collect_target_groups()`에서 `tags["_target_type"] = tg.get("TargetType", "instance")` 저장
2. **Alarm Manager** (`backend/common/alarm_manager.py`):
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

---

## ~~KI-005: Threshold_* 태그에 CloudWatch metric_name 사용 시 동적 알람 중복 생성 방지~~ (해결됨)

> **해결 완료 (Phase 4 Task 16)**: 모든 하드코딩 알람의 `metric` 키를 CW metric_name과 일치시키는 대규모 리네이밍으로 근본 원인 제거.
> `Threshold_CPUUtilization=90` 태그는 이제 직접 하드코딩 필터에 매칭되어 동적 알람이 생성되지 않는다.
> 기존 태그(`Threshold_CPU=90`)는 `_LEGACY_TAG_MAP`으로 계속 지원된다.

### 해결 내용
- `alarm_registry.py`: 모든 alarm def의 `metric_key` 필드 제거, `metric` 필드를 CW metric_name과 동일하게 통일
- `_HARDCODED_METRIC_KEYS`: 내부 키 → CW metric_name으로 전환 (예: `"CPU"` → `"CPUUtilization"`)
- `tag_resolver.py`: `_LEGACY_TAG_MAP` 추가로 기존 `Threshold_CPU` 등 레거시 태그 하위 호환 지원
- `alarm_builder.py`: `_LEGACY_KEY_MAP` + `_resolve_metric_key`에서 기배포 알람 설명의 레거시 키 자동 변환

---

## KI-006: Aurora Serverless v2에서 FreeLocalStorage 메트릭 미발행

### 현상
Aurora Serverless v2 인스턴스(`db.serverless`)에 `FreeLocalStorage` 알람을 생성하면
`INSUFFICIENT_DATA` 상태가 영구적으로 유지된다.

### 원인
`FreeLocalStorage` 메트릭은 프로비저닝 인스턴스(`db.r6g.*`, `db.r7g.*` 등)에서만 발행된다.
Serverless v2는 로컬 임시 스토리지 관리가 다르며, 해당 메트릭을 CloudWatch에 발행하지 않는다.

E2E 테스트(aurora-rds-test 스택, 2026-03-25)에서 `list_metrics` API로 확인:
Serverless v2 인스턴스의 발행 메트릭 목록에 `FreeLocalStorage`가 없음.

### 영향 범위
- Aurora Serverless v2 (`db.serverless`) 인스턴스에만 해당
- 프로비저닝 Aurora 인스턴스(`db.r6g.large` 등)에서는 정상 발행

### 엔진 대응 (v20260326 — rds-aurora-alarm-optimization)
1. **Collector** (`backend/common/collectors/rds.py`):
   - `_enrich_aurora_metadata()`에서 `_is_serverless_v2` 내부 태그를 설정 (`"true"` if `DBInstanceClass == "db.serverless"`)
2. **Alarm Manager** (`backend/common/alarm_manager.py`):
   - `_get_aurora_alarm_defs()`: `_is_serverless_v2 == "true"`이면 `FreeLocalStorageGB` 알람 정의를 제외하고, 대신 `ACUUtilization` / `ServerlessDatabaseCapacity` 알람을 추가
3. **Metric Collector** (`backend/common/collectors/rds.py`):
   - `get_aurora_metrics()`: `_is_serverless_v2 == "true"`이면 `FreeLocalStorage` 메트릭 조회를 스킵

이전 대응(수동 `Threshold_FreeLocalStorageGB=off` 태그)은 더 이상 필요하지 않다.

---

## KI-007: Aurora 라이터 단독 구성에서 AuroraReplicaLagMaximum 메트릭 미발행

### 현상
Aurora 클러스터에 라이터 인스턴스만 있고 리더(replica) 인스턴스가 없으면
`AuroraReplicaLagMaximum` 알람이 `INSUFFICIENT_DATA` 상태가 된다.

### 원인
`AuroraReplicaLagMaximum`은 리더 인스턴스의 복제 지연을 측정하는 메트릭이다.
리더 인스턴스가 없으면 복제 자체가 발생하지 않으므로 CloudWatch에 데이터가 발행되지 않는다.

E2E 테스트(aurora-rds-test 스택, 2026-03-25)에서 확인:
라이터 1개 단독 구성 시 `list_metrics`에 `AuroraReplicaLagMaximum` 없음.

### 영향 범위
- 라이터 단독 구성(리더 0개)에만 해당
- 리더 인스턴스 1개 이상 추가하면 정상 발행

### 엔진 대응 (v20260326 — rds-aurora-alarm-optimization)
1. **Collector** (`backend/common/collectors/rds.py`):
   - `_enrich_aurora_metadata()`에서 `_is_cluster_writer`, `_has_readers` 내부 태그를 설정
   - `_has_readers`: 클러스터 멤버 수 > 1이면 `"true"`, 아니면 `"false"`
2. **Alarm Manager** (`backend/common/alarm_manager.py`):
   - `_get_aurora_alarm_defs()`: `_is_cluster_writer == "true"` & `_has_readers == "false"`이면 `ReplicaLag` 알람 정의를 제외
   - `_is_cluster_writer == "false"`이면 `ReaderReplicaLag` (AuroraReplicaLag) 알람을 대신 추가
3. **Metric Collector** (`backend/common/collectors/rds.py`):
   - `get_aurora_metrics()`: writer-only 클러스터에서 `AuroraReplicaLagMaximum` 메트릭 조회를 스킵

이전 대응(수동 `Threshold_ReplicaLag=off` 태그)은 더 이상 필요하지 않다.

---

## KI-008: DeleteDBInstance 이벤트에서 Aurora 알람 삭제 실패 가능성

### 현상
Aurora 인스턴스가 삭제된 후 CloudTrail `DeleteDBInstance` 이벤트를 Remediation Handler가 수신하면,
`_resolve_rds_aurora_type()`가 `describe_db_instances`를 호출하지만 인스턴스가 이미 삭제되어 API 실패 → `"RDS"` 폴백.
이 경우 `[RDS]` prefix로 알람을 검색하므로 `[AuroraRDS]` prefix 알람을 찾지 못해 삭제하지 못할 수 있다.

### 원인
`_resolve_rds_aurora_type()`는 `describe_db_instances` API로 Engine 필드를 확인하여 Aurora 여부를 판별한다.
인스턴스 삭제 후에는 API가 `DBInstanceNotFound` 에러를 반환하므로 `"RDS"` 폴백이 발생한다.
`_handle_delete()`는 폴백된 `"RDS"` 타입으로 `delete_alarms_for_resource()`를 호출하므로
`[AuroraRDS]` prefix 알람은 검색 대상에서 제외된다.

### 영향 범위
- Aurora 인스턴스 삭제 시 실시간 알람 정리 경로에만 해당
- Daily Monitor의 `_cleanup_orphan_alarms()`가 백업으로 다음 실행 시 정리함 (최대 24시간 지연)

### 현재 대응 (v20260326 — rds-aurora-alarm-optimization에서 수정 완료)
1. **Remediation Handler** (`backend/remediation_handler/lambda_handler.py`):
   - `_resolve_rds_aurora_type()`: `(resource_type, is_fallback)` 튜플을 반환하도록 변경
   - 성공 시 `("AuroraRDS", False)` 또는 `("RDS", False)`, 실패 시 `("RDS", True)`
   - `_handle_delete()`: `is_fallback=True` + DELETE 이벤트 시 `delete_alarms_for_resource(resource_id, "")` 호출 → 전체 prefix(`[RDS]`, `[AuroraRDS]`) 검색으로 알람 삭제
2. **Daily Monitor**: 고아 알람 정리가 백업 경로로 여전히 동작 (최대 24시간 지연)

---

## KI-009: ~~Dynamic Alarm Direction Limitation~~ — **해결됨**

**해결 버전:** phase2 브랜치 (alarm_manager.py `_parse_threshold_tags`)

### 해결 방법

`Threshold_LT_{MetricName}={Value}` 태그 prefix로 `LessThanThreshold` 비교 연산자를 사용할 수 있다.

```
# "낮을수록 위험" 메트릭에 사용
Threshold_LT_BufferCacheHitRatio=90   → BufferCacheHitRatio < 90 시 ALARM
Threshold_LT_FreeConnections=10       → FreeConnections < 10 시 ALARM

# 기존 방식 (높을수록 위험, 기본값)
Threshold_CPU=90                      → CPU > 90 시 ALARM
```

**구현 위치:** `backend/common/alarm_manager.py` `_parse_threshold_tags()` — `LT_` prefix 감지 후 `LessThanThreshold` 반환.
