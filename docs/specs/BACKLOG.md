# 스펙 백로그 — 미완료 태스크 모음

> 원본 스펙 전문(requirements.md / design.md / tasks.md)은 git 히스토리의
> `.kiro/specs/<name>/` 참조. 이 문서는 부분 완료 상태로 종료된 스펙들의
> 미체크(`- [ ]`) 태스크만 발췌한 것이다.
>
> `*` 표시 태스크는 원본 스펙에서 "선택적 — 빠른 MVP를 위해 스킵 가능"으로
> 분류된 항목이며, 대부분 PBT(Property-Based Test) 작성 태스크다.

## extended-resource-monitoring

- [ ] 16. PBT — 설계 문서 Correctness Properties 10개
  - 하위 태스크 16.1~16.10(PBT Property 1~10)은 모두 완료 체크됨. 상위
    체크박스만 미체크로 남은 상태 — 사실상 완료로 보임.

## create-event-alarm-trigger

CREATE 이벤트(RunInstances, CreateDBInstance, CreateLoadBalancer,
CreateTargetGroup) 기반 알람 자동 생성 트리거. 구현·단위 테스트는 완료,
선택적 PBT 3건만 남음 (테스트 파일: `tests/test_pbt_create_event.py`).

- [ ]* 3.3 Property 1 PBT 작성 — CREATE 이벤트 파싱 정확성
  - `parse_cloudtrail_event()` 반환값의 resource_id/resource_type/event_category 검증
- [ ]* 4.3 Property 2 PBT 작성 — Monitoring 태그 게이팅
  - `Monitoring=on`일 때만 `create_alarms_for_resource` 호출됨을 검증
- [ ]* 4.4 Property 4 PBT 작성 — CREATE 라우팅 및 응답
  - `lambda_handler()`가 `{"status": "ok"}` / 예외 시 `{"status": "error"}` 반환 검증

## lb-tg-alarm-test-infra

LB/TG 알람 테스트용 CloudFormation 인프라(`infra-test/`). 템플릿·문서 완료,
템플릿 검증 테스트 3건 남음 (상위 태스크 "5. PBT 테스트 작성" 하위).

- [ ]* 5.2 DeletionPolicy 안전성 테스트 추가
  - 모든 리소스의 DeletionPolicy가 absent 또는 Delete인지 확인
- [ ]* 5.3 Security Group 아웃바운드 개방 테스트 추가
  - 모든 SG의 SecurityGroupEgress에 `0.0.0.0/0` 전체 아웃바운드 규칙 존재 확인
- [ ]* 5.4 단위 테스트 추가 — 템플릿 구조 검증
  - 파라미터 6개, EC2 t3.micro/UserData, ALB/NLB Scheme, TG 헬스체크, Listener 설정 확인

## elb-resource-type-split

ELB → ALB/NLB/TG resource_type 세분화. 구현 완료, 선택적 PBT 4건 남음.

- [ ]* 2.3 Property 1 테스트: Collector 리소스 타입 매핑 정확성
  - `common/collectors/elb.py`의 ALB/NLB/TG 분류 검증
- [ ]* 3.3 Property 2 테스트: 알람 이름 prefix와 resource_type 일치
  - `common/alarm_manager.py` 알람 정의 분리 검증
- [ ]* 7.4 Property 4 테스트: 알람 분류 정확성 (새 prefix 포함)
  - `daily_monitor/lambda_handler.py` 고아 알람 정리 로직 검증
- [ ]* 8.3 Property 5 테스트: ARN 기반 resource_type 판별
  - `remediation_handler/lambda_handler.py` ALB/NLB 구분 검증

## elasticache-nat-monitoring

ElastiCache + NAT Gateway 모니터링. 구현 완료, 선택적 PBT 6건 남음.

- [ ]* 1.5 PBT: Property 1 — 신규 리소스 타입 레지스트리 완전성 (alarm_registry)
- [ ]* 3.3 PBT: Property 2 — ElastiCache Collector 필터링
- [ ]* 4.3 PBT: Property 3 — NATGateway Collector 필터링
- [ ]* 6.3 PBT: Property 4 — CloudTrail 이벤트 ID 추출 정확성 (remediation handler)
- [ ]* 7.2 PBT: Property 5 — 신규 메트릭 태그 임계치 오버라이드 (tag_resolver)
- [ ]* 7.3 PBT: Property 6 — 신규 리소스 타입 동적 알람 하드코딩 키 제외

