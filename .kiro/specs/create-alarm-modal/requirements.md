# Requirements Document

## Introduction

Dashboard의 "Create Alarm" 버튼을 클릭하면 열리는 알람 생성 모달을 구현한다. 모달은 두 가지 트랙으로 분기된다:
- **트랙 1 (커스텀 알람 추가)**: 이미 모니터링 중인 리소스에 커스텀 CloudWatch 메트릭 알람을 추가한다.
- **트랙 2 (새 모니터링 설정)**: 미모니터링 리소스에 대해 모니터링을 활성화하고 기본 메트릭 + 커스텀 메트릭 알람을 일괄 생성한다.

모달 내부에서 고객사 → 어카운트 → 리소스 순으로 캐스케이딩 필터를 거쳐 대상 리소스를 선택하고, 선택된 리소스 타입에 맞는 메트릭 설정 UI를 표시한다.

## Glossary

- **CreateAlarmModal**: 알람 생성 모달 최상위 Client Component
- **TrackSelector**: 트랙 1(커스텀 알람 추가)과 트랙 2(새 모니터링 설정) 중 하나를 선택하는 카드 UI 컴포넌트
- **ResourceFilterStep**: 고객사 → 어카운트 → 리소스 순서로 캐스케이딩 드롭다운을 제공하는 필터 컴포넌트
- **MetricConfigStep**: 선택된 트랙과 리소스 타입에 따라 메트릭 설정 UI를 표시하는 컴포넌트
- **InfoBanner**: SNS 토픽 안내 등 정보성 배너 컴포넌트
- **ModalFooter**: Cancel 및 Create Alarm 버튼을 포함하는 모달 하단 컴포넌트
- **Customer**: 고객사 엔티티 (MOCK_CUSTOMERS 데이터 소스)
- **Account**: AWS 어카운트 엔티티 (MOCK_ACCOUNTS 데이터 소스)
- **Resource**: AWS 리소스 엔티티 (MOCK_RESOURCES 데이터 소스, monitoring 필드로 모니터링 상태 구분)
- **METRICS_BY_TYPE**: 리소스 타입별 기본 메트릭 정의 (MetricConfigSection.tsx)
- **AVAILABLE_CW_METRICS**: 리소스 타입별 추가 가능한 CloudWatch 커스텀 메트릭 목록 (MetricConfigSection.tsx)
- **Toast**: 작업 결과를 사용자에게 알리는 글로벌 알림 컴포넌트
- **Cascading_Filter**: 상위 드롭다운 선택에 따라 하위 드롭다운 옵션이 자동 필터링되는 UI 패턴

## Requirements

### Requirement 1: 모달 열기/닫기

**User Story:** As a 운영자, I want to Dashboard에서 "Create Alarm" 버튼을 클릭하여 알람 생성 모달을 열고 닫을 수 있기를, so that 필요할 때 알람 생성 워크플로우에 진입할 수 있다.

#### Acceptance Criteria

1. WHEN 운영자가 Dashboard의 "Create Alarm" 버튼을 클릭하면, THE CreateAlarmModal SHALL 화면 중앙에 오버레이와 함께 표시된다.
2. WHEN 운영자가 모달의 닫기(X) 버튼을 클릭하면, THE CreateAlarmModal SHALL 모달을 닫고 모든 내부 상태를 초기화한다.
3. WHEN 운영자가 모달의 Cancel 버튼을 클릭하면, THE CreateAlarmModal SHALL 모달을 닫고 모든 내부 상태를 초기화한다.
4. WHEN CreateAlarmModal이 닫힌 후 다시 열리면, THE CreateAlarmModal SHALL 트랙 선택 단계부터 초기 상태로 표시된다.

### Requirement 2: 트랙 선택

**User Story:** As a 운영자, I want to 커스텀 알람 추가와 새 모니터링 설정 중 하나를 선택할 수 있기를, so that 리소스의 모니터링 상태에 맞는 워크플로우를 진행할 수 있다.

#### Acceptance Criteria

1. WHEN CreateAlarmModal이 열리면, THE TrackSelector SHALL "커스텀 알람 추가"와 "새 모니터링 설정" 두 개의 선택 카드를 표시한다.
2. WHEN 운영자가 "커스텀 알람 추가" 카드를 클릭하면, THE TrackSelector SHALL 트랙 1을 선택 상태로 표시하고 ResourceFilterStep으로 진행한다.
3. WHEN 운영자가 "새 모니터링 설정" 카드를 클릭하면, THE TrackSelector SHALL 트랙 2를 선택 상태로 표시하고 ResourceFilterStep으로 진행한다.
4. WHEN 운영자가 트랙을 선택한 후 다른 트랙 카드를 클릭하면, THE TrackSelector SHALL 선택된 트랙을 변경하고 이전에 입력한 고객사, 어카운트, 리소스, 메트릭 설정을 모두 초기화한다.

