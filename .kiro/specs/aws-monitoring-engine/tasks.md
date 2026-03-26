# Implementation Plan: AWS Monitoring Engine

## Overview

AWS 리소스(EC2, RDS, ELB) 모니터링 자동화 엔진을 Python + SAM으로 구현한다.
공통 모듈(Tag_Resolver, SNS_Notifier, Collectors)을 먼저 구축하고, 두 Lambda 핸들러(Daily_Monitor, Remediation_Handler)에서 이를 호출하는 구조로 점진적으로 구현한다.
Hypothesis 기반 속성 테스트와 단위 테스트로 16개 설계 속성과 8개 요구사항을 검증한다.

## Tasks

- [x] 1. 프로젝트 구조 및 공통 인터페이스 설정
  - [x] 1.1 프로젝트 디렉터리 구조 생성
    - `aws-monitoring-engine/` 루트 디렉터리 생성
    - `common/`, `common/collectors/`, `daily_monitor/`, `remediation_handler/`, `tests/` 디렉터리 생성
    - 각 디렉터리에 `__init__.py` 파일 생성
    - `requirements.txt` 생성 (boto3, hypothesis, pytest, moto)
    - _Requirements: 6.1, 6.3_

  - [x] 1.2 데이터 모델 및 상수 정의
    - `common/__init__.py`에 `HARDCODED_DEFAULTS`, `SUPPORTED_RESOURCE_TYPES`, `MONITORED_API_EVENTS` 상수 정의
    - `ResourceInfo`, `AlertMessage`, `RemediationAlertMessage`, `LifecycleAlertMessage` TypedDict 정의
    - _Requirements: 6.1_

  - [x] 1.3 테스트 공통 픽스처 설정
    - `tests/conftest.py`에 boto3 모킹 픽스처, 환경 변수 픽스처, 샘플 리소스 데이터 픽스처 작성
    - _Requirements: 6.1_

- [x] 2. Tag_Resolver 모듈 구현
  - [x] 2.1 `common/tag_resolver.py` 구현
    - `get_threshold(resource_tags, metric_name)` 함수 구현: 3단계 폴백 체인 (태그 → 환경변수 → 하드코딩 기본값)
    - `has_monitoring_tag(resource_tags)` 함수 구현
    - `get_resource_tags(resource_id, resource_type)` 함수 구현: boto3를 통한 AWS API 호출
    - 무효 태그 값(음수, 0, 비숫자) 처리 로직 포함
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [x]* 2.2 Tag_Resolver 속성 테스트 작성 (Property 2: 태그 임계치 우선 적용)
    - **Property 2: 태그 임계치 우선 적용**
    - **Validates: Requirements 2.1**
    - Hypothesis `st.floats(min_value=0.01)` 전략으로 유효한 양의 숫자 태그 값 생성
    - 태그 값이 존재할 때 환경 변수 기본값이 아닌 태그 값이 반환되는지 검증

  - [x]* 2.3 Tag_Resolver 속성 테스트 작성 (Property 3: 환경 변수 기본값 폴백)
    - **Property 3: 환경 변수 기본값 폴백**
    - **Validates: Requirements 2.2**
    - 임계치 태그가 없는 리소스에 대해 환경 변수 기본값이 반환되는지 검증

  - [x]* 2.4 Tag_Resolver 속성 테스트 작성 (Property 4: 잘못된 임계치 태그 무효 처리)
    - **Property 4: 잘못된 임계치 태그 무효 처리**
    - **Validates: Requirements 2.3**
    - 음수, 0, 비숫자 문자열, 빈 문자열 등 무효 태그 값 생성 전략 사용
    - 무효 태그 시 환경 변수 기본값으로 폴백되는지 검증

  - [x]* 2.5 Tag_Resolver 속성 테스트 작성 (Property 13: 절대 유효값 반환 보장)
    - **Property 13: Tag_Resolver 절대 유효값 반환 보장**
    - **Validates: Requirements 2.5**
    - 임의의 태그/환경변수 조합(무효값 포함)에 대해 항상 양의 숫자(> 0) 반환 검증
    - None 반환 또는 예외 발생이 없는지 검증

  - [x]* 2.6 Tag_Resolver 단위 테스트 작성
    - 구체적 예시: CPU 태그 90 → 90.0 반환, 태그 없음 + 환경변수 70 → 70.0 반환
    - 엣지 케이스: 태그 "abc", "-5", "0", "" → 기본값 폴백
    - 환경변수도 무효일 때 하드코딩 기본값(CPU:80, Memory:80, Connections:100) 반환 확인
    - _Requirements: 2.1, 2.2, 2.3, 2.5_