## manual-dependency-injection

`*, cw=None` 키워드 인자 방식 수동 DI (Phase 1). 구현 완료, DI 단위 테스트
6건 남음.

- [ ]* 1.2 `create_clients_for_account` 단위 테스트 작성 (`_clients.py`)
- [ ]* 3.2 alarm_search DI 단위 테스트 작성
- [ ]* 5.2 dimension_builder DI 단위 테스트 작성
- [ ]* 7.3 alarm_builder DI 단위 테스트 작성
- [ ]* 9.2 alarm_sync DI 단위 테스트 작성
- [ ]* 11.4 Facade DI 단위 테스트 작성 (`alarm_manager.py` 3개 함수)

## alarm-name-short-id

ALB/NLB/TG 알람 이름 Short_ID suffix 적용. 구현 완료, 선택적 PBT 7건 남음.

- [ ]* 1.3 Property 1 테스트: ALB/NLB/TG Short_ID 추출 정확성 (`_shorten_elb_resource_id()`)
- [ ]* 1.4 Property 2 테스트: EC2/RDS 무변환
- [ ]* 1.5 Property 7 테스트: Short_ID 추출 멱등성
- [ ]* 1.6 Property 8 테스트: Short_ID와 Dimension 값 차이
- [ ]* 2.3 Property 3 테스트: 알람 이름 Short_ID suffix (`_pretty_alarm_name()`)
- [ ]* 5.3 Property 5 테스트: 검색 결과 중복 없음 (`_find_alarms_for_resource()` 레거시+새 포맷 호환)
- [ ]* 6.2 Property 6 테스트: AlarmDescription에 Full_ARN 유지

## aurora-rds-monitoring

Aurora RDS 분류·모니터링. 구현 완료, 선택적 PBT 7건 남음.

- [ ]* 2.3 Property 1 테스트: Engine 기반 Aurora 분류 (`common/collectors/rds.py`)
- [ ]* 2.6 Property 2 테스트: Bytes-to-GB 변환 일관성
- [ ]* 4.5 Property 3 테스트: Aurora 알람 이름 prefix 및 메타데이터 (`common/alarm_manager.py`)
- [ ]* 5.3 Property 5 테스트: 알람 검색 prefix/suffix
- [ ]* 7.5 Property 4 테스트: 알람 분류 정확성 (`daily_monitor/lambda_handler.py`)
- [ ]* 9.5 Property 6 테스트: CloudTrail 이벤트 Aurora 해석 (`remediation_handler/lambda_handler.py`)
- [ ]* 10.3 Property 7 테스트: 태그 기반 임계치 오버라이드 (`common/tag_resolver.py`)

## rds-aurora-alarm-optimization

RDS/Aurora 변형별 알람 최적화 (KI-008 포함). 구현 완료, 선택적 PBT 7건 남음.

- [ ]* 2.3 Property 1 테스트: Aurora Collector Enrichment Completeness (`common/collectors/rds.py`)
- [ ]* 2.4 Property 2 테스트: Non-Aurora RDS Tag Exclusion
- [ ]* 4.5 Property 3 테스트: Alarm Variant Routing (`common/alarm_manager.py`)
- [ ]* 6.3 Property 5 테스트: Percentage-Based Memory Threshold Calculation
- [ ]* 6.4 Property 6 테스트: Instance Memory Capacity Lookup
- [ ]* 8.3 Property 4 테스트: Metric Collection Matches Alarm Variant
- [ ]* 10.3 Property 7 테스트: Delete Event Alarm Cleanup Across Prefixes (`remediation_handler/lambda_handler.py`)

## tag-driven-alarm-engine

태그 기반 알람 엔진 (threshold off 처리, 동적 알람 sync). 구현 완료,
선택적 PBT 8건 남음 (테스트 파일: `tests/test_pbt_tag_driven_alarm.py`).

- [ ]* 1.3 Property 8 PBT 작성 — `is_threshold_off()` (tag_resolver.py)
- [ ]* 2.4 Property 1 PBT 작성 — `_select_best_dimensions()` / `_resolve_metric_dimensions()`
- [ ]* 3.3 Property 2 PBT 작성 — `_parse_threshold_tags()` off 값 명시적 처리
- [ ]* 5.3 Property 3 PBT 작성 — `create_alarms_for_resource()` off 체크
- [ ]* 6.4 Property 4 PBT 작성 — `sync_alarms_for_resource()` 동적 알람 + off 처리
- [ ]* 6.5 Property 5 PBT 작성 — 〃
- [ ]* 6.6 Property 6 PBT 작성 — 〃
- [ ]* 6.7 Property 7 PBT 작성 — 〃

