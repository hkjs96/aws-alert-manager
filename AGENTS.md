# Project: AWS Monitoring Engine (Alert Manager) - Agent Governance

이 파일은 모든 AI 에이전트(Gemini, Claude, Cursor 등)가 프로젝트의 맥락을 이해하고 일관된 품질을 유지하기 위해 반드시 준수해야 하는 **최상위 지침**입니다.

## 1. 프로젝트 개요
- **목적:** AWS 리소스의 메트릭을 모니터링하고 태그 기반으로 알람을 자동 생성/관리하는 시스템.
- **핵심 가치:** 인프라 코드화(IaC), 자동화된 거버넌스, 낮은 운영 부하.

## 2. 에이전트 필수 행동 수칙
1. **Context Awareness:** 작업 시작 전 반드시 해당 영역의 `AGENTS.md`를 읽으십시오.
2. **Surgical Updates:** 코드 수정 시 기존 스타일과 패턴을 엄격히 준수하고, 불필요한 리팩토링은 피하십시오.
3. **Validation First:** 코드 변경 후에는 반드시 통합 검증 스크립트를 실행하십시오:
   - `python scripts/verify_all.py`
4. **Security:** 절대 하드코딩된 시크릿을 추가하지 마십시오. (Secrets Manager/SSM 사용)
   - 검증 스크립트에 포함된 `Secret Leak Guard`를 통과해야 합니다.

## 3. 기술 스택 및 디렉토리 구조
- **Backend:** Python 3.12, Boto3, CloudFormation (`/backend`)
- **Frontend:** Next.js, TypeScript, Tailwind CSS (`/frontend`)
- **Infrastructure:** AWS CDK 또는 Pure CloudFormation (`/infrastructure`)

## 4. 하위 거버넌스 가이드라인
영역별 상세 규칙은 다음 파일을 참조하십시오:
- **백엔드 규칙:** [backend/AGENTS.md](./backend/AGENTS.md)
- **프론트엔드 규칙:** [frontend/AGENTS.md](./frontend/AGENTS.md)
- **알람/리소스 상세 규격:** `docs/specs/` 내 문서 참조

## 5. 공통 안티패턴 (Anti-Patterns)
- **AP-1:** 하드코딩된 시크릿 (AKIA..., password= 등)
- **AP-2:** 모듈 레벨 global 변수로 AWS 클라이언트 관리 (반드시 `lru_cache` 싱글턴 사용)
- **AP-3:** 예외 처리 시 `except Exception` 남용 (구체적인 에러 캐치 권장)
- **AP-4:** 로깅 시 f-string 사용 (Lazy formatting `logger.info("%s", var)` 사용)
- **AP-5:** 페이지네이션(`while True` + `table.query/scan`)을 bare `MagicMock` 테이블로 테스트 (무한 루프·수 GB RSS — mock 메서드를 종료 페이지로 stub: `table.query.return_value = {"Items": []}`. 상세: `backend/AGENTS.md` §3, `.kiro/steering/anti-patterns.md` AP-15)
- **AP-6:** 리소스 식별자(`resource_id`)를 URL path나 API path 세그먼트에 **raw로 삽입**.
  EC2 `i-...`는 슬래시가 없어 우연히 동작하지만 ALB/NLB/TG는 풀 ARN
  (`arn:...:targetgroup/name/hash`)이라 `/`·`:`를 포함한다. 브라우저/CloudFront/
  Next 프록시(`app/api/[...path]`)/API Gateway가 `%2F`를 다시 `/`로 디코딩하면서
  라우터 `[^/]+`가 매칭에 실패해 404가 된다. 반드시 **base64url 토큰**으로 인코딩해
  실어야 한다: 프론트는 `frontend/lib/resource-id.ts`의 `encodeResourceId()`/
  `decodeResourceId()`를, 백엔드는 `_decode_resource_token`(`_path_id`가 자동 적용)을
  사용한다. 토큰은 **가역·타입 무관(type-agnostic)**이라 신규 리소스 타입을 추가해도
  식별자 관련 추가 작업이 없다. (상세: `frontend/AGENTS.md` §5, `backend/AGENTS.md` §5)

## 6. Codex 작업 워크플로 (필수)

Codex는 파일 수정 후 반드시 아래 순서를 완료하고 태스크를 종료하십시오.

```bash
# 1. 검증 (실패 시 중단)
python scripts/verify_all.py

# 2. 변경 파일만 스테이징
git add <수정한 파일들...>

# 3. 커밋
git commit -m "fix|feat|refactor: <한 줄 요약>"

# 4. 푸시
git push origin main
```

**배포는 Codex가 수행할 수 있습니다.** 코드 변경이 배포 대상이고 검증/커밋/푸시가 완료되면 Codex가 배포까지 이어서 진행하십시오.
백엔드/인프라 배포는 Codex 전용 스크립트 `python .codex/deploy-backend-stack.py`를 사용하십시오.
배포 전 `python scripts/verify_all.py`를 통과해야 하며, 필요한 AWS 프로필/리전/스택 이름은 스크립트 기본값 또는 환경 변수로 지정하십시오.
배포 권한 또는 AWS 인증이 없으면 중단하고 사용자에게 필요한 권한/프로필 정보를 요청하십시오.

**pre-push hook이 설치되어 있습니다.** `git push`를 실행하면 backend 테스트가 자동으로 게이트됩니다.
테스트가 실패하면 push가 차단됩니다 — 이 경우 오류를 수정하고 재커밋 후 다시 push하십시오.

---
*이 문서는 프로젝트의 헌법과 같으며, 수정이 필요한 경우 사용자에게 먼저 확인을 받으십시오.*
