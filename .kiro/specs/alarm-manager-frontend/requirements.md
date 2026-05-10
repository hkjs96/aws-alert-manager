# 요구사항 문서: Alarm Manager 프론트엔드 (MVP)

## 소개

AWS CloudWatch 알람 임계치를 다수의 고객사/어카운트에 걸쳐 관리하는 웹 애플리케이션(MVP).
Phase1 백엔드(Python Lambda 기반 알람 자동 생성/동기화 엔진)의 수동 태그 관리를 대체하여,
인프라 엔지니어가 UI를 통해 리소스 조회, 모니터링 토글, 알람 임계치 설정을 수행할 수 있도록 한다.

기술 스택: React + TypeScript + Tailwind CSS
백엔드 API: API Gateway + Lambda (api_handler), 기존 Phase1 alarm_manager 함수 호출
지원 리소스: 30종 (EC2, RDS, AuroraRDS, ALB, NLB, CLB, TG, DocDB, ElastiCache, NAT, Lambda, VPN, APIGW, ACM, Backup, MQ, OpenSearch, SQS, ECS, MSK, DynamoDB, CloudFront, WAF, Route53, DX, EFS, S3, SageMaker, SNS)

## 용어 정의

- **Alarm_Manager_App**: Alarm Manager 프론트엔드 웹 애플리케이션 전체
- **Dashboard_Page**: 모니터링 현황 요약을 표시하는 대시보드 페이지
- **Resources_Page**: 리소스 목록 조회 및 필터링, 벌크 액션을 제공하는 페이지
- **Resource_Detail_Page**: 개별 리소스의 알람 설정을 관리하는 상세 페이지
- **Settings_Page**: 고객사, 어카운트, 기본 임계치 오버라이드를 관리하는 설정 페이지
- **Backend_API**: API Gateway + Lambda(api_handler)로 구성된 백엔드 REST API
- **Alarm_Registry**: Phase1 alarm_registry.py에 정의된 리소스 유형별 알람 정의 데이터
- **Severity_Badge**: SEV-1~SEV-5 등급을 읽기 전용 아웃라인 뱃지로 표시하는 UI 컴포넌트
- **Source_Badge**: 임계치 출처(System/Customer/Custom)를 표시하는 UI 컴포넌트
- **Direction_Icon**: 메트릭 비교 방향(▲ GreaterThan / ▼ LessThan)을 표시하는 아이콘
- **Monitoring_Toggle**: 리소스 또는 개별 메트릭의 모니터링 활성화/비활성화 스위치
- **Threshold_Override**: 고객사별 또는 리소스별로 시스템 기본 임계치를 덮어쓰는 설정값
- **Custom_Metric**: 하드코딩 알람 정의에 없는 사용자 추가 메트릭
- **Sync_Status**: Phase1 엔진과 실제 CloudWatch 알람 간의 동기화 상태
- **Resource_Type_Category**: 리소스 유형을 Compute/Database/Network/Storage/Application/Security로 분류한 그룹

## 요구사항

### 요구사항 1: 애플리케이션 레이아웃 및 내비게이션

**사용자 스토리:** 인프라 엔지니어로서, 일관된 레이아웃과 내비게이션을 통해 Alarm Manager의 모든 기능에 빠르게 접근하고 싶다.

#### 인수 조건

