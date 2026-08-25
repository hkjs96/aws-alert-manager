# Project: AWS Monitoring Engine (Alert Manager) - Agent Governance

이 파일은 이 저장소에서 작업하는 AI 에이전트(기본: Claude Code)가 프로젝트의 맥락을 이해하고 일관된 품질을 유지하기 위해 반드시 준수해야 하는 **최상위 지침**입니다.

## 1. 프로젝트 개요
- **목적:** AWS 리소스의 메트릭을 모니터링하고 태그 기반으로 알람을 자동 생성/관리하는 시스템.
- **핵심 가치:** 인프라 코드화(IaC), 자동화된 거버넌스, 낮은 운영 부하.

## 2. 에이전트 필수 행동 수칙
1. **Context Awareness:** 작업 시작 전 반드시 해당 영역의 가이드(§4)를 읽으십시오.
2. **Surgical Updates:** 코드 수정 시 기존 스타일과 패턴을 엄격히 준수하고, 불필요한 리팩토링은 피하십시오.
3. **Validation First:** 코드 변경 후에는 반드시 통합 검증 스크립트를 실행하십시오:
   - `python scripts/verify_all.py`
4. **Security:** 절대 하드코딩된 시크릿을 추가하지 마십시오. (Secrets Manager/SSM 사용)
   - 검증 스크립트에 포함된 `Secret Leak Guard`를 통과해야 합니다.

## 3. 기술 스택 및 디렉토리 구조
- **Backend:** Python 3.12, Boto3, CloudFormation (`/backend`)
- **Frontend:** Next.js, TypeScript, Tailwind CSS (`/frontend`)
- **Infrastructure:** Pure CloudFormation (`/infrastructure`)

## 4. 하위 거버넌스 가이드라인
영역별 상세 규칙은 다음 파일을 참조하십시오:
- **백엔드 규칙:** [backend/AGENTS.md](./backend/AGENTS.md)
- **프론트엔드 규칙:** [frontend/AGENTS.md](./frontend/AGENTS.md), [frontend/CLAUDE.md](./frontend/CLAUDE.md)
- **알람/네이밍/디멘션/Severity 계약:** [docs/ALARM-RULES.md](./docs/ALARM-RULES.md)
- **기능 스펙 및 백로그:** `docs/specs/` (활성 초안 + `BACKLOG.md`)

## 5. 안티패턴 (Anti-Patterns) — 통합 목록

> 프로젝트 전체에서 금지되는 패턴의 **단일 목록**입니다. 번호는 코드 주석·CFN 템플릿에서
> 참조되므로 변경하지 마십시오. (구 `.kiro/steering/anti-patterns.md`와 구 루트 목록을 통합)

### Python (Backend / Lambda)
- **AP-1:** 하드코딩된 시크릿 (AKIA..., `password=` 등). 환경 변수 / Secrets Manager / SSM 사용.
- **AP-2:** 순환 참조 (Circular Import). 공통 타입/상수는 `common/__init__.py` 또는 별도 모듈로 분리.
- **AP-3:** 알람 이름에서 메트릭/리소스 정보를 **문자열 파싱**으로 추출. 알람 메타데이터(Namespace,
  MetricName, Dimensions, AlarmDescription JSON) 기반으로 매칭한다.
  *(주의: 현재 코드에 위반이 남아 있으며 개선 대상이다 — 새 코드에서 위반을 늘리지 말 것.)*
- **AP-4:** `describe_alarms()` 전체 풀스캔 후 클라이언트 필터링. `AlarmNamePrefix` 등 서버측 필터 사용.
  *(주의: AP-3과 동일하게 기존 위반이 존재. 새 코드에서 금지.)*
- **AP-5:** `except Exception` 남용 (최상위 핸들러 제외). AWS API는 `botocore.exceptions.ClientError`만 catch.
- **AP-6:** 리소스 식별자(`resource_id`)를 URL path나 API path 세그먼트에 **raw로 삽입**.
  EC2 `i-...`는 슬래시가 없어 우연히 동작하지만 ALB/NLB/TG는 풀 ARN
  (`arn:...:targetgroup/name/hash`)이라 `/`·`:`를 포함한다. 브라우저/CloudFront/
  Next 프록시(`app/api/[...path]`)/API Gateway가 `%2F`를 다시 `/`로 디코딩하면서
  라우터 `[^/]+`가 매칭에 실패해 404가 된다. 반드시 **base64url 토큰**으로 인코딩해
  실어야 한다: 프론트는 `frontend/lib/resource-id.ts`의 `encodeResourceId()`/
  `decodeResourceId()`를, 백엔드는 `_decode_resource_token`(`_path_id`가 자동 적용)을
  사용한다. 토큰은 **가역·타입 무관(type-agnostic)**이라 신규 리소스 타입을 추가해도
  식별자 관련 추가 작업이 없다. (상세: `frontend/AGENTS.md` §6, `backend/AGENTS.md` §5)
- **AP-7:** 모듈 레벨 global 변수로 AWS 클라이언트 관리. 반드시 `functools.lru_cache` 싱글턴 사용.
- **AP-8:** 리소스 alive 체크 로직을 `daily_monitor/lambda_handler.py`에 직접 작성.
  각 Collector의 `resolve_alive_ids()`에서 처리한다.
- **AP-22:** 로깅에 f-string 사용. Lazy formatting(`logger.info("%s", var)`)을 사용한다.