- [x] 3. Checkpoint - Tag_Resolver 검증
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. SNS_Notifier 모듈 구현
  - [x] 4.1 `common/sns_notifier.py` 구현
    - `send_alert(resource_id, resource_type, metric_name, current_value, threshold)` 구현: JSON 형식 알림 메시지 발송
    - `send_remediation_alert(resource_id, resource_type, change_summary, action_taken)` 구현
    - `send_lifecycle_alert(resource_id, resource_type, event_type, message)` 구현
    - `send_error_alert(context, error)` 구현
    - 모든 함수에서 SNS 발송 실패 시 CloudWatch Logs에 기록하고 예외를 삼키는 패턴 적용
    - _Requirements: 3.1, 3.2, 3.4, 5.2, 8.2, 8.5_

  - [x]* 4.2 SNS_Notifier 속성 테스트 작성 (Property 7: 임계치 초과 알림 메시지 완전성)
    - **Property 7: 임계치 초과 알림 메시지 완전성**
    - **Validates: Requirements 3.1, 3.2**
    - 임의 메트릭 값으로 `send_alert` 호출 시 JSON 메시지에 resource_id, resource_type, metric_name, current_value, threshold 필드 모두 포함 검증

  - [x]* 4.3 SNS_Notifier 속성 테스트 작성 (Property 11: Remediation 완료 알림 메시지 완전성)
    - **Property 11: Remediation 완료 알림 메시지 완전성**
    - **Validates: Requirements 5.2**
    - 임의 remediation 결과로 `send_remediation_alert` 호출 시 resource_id, resource_type, change_summary, action_taken 필드 모두 포함 검증

  - [x]* 4.4 SNS_Notifier 단위 테스트 작성
    - SNS 발송 실패 시 예외가 전파되지 않고 로그만 기록되는지 확인
    - 각 알림 함수의 JSON 메시지 구조 검증
    - _Requirements: 3.4_

- [x] 5. Collectors 모듈 구현
  - [x] 5.1 `common/collectors/ec2.py` 구현
    - `collect_monitored_resources()` 구현: `describe_instances` API로 `Monitoring=on` 태그 필터링
    - `get_metrics(instance_id)` 구현: CloudWatch에서 CPUUtilization 메트릭 조회, 데이터 없으면 None 반환
    - 삭제/종료된 인스턴스 제외 및 로그 기록
    - _Requirements: 1.1, 1.2, 1.5, 3.5_

  - [x] 5.2 `common/collectors/rds.py` 구현
    - `collect_monitored_resources()` 구현: `describe_db_instances` + `list_tags_for_resource` API로 `Monitoring=on` 태그 필터링
    - `get_metrics(db_instance_id)` 구현: CloudWatch에서 CPUUtilization, DatabaseConnections 메트릭 조회
    - _Requirements: 1.1, 1.2, 1.5, 3.5_

  - [x] 5.3 `common/collectors/elb.py` 구현
    - `collect_monitored_resources()` 구현: `describe_load_balancers` + `describe_tags` API로 `Monitoring=on` 태그 필터링
    - `get_metrics(load_balancer_name)` 구현: CloudWatch에서 RequestCount, HealthyHostCount 메트릭 조회
    - _Requirements: 1.1, 1.2, 1.5, 3.5_

  - [x]* 5.4 Collectors 속성 테스트 작성 (Property 1: 수집 결과 필터링 정확성)
    - **Property 1: 수집 결과 필터링 정확성**
    - **Validates: Requirements 1.1, 1.2**
    - 임의 리소스 목록(Monitoring=on 태그 있는 것과 없는 것 혼합) 생성
    - 반환 목록이 Monitoring=on 태그 리소스만 포함하고 누락 없는지 검증

  - [x]* 5.5 Collectors 속성 테스트 작성 (Property 5: 삭제된 리소스 수집 제외)
    - **Property 5: 삭제된 리소스 수집 제외**
    - **Validates: Requirements 1.5**
    - 삭제/종료 상태 리소스 포함 목록에서 해당 리소스가 제외되는지 검증

  - [x]* 5.6 Collectors 단위 테스트 작성
    - AWS API 오류 시 로그 기록 + SNS 오류 알림 발송 확인
    - 수집 대상 0개일 때 빈 리스트 반환 확인
    - InsufficientData 메트릭 시 None 반환 확인
    - _Requirements: 1.3, 1.4, 3.5_

