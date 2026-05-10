# AWS Alarm Manager — 기능 명세서

> 작성일: 2026-04-28  
> 브랜치: phase2  
> 범위: 현재 구현 완료 기능 + 미완료 로드맵 전체

---

## 범례

| 기호 | 의미 |
|------|------|
| ✅ | 구현 완료 |
| 🔶 | 부분 구현 (UI/Mock 존재, API 미연동) |
| ❌ | 미구현 |
| P0 | 없으면 시스템이 동작 안 함 (블로커) |
| P1 | 핵심 운영 기능, 빠른 시일 내 필요 |
| P2 | 편의·품질 개선, 일정 여유 시 구현 |

---

## 1. 백엔드 엔진 (Python Lambda)

### 1-1. 태그 기반 알람 자동 생성 ✅ P0 — `0h`

**사용자 스토리:** 인프라 엔지니어로서, EC2·RDS·ELB 등 리소스에 `Monitoring=on` 태그를 붙이면 CloudWatch 알람이 자동으로 생성되길 원한다. 매번 콘솔에서 수작업으로 알람을 만들지 않기 위해.

**인수 조건:**
- `Monitoring=on` 태그가 있는 리소스에 대해 리소스 타입별 기본 알람이 자동 생성된다
- 지원 리소스: EC2, RDS, AuroraRDS, ALB, NLB, CLB, TG, DocDB, ElastiCache, NAT Gateway, Lambda, VPN, APIGW, ACM, Backup, MQ, OpenSearch, SQS, ECS, MSK, DynamoDB, CloudFront, WAF, Route53, DX, EFS, S3, SageMaker, SNS (30종)
- 알람 이름은 `[ResourceType]-{TagName}-{Metric}-{Threshold}` 포맷을 따른다
- Daily Monitor Lambda가 매일 00:00 UTC(09:00 KST) 실행되어 전체 동기화를 수행한다

---

### 1-2. `Threshold_*` 태그 기반 임계치 동적 설정 ✅ P0 — `0h`

**사용자 스토리:** 운영자로서, 리소스별로 임계치를 다르게 설정하고 싶다. 글로벌 기본값이 아닌 해당 리소스에 맞는 임계치를 코드 수정 없이 태그로 지정하고 싶기 때문이다.

**인수 조건:**
- `Threshold_{MetricKey}={value}` 태그로 알람 임계치를 오버라이드할 수 있다 (예: `Threshold_CPU=90`)
- `Threshold_off` 태그가 있으면 해당 메트릭의 알람이 생성되지 않는다
- 임계치 조회 우선순위: 리소스 태그 → 환경변수 → 하드코딩 기본값 (3단계 폴백)
- GB 단위 임계치는 내부적으로 bytes로 자동 환산된다

---

### 1-3. 알람 동기화 및 드리프트 감지 ✅ P0 — `0h`

**사용자 스토리:** 운영자로서, 누군가 콘솔에서 임의로 알람을 변경하더라도 시스템이 자동으로 원래 설정으로 복원하길 원한다. 임계치 드리프트로 인한 모니터링 공백을 없애기 위해.

**인수 조건:**
- Daily Monitor 실행 시 기존 알람과 기대값을 비교하여 드리프트를 감지한다
- 드리프트가 감지된 알람은 자동으로 재동기화(put_metric_alarm)된다
- `Monitoring=on` 태그가 제거된 리소스의 알람(고아 알람)은 자동 삭제된다

---

### 1-4. 실시간 변경 감지 (Remediation Handler) ✅ P0 — `0h`

**사용자 스토리:** 운영자로서, 리소스가 생성·삭제·태그 변경될 때 즉시 알람이 조정되길 원한다. Daily Monitor 스케줄을 기다리지 않고 실시간으로 반응하기 위해.