### Requirement 3: 캐스케이딩 리소스 필터

**User Story:** As a 운영자, I want to 고객사 → 어카운트 → 리소스 순서로 필터링하여 대상 리소스를 선택할 수 있기를, so that 원하는 리소스를 정확하게 찾을 수 있다.

#### Acceptance Criteria

1. WHEN 트랙이 선택되면, THE ResourceFilterStep SHALL 고객사 드롭다운에 MOCK_CUSTOMERS의 전체 고객사 목록을 표시한다.
2. WHEN 운영자가 고객사를 선택하면, THE ResourceFilterStep SHALL 해당 고객사의 customer_id와 일치하는 어카운트만 어카운트 드롭다운에 표시한다.
3. WHEN 운영자가 고객사를 변경하면, THE ResourceFilterStep SHALL 어카운트 선택과 리소스 선택을 초기화한다.
4. WHILE 트랙 1이 선택된 상태에서, WHEN 운영자가 어카운트를 선택하면, THE ResourceFilterStep SHALL 해당 어카운트의 account_id와 일치하고 monitoring이 true인 리소스만 리소스 드롭다운에 표시한다.
5. WHILE 트랙 2가 선택된 상태에서, WHEN 운영자가 어카운트를 선택하면, THE ResourceFilterStep SHALL 해당 어카운트의 account_id와 일치하고 monitoring이 false인 리소스만 리소스 드롭다운에 표시한다.
6. WHEN 운영자가 어카운트를 변경하면, THE ResourceFilterStep SHALL 리소스 선택을 초기화한다.
7. WHEN 운영자가 리소스를 선택하면, THE ResourceFilterStep SHALL 단일 리소스만 선택 가능하도록 하고 MetricConfigStep을 표시한다.

### Requirement 4: 트랙 1 — 커스텀 메트릭 설정

**User Story:** As a 운영자, I want to 이미 모니터링 중인 리소스에 CloudWatch 커스텀 메트릭 알람을 추가할 수 있기를, so that 기본 메트릭 외에 추가적인 지표를 감시할 수 있다.

#### Acceptance Criteria

1. WHILE 트랙 1이 선택된 상태에서, WHEN 리소스가 선택되면, THE MetricConfigStep SHALL 해당 리소스 타입에 맞는 AVAILABLE_CW_METRICS 목록을 드롭다운으로 표시한다.
2. WHEN 운영자가 커스텀 메트릭을 드롭다운에서 선택하면, THE MetricConfigStep SHALL 임계치(threshold), 단위(unit), 방향(direction) 입력 필드를 표시한다.
3. THE MetricConfigStep SHALL 임계치 입력 필드에 숫자만 입력 가능하도록 한다.
4. THE MetricConfigStep SHALL 방향 입력 필드에 ">" (Above)와 "<" (Below) 두 가지 옵션을 제공한다.
5. WHILE 트랙 1이 선택된 상태에서, THE MetricConfigStep SHALL 기본 메트릭 테이블을 표시하지 않는다.

### Requirement 5: 트랙 2 — 기본 메트릭 + 커스텀 메트릭 설정

**User Story:** As a 운영자, I want to 미모니터링 리소스에 대해 기본 메트릭과 커스텀 메트릭을 함께 설정할 수 있기를, so that 모니터링 활성화와 알람 생성을 한 번에 처리할 수 있다.

#### Acceptance Criteria

1. WHILE 트랙 2가 선택된 상태에서, WHEN 리소스가 선택되면, THE MetricConfigStep SHALL 해당 리소스 타입의 METRICS_BY_TYPE 기본 메트릭 전체를 체크박스가 포함된 테이블로 표시한다.
2. THE MetricConfigStep SHALL 기본 메트릭 테이블의 각 행에 메트릭 이름, CW 메트릭명, 임계치 입력, 단위, 방향을 표시한다.
3. WHEN 운영자가 기본 메트릭의 체크박스를 해제하면, THE MetricConfigStep SHALL 해당 메트릭 행을 비활성화 상태로 표시하고 임계치 편집을 비활성화한다.
4. WHEN 운영자가 기본 메트릭의 임계치를 변경하면, THE MetricConfigStep SHALL 변경된 값을 즉시 반영한다.
5. WHILE 트랙 2가 선택된 상태에서, THE MetricConfigStep SHALL 기본 메트릭 테이블 아래에 커스텀 메트릭 추가 영역을 표시한다.
6. WHEN 운영자가 "추가" 버튼을 클릭하면, THE MetricConfigStep SHALL AVAILABLE_CW_METRICS에서 아직 추가되지 않은 메트릭만 드롭다운에 표시한다.
7. WHEN 운영자가 커스텀 메트릭을 추가하면, THE MetricConfigStep SHALL 추가된 메트릭을 커스텀 메트릭 목록에 표시하고 삭제 버튼을 제공한다.
8. WHEN 운영자가 커스텀 메트릭의 삭제 버튼을 클릭하면, THE MetricConfigStep SHALL 해당 메트릭을 커스텀 메트릭 목록에서 제거한다.

