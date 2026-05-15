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
- **PBT:** 복잡한 로직은 `hypothesis`를 사용한 Property-Based Testing을 작성하십시오.
- **필수 실행:** 코드 수정 후 `cd backend && pytest`를 실행하여 회귀 테스트를 완료하십시오.

## 4. 인프라 (CloudFormation)
- SAM을 사용하지 않는 순수 CloudFormation 패턴을 지향합니다.
- `template.yaml`의 런타임 설정을 항상 확인하십시오.