**인수 조건:**
- CloudTrail 이벤트(RunInstances, TerminateInstances, CreateDBInstance 등)를 감지한다
- 리소스 생성 시 → 알람 자동 생성, 삭제 시 → 알람 자동 정리
- `Monitoring` 태그 변경 이벤트(`on`↔`off`) 시 알람 활성화/비활성화 처리
- 지원 이벤트: `MONITORED_API_EVENTS`에 정의된 AWS API 이벤트 전체

---

### 1-5. Severity 등급 자동 부여 및 태그 저장 🔶 P1 — `4h`

**사용자 스토리:** 운영자로서, 각 알람이 얼마나 심각한지 등급(SEV-1~5)이 자동으로 부여되길 원한다. 알람이 울렸을 때 우선순위를 빠르게 판단하기 위해.

**인수 조건:**
- `alarm_registry.py`에 `_DEFAULT_SEVERITY` dict가 정의된다 (메트릭 → SEV-1~5 매핑)
- 알람 생성 시 CloudWatch 알람 태그에 `Severity: SEV-{n}` 및 `ManagedBy: AlarmManager`가 저장된다
- 기본 정의 없는 메트릭은 SEV-5(Info)로 폴백된다
- Severity 변경은 `tag_resource`만 호출하며, 알람 재생성이 불필요하다

**현황:** `_DEFAULT_SEVERITY` dict 및 `tag_resource` 호출 코드 작성 필요.

---

### 1-6. 동적 알람 방향 제어 (`LT_` prefix) ❌ P2 — `6h`

**사용자 스토리:** 운영자로서, "값이 N 이하로 떨어지면 알람"인 메트릭(HealthyHostCount, FreeMemory 등)에도 태그 기반 동적 알람을 설정하고 싶다. 현재는 GreaterThan 방향만 동적으로 지원하기 때문이다.

**인수 조건:**
- `Threshold_LT_{MetricKey}={value}` 태그를 인식하여 `LessThanThreshold` 비교 연산자로 알람을 생성한다
- `Threshold_{MetricKey}={value}` (prefix 없음)은 기존대로 `GreaterThanThreshold`로 처리된다
- 기존 동적 알람과 하위 호환이 유지된다

**현황:** KNOWN-ISSUES KI-009. 스펙 설계부터 시작.

---

### 1-7. 글로벌 서비스 알람 알림 (us-east-1) ❌ P2 — `8h`

**사용자 스토리:** 운영자로서, CloudFront·Route53·WAF 알람이 울리면 다른 리소스와 동일하게 Slack 알림을 받고 싶다. 현재는 글로벌 서비스 AlarmActions가 비어 있어 알림이 오지 않기 때문이다.

**인수 조건:**
- us-east-1에 SNS 토픽이 자동 프로비저닝된다 (CloudFormation CustomResource)
- CloudFront/Route53/WAF/Shield 알람의 AlarmActions에 us-east-1 SNS ARN이 설정된다
- `SNS_TOPIC_ARN_GLOBAL_ALERT` 환경변수로 ARN을 관리한다

**현황:** KNOWN-ISSUES KI 관련. spec 설계 → CustomResource Lambda → alarm_builder 수정 순으로 진행.

---

## 2. API 인프라 (미구현)

### 2-1. API Gateway + api_handler Lambda ❌ P0 — `2d`

**사용자 스토리:** 프론트엔드 개발자로서, 실제 AWS 데이터를 조회·변경하는 REST API가 필요하다. 현재 프론트엔드는 Mock 데이터만 사용하기 때문이다.

**인수 조건:**
- API Gateway REST API + Lambda(api_handler)가 CloudFormation으로 프로비저닝된다
- 엔드포인트: `GET /resources`, `GET /resources/{id}`, `GET /alarms`, `GET /dashboard/stats`
- 엔드포인트: `POST /resources/sync`, `POST /monitoring/enable`, `POST /monitoring/disable`
- 엔드포인트: `GET|POST|PUT|DELETE /customers`, `GET|POST|PUT|DELETE /accounts`
- 엔드포인트: `GET|PUT /alarm-configs/{resourceId}`
- IAM 인증 또는 API Key 기반 인증