- [x] 6. Checkpoint - 공통 모듈 검증
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Daily_Monitor 핸들러 구현
  - [x] 7.1 `daily_monitor/handler.py` 구현
    - `handler(event, context)` 함수 구현: EC2/RDS/ELB Collector 순회 → 메트릭 조회 → 임계치 비교 → SNS 알림
    - 핸들러는 비즈니스 로직 없이 공통 모듈 호출만 담당
    - 리소스별 격리 패턴 적용: 단일 리소스 실패가 전체 실행을 중단시키지 않음
    - 메트릭 데이터 없음/InsufficientData 시 건너뛰기 및 로그 기록
    - 수집 대상 0개 시 알림 없이 정상 종료
    - _Requirements: 1.1, 1.3, 3.1, 3.3, 3.5, 6.3, 6.4_

  - [x]* 7.2 Daily_Monitor 속성 테스트 작성 (Property 6: InsufficientData 메트릭 알림 건너뛰기)
    - **Property 6: InsufficientData 메트릭 알림 건너뛰기**
    - **Validates: Requirements 3.5**
    - 메트릭 데이터 없음/InsufficientData 시나리오에서 알림 미발송 및 로그 기록 검증

  - [x]* 7.3 Daily_Monitor 속성 테스트 작성 (Property 8: 복수 리소스 개별 알림 발송)
    - **Property 8: 복수 리소스 개별 알림 발송**
    - **Validates: Requirements 3.3**
    - N개 임계치 초과 리소스에 대해 정확히 N개 SNS 알림 발송 검증

  - [x]* 7.4 Daily_Monitor 단위 테스트 작성
    - 수집 대상 0개일 때 SNS 알림 미발송 확인
    - AWS API 오류 시 로그 + SNS 오류 알림 발송 확인
    - SNS 발송 실패 시 나머지 리소스 처리 계속 확인
    - _Requirements: 1.3, 1.4, 3.4_

- [x] 8. Remediation_Handler 구현
  - [x] 8.1 `remediation_handler/handler.py` 구현 - CloudTrail 이벤트 파싱 및 라우팅
    - `handler(event, context)` 함수 구현
    - `parse_cloudtrail_event(event)` 함수 구현: resource_id, resource_type, change_summary, event_category 추출
    - event_category별 라우팅: "MODIFY" → remediation, "DELETE" → lifecycle 알림, "TAG_CHANGE" → 태그 변경 처리
    - CloudTrail 이벤트 파싱 오류 시 로그 기록 + SNS 오류 알림
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 6.3, 6.4_

  - [x] 8.2 `remediation_handler/handler.py` 구현 - Auto-Remediation 로직
    - `perform_remediation(resource_type, resource_id)` 함수 구현: EC2→stop, RDS→stop, ELB→delete
    - Remediation 수행 전 CloudWatch Logs에 사전 로그 기록 (resource_id, 변경 이벤트 요약, 수행 예정 조치)
    - Remediation 완료 후 SNS 알림 발송
    - Remediation 실패 시 로그 기록 + SNS 즉시 알림
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [x] 8.3 `remediation_handler/handler.py` 구현 - 리소스 삭제 및 태그 변경 처리
    - `handle_tag_change(event, resource_id, resource_type)` 함수 구현
    - 리소스 삭제 이벤트: Monitoring=on 태그 있으면 "리소스가 삭제됨" SNS 알림, 없으면 무시
    - DeleteTags 이벤트: Monitoring=on 태그 제거 시 "모니터링 대상에서 제외됨" SNS 알림
    - CreateTags 이벤트: Monitoring=on 태그 추가 시 CloudWatch Logs에 "모니터링 대상에 추가됨" 기록
    - 이벤트 파싱 오류 시 로그 기록 + SNS 오류 알림
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7_

  - [x]* 8.4 Remediation_Handler 속성 테스트 작성 (Property 9: Monitoring 태그 기반 Remediation 필터링)
    - **Property 9: Monitoring 태그 기반 Remediation 필터링**
    - **Validates: Requirements 4.2, 4.3**
    - Monitoring=on 태그 없는 리소스에 remediation 미수행, 있는 리소스에 수행 검증

  - [x]* 8.5 Remediation_Handler 속성 테스트 작성 (Property 10: 리소스 유형별 Remediation 액션 정확성)
    - **Property 10: 리소스 유형별 Remediation 액션 정확성**
    - **Validates: Requirements 5.1**
    - EC2→stop, RDS→stop, ELB→delete 규칙 준수 검증

  - [x]* 8.6 Remediation_Handler 속성 테스트 작성 (Property 12: Remediation 사전 로그 기록)
    - **Property 12: Remediation 사전 로그 기록**
    - **Validates: Requirements 5.4**
    - 로그 기록이 실제 remediation 액션 호출보다 먼저 발생하는지 검증

  - [x]* 8.7 Remediation_Handler 속성 테스트 작성 (Property 14: 리소스 삭제 이벤트 알림 정확성)
    - **Property 14: 리소스 삭제 이벤트 알림 정확성**
    - **Validates: Requirements 8.1, 8.2, 8.3**
    - Monitoring=on 태그 있는 리소스 삭제 시 SNS 알림 발송, 없으면 무시 검증

  - [x]* 8.8 Remediation_Handler 속성 테스트 작성 (Property 15: 태그 제거 시 알림 발송)
    - **Property 15: 태그 제거 시 알림 발송**
    - **Validates: Requirements 8.5**
    - DeleteTags 이벤트에서 Monitoring=on 태그 제거 시 SNS 알림 발송 검증

  - [x]* 8.9 Remediation_Handler 속성 테스트 작성 (Property 16: 태그 추가 시 로그 기록)
    - **Property 16: 태그 추가 시 로그 기록**
    - **Validates: Requirements 8.6**
    - CreateTags 이벤트에서 Monitoring=on 태그 추가 시 로그 기록 및 SNS 알림 미발송 검증

  - [x]* 8.10 Remediation_Handler 단위 테스트 작성
    - 잘못된 CloudTrail 이벤트 파싱 오류 처리 확인
    - Remediation 실패 시 즉시 SNS 알림 확인
    - 삭제/태그 변경 이벤트 파싱 오류 시 로그 + SNS 알림 발송 확인
    - _Requirements: 4.4, 5.3, 8.7_

