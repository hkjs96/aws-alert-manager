---
inclusion: always
---

# 코딩 거버넌스 (AWS Monitoring Engine)

이 프로젝트의 코드 작성 시 반드시 준수해야 하는 규칙.

> 알람 관련 상세 규칙(§5~§7, §11)은 `.kiro/steering/alarm-rules.md`, `.kiro/steering/resource-checklist.md`에 분리되어 있으며, Python 파일 작업 시 자동 로드된다.

## 0. 기술 스택 및 버전

### 런타임
| 항목 | 버전 | 비고 |
|------|------|------|
| Python | 3.12 | Lambda 런타임 (template.yaml Mappings) |
| CloudFormation | 2010-09-09 | 순수 CFN, SAM 미사용 |

### 프로덕션 의존성
| 패키지 | 버전 | 비고 |
|--------|------|------|
| boto3 | >=1.35.0 | Lambda 런타임 내장, requirements.txt에는 최소 버전만 명시 |
| botocore | >=1.35.0 | boto3 의존성으로 자동 설치 |

### 개발/테스트 의존성
| 패키지 | 버전 | 비고 |
|--------|------|------|
| pytest | >=9.0 | 테스트 프레임워크 |
| pytest-mock | >=3.14 | mock 래퍼 |
| hypothesis | >=6.100 | Property-Based Testing |
| moto[ec2,rds,elbv2,cloudwatch,sns] | >=5.0 | AWS 서비스 모킹 |


### Lambda 런타임 내장 패키지 (2026-03-19 기준)
| 패키지 | python3.12 | python3.13 | python3.14 |
|--------|-----------|-----------|-----------|
| boto3 | 1.40.4 | 1.40.4 | 1.40.4 |
| botocore | 1.40.4 | 1.40.4 | 1.40.4 |
| urllib3 | 1.26.19 | 1.26.19 | 2.6.3 |

### CPython EOL 일정
| 버전 | Lambda GA | CPython EOL | 비고 |
|------|-----------|-------------|------|
| 3.12 | 2023-12 | 2028-10 | 현재 사용 중, 가장 안정적 |
| 3.13 | 2024-11 | 2029-10 | 안정적, 마이그레이션 후보 |
| 3.14 | 2025-01 | 2030-10 | 최신, 생태계 안정화 중 |

### 버전 관리 규칙
- `requirements.txt`에 최소 버전(`>=`)을 명시한다. 정확한 핀(`==`)은 CI/CD lock 파일에서 관리
- Lambda 런타임 버전은 `template.yaml`의 `Mappings.LambdaConfig.Settings.Runtime`에서 단일 관리
- Python 3.12 전용 문법 사용 가능: `type` statement, `TypedDict`, `X | Y` union 타입 등
- Python 3.13+ 전용 문법 사용 금지 (Lambda 런타임 호환성)
- 런타임 업그레이드는 기능 개발/리팩터링과 분리하여 별도 작업으로 진행
- 업그레이드 전 전체 테스트 스위트(pytest + hypothesis PBT) 통과 필수

## 1. boto3 클라이언트 생성

모든 모듈에서 `functools.lru_cache` 기반 싱글턴 패턴을 사용한다.

```python
import functools
import boto3

@functools.lru_cache(maxsize=None)
def _get_cw_client():
    return boto3.client("cloudwatch")
```

금지 패턴:
- 모듈 레벨 `global` 변수 + `global` statement
- 함수 호출마다 `boto3.client()` 직접 생성

## 2. Import 규칙

- 모든 import는 파일 상단에 위치한다
- 함수 내부 지연 import 금지 (순환 참조 회피가 아닌 한)
- import 순서: stdlib → 서드파티(boto3) → 프로젝트 내부(common.*)

## 3. 함수 복잡도 제한 (pylint 기준)

| 항목 | 상한 |
|------|------|
| 로컬 변수 | 15개 |
| statements | 50개 |
| branches | 12개 |
| 함수 인자 | 5개 |

초과 시 반드시 헬퍼 함수로 분리한다.

## 4. 에러 처리

- AWS API 호출: `botocore.exceptions.ClientError`만 catch
- `except Exception` 사용 금지 (최상위 핸들러 제외)
- 에러 로그 시 `logger.error("메시지: %s", e)` 포맷 사용 (f-string 금지)

## 8. 테스트 규칙

- AWS 서비스 모킹: `moto` 사용 (단위 테스트), `unittest.mock` (통합 테스트)
- 정합성 검증: `hypothesis` PBT로 correctness property 작성
- 테스트 파일 네이밍: `tests/test_{module_name}.py`, PBT는 `tests/test_pbt_{property_name}.py`
- 모든 public 함수에 대해 최소 1개 테스트 케이스 필수

### TDD (Test-Driven Development)

레드-그린-리팩터링 사이클을 따른다.

1. **레드 (Red)**: 실패하는 테스트를 먼저 작성한다. 아직 구현이 없으므로 반드시 실패해야 한다.
2. **그린 (Green)**: 테스트를 통과시키는 가장 간단한 코드를 작성한다. 과도한 설계 금지.
3. **리팩터링 (Refactor)**: 테스트가 통과하는 상태를 유지하면서 코드를 정리·개선한다. 중복 제거, 네이밍 개선, 구조 분리 등 유지보수성을 높인다.

이 사이클을 기능 단위로 반복한다.

규칙:
- 프로덕션 코드보다 테스트를 먼저 작성한다
- 그린 단계에서는 테스트를 통과시키는 최소한의 코드만 작성한다
- 리팩터링 단계에서 새로운 기능을 추가하지 않는다 (기존 테스트만 통과하면 됨)
- 리팩터링 후 반드시 전체 테스트를 재실행하여 회귀가 없음을 확인한다

## 9. 로깅

- 모듈별 `logger = logging.getLogger(__name__)` 사용
- 로그 레벨: `info`(정상 흐름), `warning`(스킵/폴백), `error`(실패)
- 로그 메시지에 resource_id, metric_name 등 컨텍스트 포함

## 10. 코드 중복 금지

- 동일 로직이 2곳 이상에서 반복되면 공통 함수/모듈로 추출한다
- 알람 삭제 + lifecycle 알림 같은 복합 패턴은 헬퍼 함수로 추출한다