---

### 2-2. DynamoDB 데이터 모델 ❌ P0 — `1d`

**사용자 스토리:** MSP 엔지니어로서, 고객사·어카운트·임계치 오버라이드 설정을 영구 저장할 DB가 필요하다. 현재는 코드에 하드코딩된 설정만 존재하기 때문이다.

**인수 조건:**
- `Customers` 테이블: customer_id, name, description, created_at
- `Accounts` 테이블: account_id, customer_id, aws_account_id, region, name
- `ThresholdOverrides` 테이블: resource_id, metric_key, threshold_value, customer_id
- `SeverityOverrides` 테이블 슬롯 예약 (Phase2 대비)
- 파티션 키 설계: 핫스팟 없도록 customer_id 기반 설계

---

### 2-3. SQS FIFO 큐 기반 비동기 처리 ❌ P1 — `4h`

**사용자 스토리:** 운영자로서, 수백 개 리소스에 대한 벌크 모니터링 활성화가 타임아웃 없이 처리되길 원한다. API Gateway 타임아웃(30초)보다 오래 걸리는 대규모 작업이 존재하기 때문이다.

**인수 조건:**
- 벌크 enable/disable 요청은 SQS FIFO 큐로 전달된다
- SQS Worker Lambda가 메시지를 소비하여 알람 생성/삭제를 처리한다
- API는 즉시 `202 Accepted`와 `job_id`를 반환한다
- `GET /jobs/{job_id}` 엔드포인트로 처리 상태를 조회할 수 있다

---

## 3. 프론트엔드 기능

### 3-1. 레이아웃 및 글로벌 필터 🔶 P0 — `4h`

**사용자 스토리:** 인프라 엔지니어로서, 고객사·어카운트를 전역 필터로 선택하면 모든 페이지의 데이터가 즉시 해당 범위로 좁혀지길 원한다. 페이지마다 따로 필터를 설정하지 않기 위해.

**인수 조건:**
- 상단 TopBar에 고객사 → 어카운트 캐스케이딩 드롭다운이 표시된다
- 필터 변경 시 URL 쿼리 파라미터에 반영되어 공유·북마크가 가능하다
- 모든 API 요청에 `customer_id`, `account_id`가 쿼리 파라미터로 포함된다
- 고객사/어카운트 목록은 백엔드 API에서 조회한다 (현재: Mock)
- "내 담당 고객사" 필터: localStorage 기반으로 즐겨찾기 고객사 우선 표시 ✅

---

### 3-2. Dashboard 페이지 🔶 P1 — `6h`

**사용자 스토리:** 인프라 엔지니어로서, 전체 모니터링 현황을 한눈에 보고 즉각 대응이 필요한 항목을 파악하고 싶다.

**인수 조건:**
- 통계 카드 4개: 모니터링 중인 리소스 수, 활성 알람 수, 미모니터링 리소스 수, 등록된 어카운트 수
- 활성 알람 수 > 0일 때 카드가 빨간색 강조로 표시된다
- 최근 알람 트리거 테이블(최근 10건): 시간·리소스·유형·메트릭·상태·값/임계치 컬럼
- 각 행에 Severity Badge(SEV-1~5 색상 코딩)가 표시된다
- 새로고침 버튼 클릭 시 실시간 데이터 재조회

**현황:** UI 레이아웃 완료, 백엔드 API 연동 필요.

---

### 3-3. Resources 목록 페이지 🔶 P1 — `1d`

**사용자 스토리:** 인프라 엔지니어로서, 수백 개의 리소스를 빠르게 필터링하고 일괄로 모니터링을 설정하고 싶다.

