# /test — 테스트 실행

$ARGUMENTS에 따라 테스트 범위를 결정한다.

## 사용법

- `/test` — Python + Frontend 전체 테스트
- `/test python` — Python만
- `/test frontend` — Frontend만
- `/test {file}` — 특정 파일/모듈만

## Python 테스트

```bash
pytest tests/ -x -q --tb=short
```

특정 모듈: `pytest tests/test_{module}.py -x -v --tb=short`

## Frontend 테스트

```bash
cd frontend && npx vitest --run --reporter=verbose
```

타입 체크:
```bash
cd frontend && npx tsc --noEmit
```

## 실패 시

실패 원인을 **A. 구현 버그 / B. 테스트 버그 / C. 환경 문제**로 분류하고 수정 방안을 보고한다.
