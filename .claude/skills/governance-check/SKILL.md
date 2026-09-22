---
name: governance-check
description: 백엔드 Python 코드의 코딩 거버넌스·안티패턴 준수 검사. backend/ 아래 .py 파일을 작성하거나 수정한 뒤, 또는 사용자가 거버넌스·안티패턴·코드 품질 점검을 요청할 때 사용한다. boto3 클라이언트 lru_cache 싱글턴, import 순서, 함수 복잡도 상한, ClientError만 catch, lazy 로깅, 코드 중복을 검사하고 AGENTS.md의 안티패턴 전체 목록과 대조한다.
---

# 거버넌스 검사

대상: 지정된 Python 파일, 없으면 `git diff --name-only`의 `backend/**/*.py`.

## 규칙은 여기에 없다 — 읽어라

- `backend/AGENTS.md` §1 (boto3 `lru_cache` 싱글턴), §2 (import 순서 stdlib→boto3→common.*),
  §3 (복잡도), §4 (에러 처리·로깅), §5 (리소스 URL 토큰)
- 루트 `AGENTS.md` §5 — **안티패턴 전체 목록(AP-1 이상 전부)**. 번호는 코드 주석·CFN에서
  참조되므로 재배열하지 않는다. 이 스킬은 목록을 복사해 두지 않는다 — 항상 원본을 읽어 대조한다.

## 실행

```bash
pylint --disable=all   --enable=too-many-locals,too-many-statements,too-many-branches,too-many-arguments   --max-locals=15 --max-statements=50 --max-branches=12 --max-args=5 {files}
```

## 출력

위반이 있으면 **파일명:라인:위반 규칙:설명** 형식으로 보고한다.
위반이 없으면 "거버넌스 준수 확인됨"이라고 보고한다.
기존 위반(AP-3·AP-4)이 남아 있는 파일은 **새 위반을 늘렸는지만** 판단한다.