**인수 조건:**
- 필터 바: 고객사·어카운트·서비스/프로젝트·리소스 타입·리전·모니터링 상태·자유 텍스트 검색
- 리소스 타입 드롭다운은 6개 카테고리(Compute·Database·Network·Storage·Application·Security)로 그룹화
- 테이블 컬럼: 체크박스·고객사·리소스 ID·이름·타입·어카운트·리전·모니터링 토글·활성 알람 배지
- 활성 알람 배지에 Severity 등급 포함 표시 (예: "2 SEV-1" 빨간색)
- 서버사이드 페이지네이션: 25·50·100 행/페이지, 총 건수 표시
- 체크박스 선택 시 벌크 액션 바 출력: 모니터링 활성화·비활성화·알람 설정
- CSV 내보내기, "리소스 동기화" 버튼
- 하단 요약: 전체 모니터링 수·활성 알람 수·동기화 상태·커버리지

**현황:** UI 레이아웃 완료, 백엔드 API 연동 및 서버사이드 페이지네이션 구현 필요.

---

### 3-4. Resource Detail 페이지 🔶 P1 — `1d`

**사용자 스토리:** 인프라 엔지니어로서, 특정 리소스의 모든 알람 설정을 한 페이지에서 조회·수정하고 싶다.

**인수 조건:**
- 헤더: 리소스 ID·이름·타입·어카운트·리전·태그 목록·모니터링 마스터 토글 표시
- 알람 설정 테이블: 메트릭명·Severity Badge·방향 아이콘(▲/▼)·임계치·Source Badge(System/Customer/Custom)·모니터링 토글·CloudWatch 알람 상태
- 임계치 인라인 편집: 클릭 → 숫자 입력 → 즉시 저장 (단일 메트릭만 업데이트)
- CloudWatch 콘솔 직접 링크 제공
- 커스텀 메트릭 추가: 기본 정의에 없는 메트릭을 수동으로 추가
- 변경 이력 패널(감사 로그): 최근 임계치·모니터링 상태 변경 내역

**현황:** UI 레이아웃 완료, 백엔드 연동 필요.

---

### 3-5. Alarms 페이지 🔶 P1 — `4h`

**사용자 스토리:** 인프라 엔지니어로서, 현재 활성화된 모든 알람을 한 곳에서 보고 상태별로 필터링하고 싶다.

**인수 조건:**
- 알람 목록 테이블: 알람 이름·리소스·메트릭·상태(OK/ALARM/INSUFFICIENT_DATA)·Severity Badge·임계치·마지막 변경 시간
- 상태별 필터: OK·ALARM·INSUFFICIENT_DATA
- 알람 행 클릭 시 해당 Resource Detail 페이지로 이동
- 요약 카드: 상태별 건수 집계

**현황:** UI 레이아웃 완료, 백엔드 연동 필요.

---

### 3-6. Settings 페이지 🔶 P1 — `1d`

**사용자 스토리:** MSP 엔지니어로서, 고객사와 AWS 어카운트를 UI에서 등록·수정·삭제하고 고객사별 기본 임계치를 설정하고 싶다.

**인수 조건:**
- 고객사 CRUD: 이름·설명·담당자 필드, 삭제 시 연결 어카운트 경고
- 어카운트 CRUD: AWS Account ID·리전·고객사 연결·AssumeRole ARN
- 고객사별 임계치 오버라이드: 메트릭별 기본값을 고객사 전체에 적용
- 변경 사항 저장 시 Toast 알림(성공/실패)
- 시스템 기본 임계치 테이블 조회 (읽기 전용)

**현황:** UI 레이아웃 완료, 백엔드 CRUD API 연동 필요.

---

### 3-7. Create Alarm 모달 🔶 P1 — `4h`

**사용자 스토리:** 인프라 엔지니어로서, 대화형 UI로 여러 리소스에 알람을 일괄 생성하고 싶다. 태그 작업 없이 UI에서 직접 처리하기 위해.

