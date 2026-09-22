---
name: dimension-check
description: 알람 디멘션·메트릭 정의를 바꾼 뒤 검증한다. backend/common/dimension_builder.py를 수정했을 때, backend/common/resource_types/*.py 스펙의 알람 정의(namespace·metric_name·dimension)를 추가·변경했을 때, backend/common/alarm_registry.py를 손댔을 때 사용한다. LB 레벨과 TargetGroup 레벨 메트릭 혼용, 복합 디멘션(ECS·WAF·S3·SageMaker), 글로벌 서비스 리전, TreatMissingData 의도성을 점검한다.
---

# 디멘션 검증

## 읽을 것

- 변경한 `backend/common/resource_types/<type>.py` 스펙의 알람 정의 — **알람 정의가 사는 곳은 여기다**
  (`alarm_registry.py`의 `_NAMESPACE_MAP`·`_DIMENSION_KEY_MAP`·`_METRIC_DISPLAY`는 스펙에서 **파생**된다)
- `backend/common/dimension_builder.py` — 복합 디멘션의 수동 분기
- `docs/ALARM-RULES.md` §6-1 (메트릭별 디멘션 규칙), §8 (글로벌 서비스), §10 (TreatMissingData)

## 점검 항목

1. 메트릭 네임스페이스·디멘션이 AWS 공식 문서와 일치하는가.
2. LB 레벨(`LoadBalancer`)과 TG 레벨(`TargetGroup`+`LoadBalancer`) 메트릭이 섞이지 않았는가 (§6-1).
   NLB TG에 ALB 전용 메트릭을 붙이지 않았는가 (KI-001·KI-002).
3. 글로벌 서비스(S3·CloudFront·Route53)의 리전과 디멘션이 맞는가 (§8).
4. 복합 디멘션(ECS·WAF·S3·SageMaker)이 `dimension_builder.py`에서 처리되는가 — 파생되지 않는다.
5. `treat_missing_data`가 의도적으로 설정됐는가 (Route53·DX·MSK 등, §10).
6. 수집 결과 키가 정의의 `metric_key`(없으면 `metric`)와 같은가.

## 검증

```bash
cd backend && pytest tests/test_dimension_builder.py tests/test_resource_type_registry.py -x -q --tb=short
```
