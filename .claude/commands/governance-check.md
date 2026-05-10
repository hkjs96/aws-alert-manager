# /governance-check — 코딩 거버넌스 준수 검사

> 원본: `.kiro/hooks/governance-check-on-write.json` (preToolUse: write)

지정된 Python 파일(없으면 최근 수정된 `**/*.py` 전체)에 대해 아래 규칙 위반 여부를 검사한다.

## 검사 항목

### §1 boto3 클라이언트 생성
- `functools.lru_cache` 싱글턴만 허용
- `global` 변수 + `global` statement 금지
- 함수마다 `boto3.client()` 직접 생성 금지

### §2 Import 순서
- 파일 상단에만 위치
- 함수 내부 지연 import 금지 (순환 참조 회피가 아닌 한)
- 순서: stdlib → 서드파티(boto3) → 프로젝트 내부(common.*)

### §3 함수 복잡도 (pylint 기준)
- 로컬 변수 ≤ 15
- statements ≤ 50
- branches ≤ 12
- 함수 인자 ≤ 5

pylint가 설치되어 있으면 실행:
```bash
pylint --disable=all --enable=too-many-locals,too-many-statements,too-many-branches,too-many-arguments --max-locals=15 --max-statements=50 --max-branches=12 --max-args=5 {files}
```

### §4 에러 처리
- `botocore.exceptions.ClientError`만 catch
- `except Exception` 금지 (최상위 핸들러 제외)
- `logger.error("메시지: %s", e)` 포맷 — f-string 로깅 금지

### §9 로깅
- `logging.getLogger(__name__)` 사용
- 로그 메시지에 resource_id, metric_name 등 컨텍스트 포함

### §10 코드 중복 금지
- 동일 로직이 2곳 이상 반복되면 공통 함수로 추출

## 안티패턴 (anti-patterns.md)

- AP-1: 하드코딩된 시크릿 (AKIA..., password=, secret=)
- AP-2: 순환 참조
- AP-3: 알람 이름 문자열 매칭
- AP-4: 전체 알람 풀스캔
- AP-5: except Exception 남용
- AP-6: f-string 로깅
- AP-7: 모듈 레벨 global로 boto3 관리
- AP-8: alive 체크를 lambda_handler에 하드코딩

## 출력

위반 사항이 있으면 **파일명:라인:위반 규칙:설명** 형식으로 보고한다.
위반이 없으면 "거버넌스 준수 확인됨"이라고 보고한다.
