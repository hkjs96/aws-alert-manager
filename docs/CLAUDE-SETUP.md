# Claude Code 자동화 셋업

이 저장소는 Claude Code에서 **단계별 수락 없이 자율 워크플로**(테스트 → 커밋 → 푸시까지)로 작업할 수 있도록 설정되어 있다. 다른 PC에서 clone해도 그대로 동작한다.

## 구조

| 파일 | git 추적 | 용도 |
|------|--------|------|
| `.claude/settings.json` | ✅ | 환경 독립 자동화: `defaultMode: "acceptEdits"` + 광범위 `permissions.allow` + Kiro 포팅 hooks |
| `.claude/settings.local.json` | ❌ (`.gitignore`) | 본인 PC 특화: 절대 경로(`/Users/jsb/.aws/**` 등), Lambda 패키징 임시 디렉토리 |
| `.claude/commands/*.md` | ✅ | 팀 공유 슬래시 커맨드 (`/deploy`, `/test`, `/governance-check` 등) |

## 동작

### `defaultMode: "acceptEdits"`
파일 편집(Edit/Write)을 자동 수락. 매번 권한 프롬프트 안 뜸.

### `permissions.allow`
다음 카테고리를 자동 통과시킴:

- **Read-only 셸**: `ls`, `cat`, `grep`, `find`, `git status/log/diff/show`, `jq` 등
- **테스트·빌드**: `pytest`, `npx tsc`, `npx vitest`, `npm test`
- **git 변경**: `git add`, `git commit -m`, `git push origin main`, `git stash`
- **AWS read + 정형화된 update**: CloudFormation describe/update, Lambda update-function-code, S3 cp, Amplify start-job, CloudWatch list-metrics 등
- **Lambda 패키징**: `zip -r api_handler.zip`, `/tmp/api_handler_pkg` 라이프사이클

### Hooks
Kiro에서 포팅된 reminder 기반 hooks. 흐름을 막지 않고 stderr로 안내만:

- **PreToolUse** — `secret-leak-guard`, `governance-check`
- **PostToolUse** — `pylint-on-save`, `typecheck-on-save`, `vitest-on-test-save`, `dimension-check`, `arn-conversion`, `new-collector-checklist`
- **Stop** — `deploy-after-tests`

## 다른 PC에서 셋업

1. 저장소 clone — `.claude/settings.json` + `.gitignore`가 함께 옴
2. 본인 PC 절대 경로가 `/Users/jsb/...`와 다르면 `.claude/settings.local.json`을 본인 환경에 맞게 작성. 예시:

   ```json
   {
     "permissions": {
       "allow": [
         "Read(//Users/<myname>/.aws/**)",
         "Bash(cd /Users/<myname>/workspace/aws-monitoring-engine/frontend && npx tsc:*)"
       ]
     }
   }
   ```

3. 끝. 다음 Claude Code 세션부터 자율 모드.

## 보안

- `permissions.allow`는 이 저장소 범위 안에서만 적용된다. 다른 저장소를 열면 평소대로 단계별 수락 흐름.
- AWS CLI 변경 명령(`aws cloudformation update-stack:*` 등)이 들어가 있다. 이 저장소를 clone하는 사람은 자기 AWS 자격증명으로 해당 명령이 자동 통과됨을 인지해야 한다. 본인이 아닌 팀원에게 공유한다면 보안 정책 검토 후 결정.
- 위험 작업(force push, prod 배포, 데이터 삭제 등)은 여전히 사전 확인하도록 메모리 정책으로 박혀 있음.

## 비활성화

자율 모드를 잠깐 끄려면 `Shift+Tab`을 눌러 모드를 토글하거나, `.claude/settings.json`의 `defaultMode`를 제거.