1. THE Alarm_Manager_App SHALL 상단 바에 로고("Alarm Manager"), 글로벌 필터(고객사/어카운트/서비스 드롭다운), 사용자 아바타를 표시한다
2. THE Alarm_Manager_App SHALL 좌측 사이드바에 Dashboard, Resources, Settings 내비게이션 항목을 제공한다
3. THE Alarm_Manager_App SHALL 좌측 사이드바를 아이콘 전용 모드로 축소할 수 있는 토글을 제공한다
4. WHEN 사용자가 글로벌 필터에서 고객사 또는 어카운트를 선택하면, THE Alarm_Manager_App SHALL 모든 페이지의 데이터를 선택된 필터 기준으로 갱신한다
5. THE Alarm_Manager_App SHALL 라이트 테마를 적용한다 (흰색 배경, 연한 회색(#f8fafc) 사이드바, 파란색(#2563eb) 액센트)
6. THE Alarm_Manager_App SHALL 상단 바에 서비스 스위처 슬롯을 예약한다 (현재는 "Alarm Manager" 단독 표시, 향후 24x7 Monitoring 등 추가 대비)


### 요구사항 2: Dashboard 페이지

**사용자 스토리:** 인프라 엔지니어로서, 전체 모니터링 현황을 한눈에 파악하여 즉각적인 대응이 필요한 항목을 식별하고 싶다.

#### 인수 조건

1. THE Dashboard_Page SHALL 4개의 통계 카드를 표시한다: 모니터링 중인 리소스 수, 활성 알람 수, 미모니터링 리소스 수, 등록된 어카운트 수
2. WHEN 활성 알람 수가 0보다 크면, THE Dashboard_Page SHALL 활성 알람 카드를 빨간색 강조로 표시한다
3. THE Dashboard_Page SHALL 최근 알람 트리거 테이블(최근 10건)을 표시한다 (컬럼: 시간, 리소스, 유형, 메트릭, 상태, 값/임계치)
4. THE Dashboard_Page SHALL 각 알람 트리거 행에 Severity_Badge를 표시한다
5. WHEN 글로벌 필터가 적용되면, THE Dashboard_Page SHALL 선택된 고객사/어카운트 범위의 데이터만 집계하여 표시한다

### 요구사항 3: Resources 목록 페이지

**사용자 스토리:** 인프라 엔지니어로서, 다수의 어카운트에 걸친 AWS 리소스를 필터링하고 조회하여 모니터링 대상을 효율적으로 관리하고 싶다.

#### 인수 조건

1. THE Resources_Page SHALL 필터 바를 제공한다 (고객사, 어카운트, 서비스/프로젝트, 리소스 유형, 리전, 모니터링 상태, 자유 텍스트 검색)
2. THE Resources_Page SHALL 리소스 유형 드롭다운을 Resource_Type_Category별로 그룹화하여 표시한다 (Compute: EC2, Lambda, ECS, SageMaker / Database: RDS, AuroraRDS, DocDB, ElastiCache, DynamoDB / Network: ALB, NLB, CLB, TG, NAT, VPN, Route53, DX, CloudFront / Storage: S3, EFS, Backup / Application: APIGW, SQS, MSK, SNS, MQ / Security: WAF, ACM, OpenSearch)
3. THE Resources_Page SHALL 리소스 테이블을 표시한다 (컬럼: 체크박스, 고객사, 리소스 ID(모노스페이스), 이름, 유형(아이콘), 어카운트, 리전, 모니터링(토글 스위치), 활성 알람(뱃지))
4. THE Resources_Page SHALL 활성 알람 뱃지에 Severity 등급을 포함하여 표시한다 (예: "2 SEV-1"(빨간색), "1 SEV-3"(앰버), "0 ACTIVE"(회색))
5. WHEN 사용자가 하나 이상의 리소스를 체크박스로 선택하면, THE Resources_Page SHALL 벌크 액션 바를 표시한다 (모니터링 활성화, 모니터링 비활성화, 알람 설정)
6. WHEN 사용자가 리소스 행을 클릭하면, THE Resources_Page SHALL Resource_Detail_Page로 이동한다
7. THE Resources_Page SHALL 페이지네이션을 제공한다
8. THE Resources_Page SHALL CSV 내보내기 기능을 제공한다
9. THE Resources_Page SHALL "리소스 동기화" 버튼을 제공한다
10. THE Resources_Page SHALL 하단에 통계 요약을 표시한다 (전체 모니터링 수, 활성 알람 수, 동기화 상태, 커버리지)


### 요구사항 4: Resource Detail 페이지 — 헤더 및 모니터링 토글

**사용자 스토리:** 인프라 엔지니어로서, 개별 리소스의 기본 정보를 확인하고 모니터링 활성화/비활성화를 제어하고 싶다.

#### 인수 조건

1. THE Resource_Detail_Page SHALL 헤더 영역에 리소스 ID, 이름, 유형, 어카운트, 리전을 표시한다
2. THE Resource_Detail_Page SHALL 헤더 영역에 대형 모니터링 ON/OFF Monitoring_Toggle을 제공한다
3. WHEN 사용자가 Monitoring_Toggle을 OFF로 전환하면, THE Resource_Detail_Page SHALL 해당 리소스의 모든 알람을 비활성화 처리한다
4. WHEN 사용자가 Monitoring_Toggle을 ON으로 전환하면, THE Resource_Detail_Page SHALL 해당 리소스의 알람 설정 테이블에 따라 알람을 활성화한다

### 요구사항 5: Resource Detail 페이지 — 알람 설정 테이블

**사용자 스토리:** 인프라 엔지니어로서, 리소스 유형에 맞는 메트릭별 알람 임계치를 조회하고 개별적으로 설정하고 싶다.

#### 인수 조건

1. THE Resource_Detail_Page SHALL 리소스 유형에 따라 Alarm_Registry 기반의 알람 설정 테이블을 자동 생성한다 (30종 리소스 유형 지원)
2. THE Resource_Detail_Page SHALL 알람 설정 테이블에 다음 컬럼을 표시한다: 개별 모니터링 토글, 메트릭명, CW 메트릭명(회색 모노스페이스), 임계치(편집 가능 숫자 입력), 단위, Direction_Icon, Severity_Badge(읽기 전용), Source_Badge, 상태, 현재 값
3. THE Resource_Detail_Page SHALL Direction_Icon을 메트릭 비교 방향에 따라 표시한다 (▲ 빨간/주황 = GreaterThan: CPU, Memory, Disk, ELB5XX, Errors, Connections 등 / ▼ 파란 = LessThan: FreeMemoryGB, FreeStorageGB, HealthyHostCount, TunnelState 등)
4. THE Resource_Detail_Page SHALL Severity_Badge를 읽기 전용 아웃라인 스타일로 표시한다 (SEV-1: 빨간 아웃라인, SEV-2: 주황, SEV-3: 앰버, SEV-4: 파란, SEV-5: 회색)
5. THE Resource_Detail_Page SHALL Source_Badge를 표시한다 ("System": 회색 — 시스템 기본값, "Customer": 파란색 — 고객사 오버라이드, "Custom": 보라색 — 사용자 추가 메트릭)
6. THE Resource_Detail_Page SHALL 알람 상태를 색상 코드로 표시한다 (OK: 초록, ALARM: 빨간, INSUFFICIENT_DATA: 앰버, OFF: 회색)
7. WHEN EC2 리소스의 Disk 메트릭인 경우, THE Resource_Detail_Page SHALL 마운트 경로별로 개별 행을 표시한다 (예: Disk Usage (/), Disk Usage (/data), Disk Usage (/opt))
8. THE Resource_Detail_Page SHALL "변경사항 저장" 및 "기본값으로 초기화" 버튼을 제공한다
9. WHEN 저장되지 않은 변경사항이 있으면, THE Resource_Detail_Page SHALL 미저장 변경 표시기를 표시한다
10. THE Resource_Detail_Page SHALL 최근 이벤트 섹션을 표시한다


### 요구사항 6: Resource Detail 페이지 — 커스텀 메트릭 추가

**사용자 스토리:** 인프라 엔지니어로서, 하드코딩 알람 정의에 없는 추가 메트릭에 대해서도 알람을 설정하고 싶다.

#### 인수 조건

1. THE Resource_Detail_Page SHALL "커스텀 메트릭 추가" 버튼을 제공한다
2. WHEN 사용자가 "커스텀 메트릭 추가" 버튼을 클릭하면, THE Resource_Detail_Page SHALL 인라인 입력 폼을 표시한다 (메트릭명: 자동완성 드롭다운, 임계치: 숫자 입력, 방향: ▲/▼ 드롭다운(기본값 ▲), 단위: 자동 채움 또는 수동 입력)
3. THE Resource_Detail_Page SHALL 커스텀 메트릭 자동완성 드롭다운을 CloudWatch list_metrics API 결과로 채운다 (하드코딩 메트릭 제외, "MetricName (Namespace)" 형식 표시)
4. THE Resource_Detail_Page SHALL 자유 텍스트 입력도 허용한다 (CloudWatch에 아직 데이터가 없는 메트릭 대비)
5. WHEN 입력된 메트릭이 CloudWatch에 존재하면, THE Resource_Detail_Page SHALL 초록색 검증 표시기를 표시한다 (✅ "Metric found: {MetricName} ({Namespace}, {Dimension})")
6. WHEN 입력된 메트릭이 CloudWatch에 존재하지 않으면, THE Resource_Detail_Page SHALL 앰버색 경고 표시기를 표시한다 (⚠️ "Metric not found in CloudWatch. Alarm will be INSUFFICIENT_DATA.")
7. THE Resource_Detail_Page SHALL 추가된 커스텀 알람을 별도 테이블로 표시한다 (컬럼: 메트릭, 네임스페이스, 임계치, 방향, 상태, 출처(Tag/UI), 액션)

### 요구사항 7: Settings 페이지 — 고객사 관리

**사용자 스토리:** 인프라 엔지니어로서, 모니터링 대상 고객사를 등록하고 관리하고 싶다.

#### 인수 조건

1. THE Settings_Page SHALL 고객사 목록을 표시한다 (이름, 코드, 연결된 어카운트 수)
2. THE Settings_Page SHALL 고객사 추가 폼을 제공한다 (이름, 코드, 연결할 어카운트)
3. THE Settings_Page SHALL 고객사 편집 기능을 제공한다
4. THE Settings_Page SHALL 고객사 삭제 기능을 제공한다
5. WHEN 고객사를 삭제하려 할 때 연결된 어카운트가 존재하면, THE Settings_Page SHALL 삭제 확인 경고를 표시한다

### 요구사항 8: Settings 페이지 — 어카운트 등록

**사용자 스토리:** 인프라 엔지니어로서, 모니터링 대상 AWS 어카운트를 등록하고 연결 상태를 확인하고 싶다.

#### 인수 조건

1. THE Settings_Page SHALL 어카운트 목록을 표시한다 (어카운트 ID, 이름, Role ARN, 연결된 고객사, 연결 상태)
2. THE Settings_Page SHALL 어카운트 추가 폼을 제공한다 (어카운트 ID, 이름, Role ARN, 고객사 선택)
3. THE Settings_Page SHALL 각 어카운트 행에 "연결 테스트" 버튼을 제공한다
4. WHEN 사용자가 "연결 테스트" 버튼을 클릭하면, THE Backend_API SHALL AssumeRole 유효성을 검증하고 결과를 반환한다
5. THE Settings_Page SHALL 어카운트 편집 및 삭제 기능을 제공한다


### 요구사항 9: Settings 페이지 — 기본 임계치 오버라이드

**사용자 스토리:** 인프라 엔지니어로서, 고객사별로 리소스 유형에 따른 기본 알람 임계치를 오버라이드하여 고객 환경에 맞는 모니터링 정책을 적용하고 싶다.

#### 인수 조건

1. THE Settings_Page SHALL 30종 리소스 유형을 수평 스크롤 가능한 탭으로 표시한다 (EC2, RDS, AuroraRDS, ALB, NLB, CLB, TG, DocDB, ElastiCache, NAT, Lambda, VPN, APIGW, ACM, Backup, MQ, OpenSearch, SQS, ECS, MSK, DynamoDB, CloudFront, WAF, Route53, DX, EFS, S3, SageMaker, SNS)
2. WHEN 사용자가 리소스 유형 탭을 선택하면, THE Settings_Page SHALL 해당 유형의 Alarm_Registry 기반 메트릭 카드 목록을 표시한다
3. THE Settings_Page SHALL 각 메트릭 카드에 메트릭명, CW 메트릭명, 비교 방향(> 또는 <), 시스템 기본값, 고객사별 오버라이드 목록을 표시한다
4. THE Settings_Page SHALL 각 메트릭 카드에 "오버라이드 추가" 버튼을 제공한다 (고객사 선택 + 임계치 값 입력)
5. WHEN 사용자가 오버라이드를 추가하면, THE Settings_Page SHALL 해당 고객사의 모든 리소스에 적용될 기본 임계치를 저장한다
6. THE Settings_Page SHALL 오버라이드 편집 및 삭제 기능을 제공한다

### 요구사항 10: Backend API 연동

**사용자 스토리:** 인프라 엔지니어로서, UI에서 수행하는 모든 조회/설정 작업이 실제 AWS 리소스에 반영되기를 원한다.

#### 인수 조건

1. THE Backend_API SHALL API Gateway + Lambda(api_handler) 구조로 구성된다
2. THE Backend_API SHALL 기존 Phase1 alarm_manager 함수(create_alarms_for_resource, sync_alarms_for_resource 등)를 호출하여 알람 CRUD를 수행한다
3. THE Backend_API SHALL 리소스 목록 조회 시 대상 어카운트에 AssumeRole하여 리소스 정보를 수집한다
4. THE Backend_API SHALL 알람 상태 조회 시 CloudWatch DescribeAlarms + list_tags_for_resource를 호출하여 Severity 태그를 포함한 알람 정보를 반환한다
5. THE Backend_API SHALL 커스텀 메트릭 자동완성을 위해 CloudWatch list_metrics API를 프록시한다
6. IF Backend_API 호출이 실패하면, THEN THE Alarm_Manager_App SHALL 사용자에게 에러 메시지를 표시하고 재시도 옵션을 제공한다
7. THE Backend_API SHALL 임계치 조회 우선순위를 준수한다 (리소스별 태그 > 고객사 오버라이드 > 환경 변수 > 시스템 하드코딩 기본값)
8. THE Backend_API SHALL 벌크 작업 및 비동기 알람 CRUD를 위해 SQS FIFO 큐를 사용한다 (MessageGroupId: "{account_id}:{resource_id}", MessageDeduplicationId: "{request_id}")
9. THE Backend_API SHALL SQS FIFO 처리 실패 시 DLQ(Dead Letter Queue)로 메시지를 이동한다 (MaxReceiveCount: 3)
10. THE Backend_API SHALL DLQ에 메시지가 존재하면 CloudWatch 알람을 통해 운영팀에 알린다
11. THE Backend_API SHALL 비동기 작업의 진행 상태를 DynamoDB에 기록하고, 프론트엔드가 polling으로 조회할 수 있는 상태 조회 API를 제공한다

### 요구사항 11: Severity 표시

**사용자 스토리:** 인프라 엔지니어로서, 각 알람의 심각도 등급을 시각적으로 확인하여 우선순위를 판단하고 싶다.

#### 인수 조건

1. THE Alarm_Manager_App SHALL Severity_Badge를 읽기 전용 아웃라인 스타일로 표시한다 (SEV-1: #dc2626 빨간 아웃라인, SEV-2: #ea580c 주황, SEV-3: #d97706 앰버, SEV-4: #2563eb 파란, SEV-5: #6b7280 회색)
2. THE Alarm_Manager_App SHALL Severity 등급을 시스템 기본값(_DEFAULT_SEVERITY dict)에서 조회하여 표시한다
3. WHEN 메트릭에 대한 기본 Severity가 정의되지 않은 경우, THE Alarm_Manager_App SHALL SEV-5(Info)로 폴백하여 표시한다
4. THE Alarm_Manager_App SHALL Severity 등급 변경 기능을 제공하지 않는다 (MVP 범위: 읽기 전용, 변경은 Phase2 24x7 관제에서 지원)


### 요구사항 12: 벌크 액션

**사용자 스토리:** 인프라 엔지니어로서, 다수의 리소스에 대해 모니터링 설정을 일괄 변경하여 운영 효율을 높이고 싶다.

#### 인수 조건

1. WHEN 사용자가 Resources_Page에서 복수의 리소스를 선택하면, THE Resources_Page SHALL 벌크 액션 바를 표시한다 (모니터링 활성화, 모니터링 비활성화, 알람 설정)
2. WHEN 사용자가 벌크 액션을 실행하면, THE Backend_API SHALL 각 리소스별 작업을 SQS FIFO 큐에 enqueue하고 즉시 job_id를 반환한다
3. THE Alarm_Manager_App SHALL 반환된 job_id로 작업 진행 상태를 polling하여 프로그레스 바를 표시한다 (처리 완료 수 / 전체 수)
4. WHEN 사용자가 "알람 설정" 벌크 액션을 실행하면, THE Resources_Page SHALL 선택된 리소스들에 공통 적용할 메트릭별 임계치 입력 폼을 표시한다 (선택적 메트릭 업데이트: 체크된 메트릭만 변경, 미체크 메트릭은 기존 값 유지)
5. IF 벌크 액션 중 일부 리소스에서 오류가 발생하면, THEN THE Alarm_Manager_App SHALL 성공/실패 결과 요약을 표시한다 (실패 건은 DLQ로 이동)
6. THE Alarm_Manager_App SHALL 벌크 작업 이력을 조회할 수 있는 기능을 제공한다 (job_id, 시작 시간, 상태, 성공/실패 수)

### 요구사항 13: 데이터 모델 확장성

**사용자 스토리:** 플랫폼 관리자로서, 향후 멀티 클라우드 및 서비스 확장에 대비한 데이터 모델을 갖추고 싶다.

#### 인수 조건

1. THE Backend_API SHALL 리소스 데이터 모델에 provider 필드를 포함한다 (기본값: "aws")
2. THE Resources_Page SHALL 필터 바에 Cloud Provider 슬롯을 예약한다 (현재는 AWS만 표시, 향후 확장 대비)
3. THE Backend_API SHALL AlarmDescription 메타데이터에 customer_id, account_id 필드를 포함한다

### 요구사항 14: 디자인 시스템

**사용자 스토리:** 인프라 엔지니어로서, 일관된 시각적 언어를 통해 알람 상태와 심각도를 직관적으로 파악하고 싶다.

#### 인수 조건

1. THE Alarm_Manager_App SHALL 알람 상태를 다음 색상 코드로 표시한다 (OK: 초록, ALARM: 빨간, INSUFFICIENT_DATA: 앰버, OFF: 회색)
2. THE Alarm_Manager_App SHALL Source_Badge를 다음 스타일로 표시한다 ("System": 회색 배경(#f1f5f9) + 회색 텍스트, "Customer": 파란 배경(#eff6ff) + 파란 텍스트, "Custom": 보라 배경(#f5f3ff) + 보라 텍스트)
3. THE Alarm_Manager_App SHALL Direction_Icon을 다음 스타일로 표시한다 (▲: 빨간/주황 틴트 — GreaterThan, ▼: 파란 틴트 — LessThan)
4. THE Alarm_Manager_App SHALL 리소스 ID, CW 메트릭명 등 기술 식별자를 모노스페이스 폰트로 표시한다
5. THE Alarm_Manager_App SHALL 시스템 산세리프 폰트를 기본 폰트로 사용한다

### 요구사항 15: 알림 흐름

**사용자 스토리:** 인프라 엔지니어로서, 알람 발생 시 기존 Slack 알림 파이프라인을 통해 통보받고 싶다.

#### 인수 조건

1. THE Alarm_Manager_App SHALL 알림 채널 관리 UI를 제공하지 않는다 (기존 AWS Chatbot → Slack 파이프라인 사용, 알림 채널 관리는 Phase2 24x7 관제 범위)
2. WHEN 알람이 생성되면, THE Backend_API SHALL 기존 SNS 토픽을 AlarmActions에 연결하여 기존 알림 파이프라인을 유지한다
3. WHEN 알람이 생성되면, THE Backend_API SHALL CloudWatch 알람 태그에 Severity 값과 ManagedBy=AlarmManager 태그를 설정한다