**인수 조건:**
- 3단계 위저드: Track 선택(Standard/Custom) → 리소스 필터 → 메트릭 임계치 구성
- Track 선택: 시스템 기본값 사용 or 커스텀 메트릭 직접 지정
- 리소스 필터: 고객사·어카운트·리소스 타입·리전 필터로 대상 리소스 선택
- 메트릭 구성: 적용할 메트릭과 임계치를 확인·수정
- 제출 후 SQS 비동기 처리, 진행 상태 토스트 표시

**현황:** UI 레이아웃 완료, 백엔드 연동 필요.

---

### 3-8. Toast 알림 시스템 ❌ P1 — `2h`

**사용자 스토리:** 인프라 엔지니어로서, 모니터링 토글·벌크 액션·동기화 등 모든 작업 결과를 즉시 피드백으로 받고 싶다.

**인수 조건:**
- 성공(초록)·실패(빨강)·경고(앰버)·정보(파랑) 4가지 토스트 타입
- 자동 소멸(기본 5초), 닫기 버튼 제공
- 부분 실패 시 실패 리소스 ID 목록 표시
- 여러 토스트 동시 스택 표시 지원

**현황:** 미구현.

---

### 3-9. 에러 핸들링 및 로딩 상태 ❌ P1 — `4h`

**사용자 스토리:** 인프라 엔지니어로서, API 오류 시 명확한 에러 메시지와 재시도 버튼이 표시되길 원한다. 빈 화면이나 무한 로딩 상태에서 무엇을 해야 할지 모르기 때문이다.

**인수 조건:**
- 데이터 로딩 중: 스켈레톤 플레이스홀더 표시 (테이블 헤더는 유지)
- API 오류 시: 에러 메시지 + 재시도 버튼 인라인 표시
- 네트워크 오류와 서버 오류를 구분하여 다른 메시지 표시
- 페이지 전체 오류: `error.tsx` 경계로 폴백 UI 표시

**현황:** `error.tsx`, `loading.tsx` 파일 존재하나 실질적인 에러 핸들링 로직 미구현.

---

## 4. 테스트 품질

### 4-1. 핵심 모듈 단위 테스트 🔶 P0 — `1d`

**사용자 스토리:** 개발자로서, 핵심 비즈니스 로직 모듈에 테스트가 존재하여 리팩터링 시 리그레션을 즉시 감지하고 싶다.

**인수 조건:**
- `alarm_builder.py`: `_create_standard_alarm()`, 리전 분기(글로벌 us-east-1), AlarmActions 검증 — ✅ 완료
- `alarm_naming.py`: 이름 포맷·truncate·라운드트립 파싱 PBT — ✅ 완료
- `dimension_builder.py`: 리소스 타입별 디멘션 조합, Compound Dimension — ❌ 미완
- `threshold_resolver.py`: 3단계 폴백·단위 환산·Threshold_off 처리 — ✅ 완료 (일부)
- common/ 모듈 커버리지 80% 이상 달성

---

### 4-2. Property-Based Testing (PBT) 보강 🔶 P1 — `1d`

**사용자 스토리:** 개발자로서, 엣지 케이스와 무작위 입력에 대해서도 비즈니스 속성이 항상 성립함을 수학적으로 검증하고 싶다.

**인수 조건:**
- `tag-driven-alarm-engine` 8개 Property PBT 통과: 태그 값 보존·off 처리·메트릭 키 유일성·디멘션 해석 등
- `alarm_naming` PBT: 255자 이하 보장·라운드트립·Short_ID 역변환·truncate 접미사
- `dimension_builder` PBT: ALB LB 레벨에 TG 디멘션 미포함·TG 레벨에 LoadBalancer 항상 포함
- `alarm-manager-frontend-features` 10개 속성 테스트 (TypeScript)

---

### 4-3. E2E 검증 인프라 🔶 P2 — `4h`