## docdb-monitoring

DocumentDB 모니터링. 구현 완료, 선택적 PBT 10건 남음.

- [ ]* 1.4 PBT Property 1: Engine 기반 DocDB 분류 (`common/collectors/docdb.py`)
- [ ]* 3.4 PBT Property 2: Bytes-to-GB 변환 Round Trip (`common/alarm_manager.py`)
- [ ]* 3.5 PBT Property 3: DocDB 알람 정의 정합성
- [ ]* 5.3 PBT Property 10: Tag Resolver DocDB 지원 (`common/tag_resolver.py`)
- [ ]* 7.4 PBT Property 5: 알람 이름 접두사 분류 (`daily_monitor/lambda_handler.py`)
- [ ]* 7.5 PBT Property 6: 알람 검색 Prefix/Suffix
- [ ]* 9.4 PBT Property 7: CloudTrail Engine Resolution (`remediation_handler/lambda_handler.py`)
- [ ]* 9.5 PBT Property 9: Remediation Execution for DocDB
- [ ]* 11.3 PBT Property 4: DocDB 알람 이름 접두사 및 메타데이터
- [ ]* 11.4 PBT Property 8: 태그 기반 임계치 오버라이드 (DocDB)

## remaining-resources-e2e-test

잔여 리소스(Lambda, APIGW REST/HTTP/WebSocket, VPN, ACM, Backup, MQ, CLB,
OpenSearch) E2E 테스트용 CFN 템플릿·트래픽 스크립트. 구현 하위 태스크는
전부 체크 완료 상태이며, 상위 체크박스와 검증 체크포인트만 미체크로 남음
— 실질 잔여 작업은 체크포인트 검증(4, 9, 11) 수행 여부 확인이다.

- [ ] 1. CFN 템플릿 스켈레톤 및 공유 리소스 생성 (하위 태스크 완료)
- [ ] 2. Lambda + API Gateway REST 리소스 생성 (하위 태스크 완료)
- [ ] 3. API Gateway HTTP + WebSocket 리소스 생성 (하위 태스크 완료)
- [ ] 4. Checkpoint — CFN 템플릿 중간 검증
- [ ] 5. VPN 리소스 생성 (하위 태스크 완료)
- [ ] 6. ACM + AWS Backup 리소스 생성 (하위 태스크 완료)
- [ ] 7. Amazon MQ + CLB 리소스 생성 (하위 태스크 완료)
- [ ] 8. OpenSearch + Outputs 섹션 생성 (하위 태스크 완료)
- [ ] 9. Checkpoint — CFN 템플릿 최종 검증
  - 전체 리소스 수 ~30개, Monitoring=on 태그 부착, DeletionProtection 비활성화 확인
- [ ] 10. 트래픽 테스트 스크립트 생성 (하위 태스크 완료 — `traffic-test.sh` Phase 1~5)
- [ ] 11. Final Checkpoint — 전체 검증

## alarm-manager-frontend

(구버전 프론트 계획 — 대부분 현행 UI로 대체됨, 참고용)

초기 MVP 프론트엔드 + 백엔드 API 통합 계획. 프론트 페이지 구현(태스크 1~9)은
완료 체크, 태스크 10~16이 미완으로 남았다. 요약:

- 프론트엔드 전체 페이지 검증 체크포인트(10) 및 최종 통합 검증(16) 미수행
- 백엔드 인프라 CFN 정의(11): DynamoDB 테이블 4개, SQS FIFO 큐+DLQ,
  API Gateway + Lambda 함수
- api_handler Lambda 라우트 구현(12): 고객사/어카운트 CRUD, 임계치
  오버라이드, 리소스 조회·알람 설정, 알람 변경·벌크 작업, 작업 상태·대시보드,
  커스텀 메트릭 자동완성
- SQS Worker Lambda 구현(14) 및 프론트-백엔드 통합 연결(15): API 에러
  핸들링, 모니터링 토글·알람 저장 비동기 흐름