### Requirement 6: SNS 토픽 안내 배너

**User Story:** As a 운영자, I want to 알람 생성 시 SNS 토픽 관련 안내를 확인할 수 있기를, so that 알람 알림이 어디로 전달되는지 인지할 수 있다.

#### Acceptance Criteria

1. WHILE 리소스가 선택된 상태에서, THE InfoBanner SHALL 알람 알림이 전달될 SNS 토픽 정보를 안내 메시지로 표시한다.
2. THE InfoBanner SHALL 정보성 아이콘과 함께 시각적으로 구분되는 배너 형태로 표시한다.

### Requirement 7: 알람 생성 (트랙 1)

**User Story:** As a 운영자, I want to 트랙 1에서 설정한 커스텀 메트릭 알람을 생성할 수 있기를, so that 모니터링 중인 리소스에 새로운 알람이 추가된다.

#### Acceptance Criteria

1. WHILE 트랙 1이 선택되고 메트릭과 임계치가 모두 설정된 상태에서, THE ModalFooter SHALL "Create Alarm" 버튼을 활성화한다.
2. WHILE 메트릭이 선택되지 않았거나 임계치가 설정되지 않은 상태에서, THE ModalFooter SHALL "Create Alarm" 버튼을 비활성화한다.
3. WHEN 운영자가 "Create Alarm" 버튼을 클릭하면, THE CreateAlarmModal SHALL mock API를 호출하여 커스텀 알람 생성을 요청한다.
4. WHEN mock API 호출이 성공하면, THE CreateAlarmModal SHALL 성공 Toast 메시지를 표시하고 모달을 닫는다.
5. IF mock API 호출이 실패하면, THEN THE CreateAlarmModal SHALL 실패 Toast 메시지를 표시하고 모달을 유지한다.
6. WHILE API 호출이 진행 중인 상태에서, THE ModalFooter SHALL "Create Alarm" 버튼에 로딩 상태를 표시하고 중복 클릭을 방지한다.

### Requirement 8: 알람 생성 (트랙 2)

**User Story:** As a 운영자, I want to 트랙 2에서 설정한 기본 메트릭과 커스텀 메트릭 알람을 생성하고 모니터링을 활성화할 수 있기를, so that 미모니터링 리소스가 즉시 감시 대상에 포함된다.

#### Acceptance Criteria

1. WHILE 트랙 2가 선택되고 최소 1개 이상의 기본 메트릭이 활성화된 상태에서, THE ModalFooter SHALL "Create Alarm" 버튼을 활성화한다.
2. WHILE 모든 기본 메트릭이 비활성화되고 커스텀 메트릭도 없는 상태에서, THE ModalFooter SHALL "Create Alarm" 버튼을 비활성화한다.
3. WHEN 운영자가 "Create Alarm" 버튼을 클릭하면, THE CreateAlarmModal SHALL mock API를 호출하여 모니터링 활성화와 알람 생성을 동시에 요청한다.
4. WHEN mock API 호출이 성공하면, THE CreateAlarmModal SHALL 성공 Toast 메시지를 표시하고 모달을 닫는다.
5. IF mock API 호출이 실패하면, THEN THE CreateAlarmModal SHALL 실패 Toast 메시지를 표시하고 모달을 유지한다.
6. WHILE API 호출이 진행 중인 상태에서, THE ModalFooter SHALL "Create Alarm" 버튼에 로딩 상태를 표시하고 중복 클릭을 방지한다.

### Requirement 9: 빈 상태 처리

**User Story:** As a 운영자, I want to 필터 결과가 비어있을 때 적절한 안내 메시지를 확인할 수 있기를, so that 왜 리소스가 표시되지 않는지 이해할 수 있다.

#### Acceptance Criteria

1. WHILE 트랙 1이 선택된 상태에서, WHEN 선택한 어카운트에 monitoring이 true인 리소스가 없으면, THE ResourceFilterStep SHALL "모니터링 중인 리소스가 없습니다" 안내 메시지를 표시한다.
2. WHILE 트랙 2가 선택된 상태에서, WHEN 선택한 어카운트에 monitoring이 false인 리소스가 없으면, THE ResourceFilterStep SHALL "미모니터링 리소스가 없습니다" 안내 메시지를 표시한다.
3. WHEN 선택한 고객사에 어카운트가 없으면, THE ResourceFilterStep SHALL 어카운트 드롭다운에 "어카운트가 없습니다" 안내를 표시한다.
4. WHILE 리소스 타입에 AVAILABLE_CW_METRICS가 비어있는 상태에서, THE MetricConfigStep SHALL "이 리소스 타입에 사용 가능한 추가 CloudWatch 메트릭이 없습니다" 안내 메시지를 표시한다.