**사용자 스토리:** 개발자로서, 배포 전 실제 AWS 환경에서 전체 모니터링 파이프라인이 올바르게 동작하는지 검증하고 싶다.

**인수 조건:**
- `remaining-resources-e2e-test` CFN 스택이 8개 리소스 타입을 생성한다
- 트래픽 생성 스크립트가 Phase 1~5 순서로 실행된다 (APIGW Phase 3 curl 20회 포함)
- daily_monitor 실행 후 전체 리소스 타입에 알람이 올바르게 생성된다
- 스택 삭제 후 고아 알람이 자동 정리된다

---

## 5. 인프라·배포 (CloudFormation)

### 5-1. 완전한 IaC 프로비저닝 🔶 P0 — `1d`

**사용자 스토리:** DevOps 엔지니어로서, `template.yaml` 하나로 전체 시스템을 프로비저닝하고 싶다. 수작업 콘솔 설정 없이 재현 가능한 배포를 원하기 때문이다.

**인수 조건:**
- DynamoDB 테이블(Customers, Accounts, ThresholdOverrides) 프로비저닝
- SQS FIFO 큐(WorkerQueue) 프로비저닝
- API Gateway + api_handler Lambda 프로비저닝
- 모든 리소스는 `Pseudo Parameters`(`AWS::AccountId`, `AWS::Region`) 사용
- Lambda 런타임은 `Mappings.LambdaConfig.Settings.Runtime`에서 단일 관리

**현황:** Daily Monitor·Remediation Handler Lambda 프로비저닝 완료. API Gateway·DynamoDB·SQS 미추가.

---

### 5-2. 프론트엔드 배포 자동화 ❌ P2 — `4h`

**사용자 스토리:** DevOps 엔지니어로서, 프론트엔드 빌드·배포가 백엔드 배포와 함께 자동화되길 원한다.

**인수 조건:**
- `next build` 결과를 S3 정적 호스팅 또는 CloudFront에 배포
- `NEXT_PUBLIC_API_BASE_URL`이 배포 환경별로 자동 주입된다
- `npm run build && aws s3 sync` 배포 스크립트 제공

---

## 6. 구현 우선순위 요약

| 우선순위 | 기능 | 예상 시간 | 상태 |
|---------|------|----------|------|
| P0 | API Gateway + api_handler Lambda | 2일 | ❌ |
| P0 | DynamoDB 데이터 모델 | 1일 | ❌ |
| P0 | 완전한 IaC 프로비저닝 | 1일 | 🔶 |
| P0 | dimension_builder 단위 테스트 | 0.5일 | ❌ |
| P1 | Severity 등급 자동 부여 | 4h | 🔶 |
| P1 | SQS FIFO 비동기 처리 | 4h | ❌ |
| P1 | 글로벌 필터 백엔드 연동 | 4h | 🔶 |
| P1 | Dashboard 백엔드 연동 | 6h | 🔶 |
| P1 | Resources 목록 백엔드 연동 + 페이지네이션 | 1일 | 🔶 |
| P1 | Resource Detail 백엔드 연동 | 1일 | 🔶 |
| P1 | Settings CRUD 백엔드 연동 | 1일 | 🔶 |
| P1 | Toast 알림 시스템 | 2h | ❌ |
| P1 | 에러 핸들링·로딩 상태 | 4h | ❌ |
| P1 | PBT 보강 (tag-driven + naming + dimension) | 1일 | 🔶 |
| P2 | 동적 알람 방향 제어 (`LT_` prefix) | 6h | ❌ |
| P2 | 글로벌 서비스 알람 알림 (us-east-1) | 8h | ❌ |
| P2 | E2E 검증 인프라 완성 | 4h | 🔶 |
| P2 | 프론트엔드 배포 자동화 | 4h | ❌ |

**총 예상 시간:**  
- P0: ~4.5일  
- P1: ~9일  
- P2: ~2.5일  
- **전체 합계: 약 16일 (1인 기준, 테스트 포함)**
