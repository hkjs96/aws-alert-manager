# Monitoring 태그 계약 — 작업 (2026-09-16)

design.md의 D1~D4. 각 항목은 커밋 하나, 전체 테스트 + dev 배포 + 스모크가 게이트.

- [x] 1(2026-09-16) **권한 조건(D1)** — `infrastructure/customer-onboarding/template.yaml` §3과 `infrastructure/backend/template.yaml`
      ApiHandlerRole의 태깅 statement를 ① `tag:TagResources` ② 조건부 서비스 액션 19개(`aws:TagKeys` = Monitoring만)
      ③ 조건 불가 2개(S3·Route53, 이유 주석)로 분리. 검증: dev ApiHandlerRole에 `iam simulate-principal-policy`로
      `lambda:TagResource` + `aws:TagKeys=[Monitoring]` → allowed, `[CostCenter]` → implicitDeny.
- [x] 2(2026-09-16) **시간 단위 정합 런(D2)** — `daily_monitor._handle_tag_reconcile`(mode=tag_reconcile), 템플릿 `TagReconcileSchedule`
      `cron(30 * * * ? *)`(매시 30분, daily run과 안 겹치게) → Orchestrator `{"mode":"tag_reconcile"}`. remediation `_extract_tags_from_params`가 SQS `TagQueue`(`tags` dict)·
      `UntagQueue`(`tagKeys`)를 읽고, 추가/제거 판정을 Untag 계열 이벤트 집합으로. 테스트: 디스패치·정합 런 단계·SQS 파라미터 모양.
- [x] 3(2026-09-16) **벌크 경로(D3)** — `routes/bulk.py` 태그·인벤토리 동기 처리 후 알람만 SQS. `sqs_worker` `toggle_monitoring` 삭제.
      FE `BulkMonitoringRequest` 타입·PBT, `docs/API-CONTRACT.md` §bulk.
- [x] 4(2026-09-16) **인벤토리 신선도** — D2의 인벤토리 동기화가 맡는다(별도 코드 없음). 정합 런 결과에 `inventory_synced` 포함.
- [x] 5(2026-09-16) **고객 규약 문서(D4)** — `guides/CUSTOMER-ONBOARDING.md`에 "Monitoring 태그 규약" 절: 키·값·대소문자, `Threshold_*`,
      태그 정책 JSON·SCP 예시, IaC(Terraform/CFN) 스니펫. `docs/ALARM-RULES.md`에서 참조.
- [ ] 6 **dev 검증** — 배포 후 `mode=tag_reconcile` 수동 invoke(status ok·오류 0), 권한 시뮬레이션, daily monitor 스모크.