### 테스트 (pytest / unittest.mock)
- **AP-15:** 페이지네이션(`while True` + `table.query/scan`)을 bare `MagicMock` 테이블로 테스트.
  `MagicMock().query().get("LastEvaluatedKey")`는 항상 truthy한 자식 mock을 반환해 **무한 루프 +
  수 GB RSS**가 된다. mock 메서드를 반드시 종료 페이지로 stub할 것:
  `table.query.return_value = {"Items": []}` (다중 페이지는 `side_effect` 마지막 페이지에서
  `LastEvaluatedKey` 제거). 페이지네이션 헬퍼를 바꾸면(예: `scan`→`query`) 관련 테스트 mock도
  함께 갱신한다. (상세: `backend/AGENTS.md` §3)

### 알람 태깅 / IAM (짝 규칙)
- **AP-18:** 관리 알람을 **태그 없이 생성/재생성**. daily monitor의 `cloudwatch:DeleteAlarms`는
  `aws:ResourceTag/ManagedBy=AlarmManager` 조건부라, 알람 생성/재생성 경로가 태깅을 빠뜨리면
  알람이 untagged로 남아 임계치 갱신·prune·orphan 정리가 AccessDenied로 영구 고착된다.
  **모든 생성·재생성 경로**(`_create_standard_alarm`/`_create_single_alarm`/
  `_recreate_standard_alarm`/`_recreate_disk_alarm`)에서 put 직후 `_tag_alarm_with_severity`
  호출 필수. 태깅 실패를 조용히 흡수하지 말 것.
- **AP-19:** 알람을 생성하는 **모든 Lambda 롤**에 `cloudwatch:PutMetricAlarm`과 함께
  `cloudwatch:TagResource`(+`ListTagsForResource`)를 부여하지 않는 것. 누락 시 생성 알람이
  전부 untagged가 되어 AP-18과 같은 고착이 발생한다.
- **AP-20:** 배포 Lambda의 boto3에 없는 **최신 API에 정적 폴백 없이 의존** (구버전 → `AttributeError`).
  새 boto3 API는 정적 매핑 폴백 + `(ClientError, AttributeError)` catch.

### TypeScript / Next.js (Frontend)
- **AP-9:** `any` 타입 사용. 명시적 인터페이스/타입을 정의한다.
- **AP-10:** `page.tsx`/`layout.tsx`에 `'use client'` 선언. 상호작용 부분만 별도 Client Component로 분리.
- **AP-11:** DB 레코드 전체를 클라이언트 props로 전달. 필요한 필드만 DTO로 전달한다.
- **AP-12:** 서버 전용 시크릿에 `NEXT_PUBLIC_` 접두사. 서버 전용은 접두사 없이 관리.
- **AP-16:** 모든 요청 실패를 단일 "연결 실패" 메시지로 뭉뚱그리기. HTTP 상태/백엔드 `code`로
  분기해 실제 에러를 노출한다. "상태 조회 요청 실패"와 "job.status === 'failed'"는 서로 다른
  사건이다. (짝: AP-17)
- **AP-17:** DynamoDB 아이템을 `default=str` 없이 `json.dumps` (Decimal → TypeError → 제네릭 500).
  모든 API 라우트는 `json.dumps(item, default=str)`. (짝: AP-16 — 이 500이 UI에서
  "Failed to connect"로 은폐된 사례가 있었다.)
- **AP-21:** 폴링/구독 `useEffect` 의존성에 부모가 매 렌더 새로 만드는 인라인 콜백 포함
  → cleanup+재실행 재구독 무한 루프. 콜백은 `useRef`로 보관하고 의존성에서 제외한다
  (latest-callback 패턴, `SyncProgressModal` 참조).

### 인프라 (CloudFormation)
- **AP-13:** 하드코딩된 리전/계정 ID. Pseudo Parameters(`${AWS::AccountId}`, `${AWS::Region}`) 사용.
- **AP-14:** Lambda 런타임 버전을 함수마다 개별 지정. `Mappings.LambdaConfig.Settings.Runtime`에서 단일 관리.

## 6. 에이전트 작업 워크플로 (필수)

파일 수정 후 반드시 아래 순서를 완료하고 태스크를 종료하십시오.

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

**배포:** 백엔드/인프라 코드가 배포 대상이면 검증/커밋/푸시 완료 후 배포까지 이어서 진행하십시오.
- 자동: Claude Code PostToolUse 훅이 backend Python 변경 시 자동 배포합니다 (`.claude/deploy-backend-stack.py`).
- 수동/CLI: `python scripts/deploy-backend-stack.py` (옵션: `--all-artifacts`, `--changed-path <path>`,
  `--dry-run`; 기본값/오버라이드는 `guides/OPERATIONS.md` 참조).
- 배포 전 `python scripts/verify_all.py`를 통과해야 하며, 배포 권한 또는 AWS 인증이 없으면 중단하고
  사용자에게 필요한 권한/프로필 정보를 요청하십시오.

**pre-push hook이 설치되어 있습니다.** `git push`를 실행하면 backend 테스트가 자동으로 게이트됩니다.
테스트가 실패하면 push가 차단됩니다 — 이 경우 오류를 수정하고 재커밋 후 다시 push하십시오.

---
*이 문서는 프로젝트의 헌법과 같으며, 수정이 필요한 경우 사용자에게 먼저 확인을 받으십시오.*
