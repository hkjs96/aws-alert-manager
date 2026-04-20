# /deploy — 테스트 + 배포

> 원본: `.kiro/hooks/deploy-after-tests.json` (postTaskExecution)

아래 절차를 순서대로 실행하라. 각 단계가 실패하면 **즉시 중단**하고 실패 원인을 보고한다.

## 1. Python 전체 테스트

```bash
pytest tests/ -x -q --tb=short
```

## 2. Frontend 테스트 (frontend/ 변경이 있는 경우에만)

```bash
cd frontend && npx vitest --run && npx tsc --noEmit && cd ..
```

## 3. 배포 (사용자에게 확인 후)

**반드시 사용자에게 "배포를 진행해도 되냐"고 물어본 뒤**에만 아래를 실행한다.

1. Python 패키징: `dist/*.zip` 생성 (daily_monitor, remediation_handler, common_layer)
2. S3 업로드: `aws s3 cp dist/*.zip s3://{bucket}/`
3. CloudFormation 스택 업데이트: `aws cloudformation update-stack`

배포 완료 시 스택 상태(`UPDATE_COMPLETE`)를 확인하여 보고한다.
