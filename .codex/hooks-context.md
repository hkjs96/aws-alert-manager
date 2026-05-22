# Codex 에이전트 훅 실행 가이드

자동 훅이 지원되지 않는 Codex 에이전트를 위한 수동 실행 절차.
Claude/Kiro 가 자동으로 처리하는 것을 동등하게 수행해야 한다.

## Phase 1: Pre-Write (작업 시작 전)

**secret-guard (AP-1)**
작성하려는 코드에 다음이 포함되어 있는지 반드시 확인할 것:
- `AKIA` 로 시작하는 AWS Access Key
- `password=`, `secret=`, `token=` 에 리터럴 값
위반 시 Secrets Manager 또는 SSM Parameter Store 사용으로 대체

**governance-remind (§1-§4)**
backend Python 파일 작업 시 아래를 준수할 것:
- `functools.lru_cache` 기반 boto3 싱글턴 (전역 변수 금지)
- import 순서: stdlib → boto3 → common.*
- 복잡도: 로컬 변수≤15, statements≤50, branches≤12, 인자≤5
- `botocore.exceptions.ClientError` 만 catch, `except Exception` 금지
- 로깅: `logger.error("%s", e)` (f-string 금지)

## Phase 2: Post-Write (파일 수정 직후)

**pylint-complexity (§3)** — backend/*.py 수정 시
```bash
cd backend
python -m pylint --disable=all \
  --enable=too-many-locals,too-many-statements,too-many-branches,too-many-arguments \
  --max-locals=15 --max-statements=50 --max-branches=12 --max-args=5 \
  <수정한 파일>
```

**pytest-surgical** — backend/*.py 수정 시
```bash
cd backend
# 수정 모듈명이 foo.py 이면:
pytest tests/test_foo.py -x -q --tb=short
```

**tsc-on-change** — frontend/*.ts/tsx 수정 시
```bash
cd frontend && npx tsc --noEmit
```

**vitest-on-test-change** — frontend/*.test.ts/tsx 수정 시
```bash
cd frontend && npx vitest run
```

## Phase 3: 최종 검증 (커밋 전)

```bash
python scripts/verify_all.py
```

pre-commit 이 설치되어 있으면 `git commit` 시 자동으로 전체 검사가 실행된다.
설치되지 않은 경우 위 스크립트를 수동 실행 후 커밋할 것.

## Phase 4: Post-Commit 배포

`git commit` 및 `git push` 완료 후 배포 대상 변경이면 Codex가 수동 실행:
```bash
python .codex/deploy-backend-stack.py
```
- backend/ 또는 infrastructure/backend/ 변경 → zip → S3 → CFN 배포
- frontend/ 변경 → Amplify start-job 트리거 (`AMPLIFY_APP_ID` 환경 변수 필요)

특정 파일 기준으로 배포할 때:
```bash
python .codex/deploy-backend-stack.py --changed-path backend/daily_monitor/lambda_handler.py
```

설정 기본값:
- stack: `aws-monitoring-engine-dev` (`ALARM_MANAGER_STACK`로 override)
- bucket: `bjs-deploy-bucket` (`ALARM_MANAGER_DEPLOY_BUCKET`로 override)
- profile: `tlsgks678_poc` (`AWS_PROFILE`로 override)
- region: `us-east-1` (`AWS_REGION`로 override)

배포를 일시적으로 비활성화하려면:
```bash
ALARM_MANAGER_AUTO_DEPLOY=0 git commit -m "..."
```
