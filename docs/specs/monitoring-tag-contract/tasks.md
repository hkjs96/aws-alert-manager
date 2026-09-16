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
- [x] 6(2026-09-16) **dev 검증** — `f2b940d` → dev `v20260916T071647`. `mode=tag_reconcile` 수동 invoke: status ok, 오류·AccessDenied 0, 단계 inventory_sync 10.0s·orphan_cleanup 0.1s·collect 5.2s·alarm_sync(감시 리소스 0). `simulate-principal-policy`(ApiHandlerRole): lambda:TagResource+TagKeys=[Monitoring] allowed, [CostCenter]·[Monitoring,CostCenter] implicitDeny, sqs:TagQueue·ec2:CreateTags allowed, tag:TagResources·s3:PutBucketTagging(키 없음) allowed. 스케줄 `tag-reconcile-schedule-dev` cron(30 * * * ? *) ENABLED. daily monitor 스모크 status ok·12타입 태그 캐시.
- [x] 7(2026-09-16) **dev 셀프 모니터링 + 라이브 드라이런 골든** — dev 스택 자체 리소스 3개(daily monitor Lambda, remediation DLQ, alert-ingest DLQ)에
      `Monitoring=on`을 RGT `tag_resources`(토글과 같은 호출)로. 태그 뒤 수 초 안에 remediation이 SQS `TagQueue`를 받아 알람 3+3개를 만들었고(D2 수정 라이브 확인),
      `tag_reconcile`이 Lambda 2개를 채워 8개·인벤토리 플래그 3건 on. daily run `processed=3`. 배치 Lambda라 기본 `Duration > 2500ms`가 매 실행 울려
      `Threshold_Duration=60000` 태그 → 다음 정합 런이 알람을 `> 60000ms`로 갱신(`updated=1`). 라이브 드라이런 기준선
      `docs/reports/alarm-dryrun-dev-2026-09-16.json`(리소스 3·알람 8) — 이후 알람 이름·차원 리팩터는 `scripts/alarm_sync_dryrun.py --diff`로 이 골든과 비교.
      비용: 계정 알람 8 → 16(무료 10 초과분 6개, 약 $0.6/월). 관찰: remediation의 create 경로는 기존 알람을 지우고 다시 만든다(정합 런과 겹치면 무해한 재생성).
