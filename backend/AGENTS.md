# Backend Agent Governance (Python/AWS)

백엔드 영역(`backend/`)에서 작업하는 모든 에이전트는 아래 규칙을 준수해야 합니다.

## 1. Python 코딩 규칙
- **Runtime:** Python 3.12 (AWS Lambda 호환성 유지)
- **Boto3 클라이언트:** 반드시 `functools.lru_cache`를 사용한 싱글턴 패턴으로 생성하십시오.
  ```python
  @functools.lru_cache(maxsize=None)
  def _get_cw_client():
      return boto3.client("cloudwatch")
  ```
- **Import 순서:** 표준 라이브러리 -> 서드파티(boto3 등) -> 프로젝트 내부 모듈(`common.*`)
- **함수 복잡도 제한:** 
  - 로컬 변수 <= 15
  - Statements <= 50
  - Branches <= 12
  - 인자 개수 <= 5

## 2. 에러 처리 및 로깅
- **AWS API:** `botocore.exceptions.ClientError`만 catch하십시오.
- **로깅 포맷:** f-string 대신 `%s` 플레이스홀더를 사용하십시오.
  - GOOD: `logger.error("Failed to delete alarm: %s", e)`
  - BAD: `logger.error(f"Failed to delete alarm: {e}")`

## 3. 테스트 및 검증 (TDD)
- **Framework:** `pytest`
- **모킹:** AWS 서비스는 `moto`를 사용하고, 내부 함수는 `unittest.mock`을 사용하십시오.
- **모킹 페이지네이션(무한 루프 주의):** `while True`로 페이지네이션하는 코드(`table.query`/`scan`)를
  mock 테이블로 테스트할 땐 그 메서드를 **반드시 종료 페이지로 stub**하십시오 —
  `table.query.return_value = {"Items": []}`. bare `MagicMock`은 `LastEvaluatedKey`가 항상 truthy라
  루프가 안 끝나고 호출 누적으로 RSS가 수 GB까지 치솟아 테스트가 멈춥니다("느린 테스트"로 오인됨).
  페이지네이션 헬퍼를 바꾸면(예: `scan` → `query`) 관련 테스트 mock도 함께 갱신하십시오.
  (상세: `.kiro/steering/anti-patterns.md` AP-15)
- **PBT:** 복잡한 로직은 `hypothesis`를 사용한 Property-Based Testing을 작성하십시오.
- **필수 실행:** 코드 수정 후 `cd backend && pytest`를 실행하여 회귀 테스트를 완료하십시오.

## 4. 인프라 (CloudFormation)
- SAM을 사용하지 않는 순수 CloudFormation 패턴을 지향합니다.
- `template.yaml`의 런타임 설정을 항상 확인하십시오.

## 5. 리소스 URL 식별자 (토큰)
`/resources/{id}` 계열 라우트의 `{id}`는 프론트엔드가 **base64url 토큰**(`r.<payload>`)
으로 보낸다. ARN처럼 `/`·`:`를 포함한 `resource_id`를 path에 안전하게 싣기 위함이다
(루트 `AGENTS.md` AP-6).

- **디코딩은 중앙에서 자동 처리된다.** `_path_id`가 `_decode_resource_token`을 호출해
  토큰을 원본 `resource_id`로 복원하므로, 핸들러는 기존처럼 raw `resource_id`로 동작한다.
  새 `/resources/{id}/...` 라우트를 추가해도 `_path_id`만 쓰면 자동으로 토큰을 받는다.
- **가역·타입 무관.** 토큰은 매핑 테이블/GSI 없이 복원되고 타입에 의존하지 않으므로
  **신규 리소스 타입을 추가할 때 식별자 관련 코드는 손대지 않는다.**
- **하위호환.** 접두사(`r.`)가 없는 입력(레거시 raw id, 리소스 name)은 그대로 통과한다.
- **금지:** `resource_id`를 디코딩 없이 외부로 노출되는 새 path 규칙에 끼워 넣지 말 것.
  라우트 패턴은 토큰을 단일 세그먼트로 받도록 `[^/]+`를 유지한다.