- [x] 9. Checkpoint - Lambda 핸들러 검증
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. SAM 템플릿 작성
  - [x] 10.1 `aws-monitoring-engine/template.yaml` 작성
    - Daily_Monitor Lambda 함수 정의 (Python 3.12 런타임, common 레이어 포함)
    - Remediation_Handler Lambda 함수 정의
    - EventBridge Scheduler 규칙 (1일 1회 Daily_Monitor 트리거)
    - EventBridge 규칙 (CloudTrail 이벤트 → Remediation_Handler 트리거)
      - 감지 대상 API: ModifyInstanceAttribute, ModifyInstanceType, ModifyDBInstance, ModifyLoadBalancerAttributes, ModifyListener, TerminateInstances, DeleteDBInstance, DeleteLoadBalancer, CreateTags, DeleteTags
    - SNS 토픽 정의
    - IAM 역할 및 최소 권한 정책 (EC2/RDS/ELB 읽기, CloudWatch 읽기, SNS 발행, CloudWatch Logs 쓰기, EC2/RDS 중지, ELB 삭제)
    - SAM 파라미터로 DEFAULT_CPU_THRESHOLD, DEFAULT_MEMORY_THRESHOLD, DEFAULT_CONNECTIONS_THRESHOLD 정의
    - Lambda 환경 변수에 SNS_TOPIC_ARN, 임계치 기본값 파라미터 매핑
    - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [x] 11. 통합 및 최종 연결
  - [x] 11.1 모듈 간 임포트 경로 및 연결 검증
    - daily_monitor/handler.py → common 모듈 임포트 경로 확인
    - remediation_handler/handler.py → common 모듈 임포트 경로 확인
    - template.yaml의 CodeUri와 실제 디렉터리 구조 일치 확인
    - _Requirements: 6.2, 6.3, 6.4_

  - [x]* 11.2 통합 테스트 작성
    - Daily_Monitor 전체 흐름 테스트: 수집 → 메트릭 조회 → 임계치 비교 → 알림 발송
    - Remediation_Handler 전체 흐름 테스트: 이벤트 수신 → 파싱 → 태그 확인 → remediation → 알림
    - _Requirements: 1.1, 3.1, 4.1, 5.1, 8.1_

- [x] 12. Final checkpoint - 전체 테스트 통과 확인
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties (Hypothesis, min 100 examples)
- Unit tests validate specific examples and edge cases
- All AWS API calls are mocked in tests using `unittest.mock` or `moto`
