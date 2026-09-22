---
name: premortem-deploy
description: 배포·마이그레이션·벌크 작업을 실행하기 전에 실패 시나리오를 먼저 점검한다. backend/ 또는 infrastructure/ 변경을 배포하려 할 때, CloudFormation 스택을 업데이트할 때, 벌크 알람 작업이나 태그 일괄 변경을 실행할 때, 새 AWS API 호출이나 DynamoDB 연산을 추가했을 때 사용한다. IAM 권한 누락, 조용히 실패하는 경로, 리소스 변형별 메트릭 미발행, 영구 고착(untagged 알람), 리소스 수에 곱해지는 비용, 태그/인벤토리 경계 위반을 다룬다.
---

# 배포 전 사전 부검

## 읽을 것

`guides/OPERATIONS.md`의 **"배포 전 사전 점검 (Premortem)"** 섹션 — 여섯 항목과 각 항목의
근거 사고가 거기 있다. 이 스킬은 항목을 복사하지 않는다.

## 절차

1. 여섯 항목에 **답을 적는다.** "모르겠다"가 하나라도 있으면 배포하지 않고 먼저 확인한다.
2. 항목 1(IAM)에 해당하면 `infrastructure/backend/template.yaml`과, 크로스어카운트면
   온보딩 템플릿 3곳의 diff를 직접 확인한다.
3. 배포 전 `python scripts/verify_all.py`를 통과시킨다.
4. 배포 후 **첫 실행 로그에서 `AccessDenied`를 grep한다** — 코드가 권한 오류를 삼키므로
   기능은 "조용히 동작 안 함"으로 나타난다.
5. 결과 보고는 `task-harness`의 완료 기준을 따른다.

## 배포 권한이 없으면

중단하고 필요한 프로필/권한을 사용자에게 요청한다. 배포 절차 자체는
`guides/OPERATIONS.md`의 Backend Deployment Stack / Backend Lambda Auto Deploy를 따른다.
