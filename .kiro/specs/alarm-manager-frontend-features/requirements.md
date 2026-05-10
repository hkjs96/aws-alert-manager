# Requirements Document

## Introduction

현재 Alarm Manager 프론트엔드는 5개 페이지(Dashboard, Resources, Resource Detail, Alarms, Settings)의 UI 레이아웃이 mock 데이터 기반으로 구현되어 있다. 이 요구사항 문서는 Stitch 디자인 문서(`stitch-prompt-alarm-webapp.md`, `stitch-prompt-mvp-v2.md`)에 정의된 전체 기능 범위와 현재 구현을 비교하여, 아직 구현되지 않은 세부 기능들을 체계적으로 정리한다.

주요 갭 영역: 백엔드 API 연동(현재 모두 mock), 서버사이드 페이지네이션, 글로벌 필터 연동, 벌크 액션 API 호출, 리소스 동기화, 고객사/어카운트 CRUD, 임계치 오버라이드, 에러 핸들링/로딩 상태, 토스트 알림.

## Glossary

- **API_Client**: 백엔드 REST API와 통신하는 프론트엔드 HTTP 클라이언트 모듈
- **Resource_List_Page**: Resources Inventory 페이지 (`/resources`)
- **Resource_Detail_Page**: 개별 리소스 상세 페이지 (`/resources/[id]`)
- **Dashboard_Page**: 시스템 개요 대시보드 페이지 (`/dashboard`)
- **Alarms_Page**: 알람 목록 페이지 (`/alarms`)
- **Settings_Page**: 시스템 설정 페이지 (`/settings`)
- **Global_Filter**: TopBar에 위치한 Customer/Account/Service 캐스케이딩 필터
- **Toast_System**: 사용자 액션 결과를 알려주는 토스트 알림 시스템
- **Bulk_Action**: 여러 리소스를 선택하여 일괄 처리하는 기능
- **Threshold_Override**: System → Customer → Account → Resource Tag 우선순위의 임계치 오버라이드 체계
- **Sync_Operation**: 백엔드에 리소스 동기화를 요청하는 작업

## Requirements

### Requirement 1: API 클라이언트 기반 구조

**User Story:** As an MSP engineer, I want the frontend to fetch real data from the backend API, so that I can manage actual AWS resources instead of mock data.

#### Acceptance Criteria

1. THE API_Client SHALL provide typed request functions for all backend endpoints (resources, alarms, customers, accounts, alarm-configs)
2. WHEN the API_Client receives an HTTP error response (4xx, 5xx), THE API_Client SHALL return a structured error object containing status code, error message, and request context
3. THE API_Client SHALL include the selected Global_Filter values (customer_id, account_id) as query parameters in every API request
4. WHEN a request is in progress, THE API_Client SHALL expose a loading state that consuming components can use to display loading indicators
5. THE API_Client SHALL use a base URL configurable via environment variable (`NEXT_PUBLIC_API_BASE_URL`)

### Requirement 2: 글로벌 필터 연동

**User Story:** As an MSP engineer, I want to filter all pages by Customer, Account, and Service, so that I can focus on a specific customer's environment.

#### Acceptance Criteria

1. THE Global_Filter SHALL render three cascading dropdowns (Customer, Account, Service) in the TopBar
2. WHEN the user selects a Customer, THE Global_Filter SHALL fetch and display only the Accounts belonging to that Customer in the Account dropdown
3. WHEN the user changes any Global_Filter value, THE Global_Filter SHALL persist the selection across page navigation using URL query parameters or global state
4. WHEN the Global_Filter selection changes, THE Dashboard_Page, Resource_List_Page, Alarms_Page SHALL re-fetch data filtered by the selected Customer and Account
5. THE Global_Filter SHALL load Customer and Account options from the backend API on initial render

### Requirement 3: Dashboard 백엔드 연동

**User Story:** As an MSP engineer, I want the dashboard to show real-time statistics from the backend, so that I can monitor the actual health of managed infrastructure.

#### Acceptance Criteria

1. WHEN the Dashboard_Page loads, THE Dashboard_Page SHALL fetch statistics (monitored_count, active_alarms, unmonitored_count, account_count) from the backend API
2. WHEN the Dashboard_Page loads, THE Dashboard_Page SHALL fetch the recent alarm triggers list from the backend API with pagination support
3. WHILE the Dashboard_Page is fetching data, THE Dashboard_Page SHALL display skeleton loading placeholders for stat cards and the alarm table
4. IF the Dashboard_Page API request fails, THEN THE Dashboard_Page SHALL display an error message with a retry button
5. WHEN the user clicks the "Refresh Metrics" button, THE Dashboard_Page SHALL re-fetch all statistics and recent alarms from the backend API

### Requirement 4: Resources 목록 백엔드 연동 및 서버사이드 페이지네이션

**User Story:** As an MSP engineer, I want to browse resources with server-side pagination and filtering, so that I can efficiently navigate large resource inventories.

#### Acceptance Criteria

1. WHEN the Resource_List_Page loads, THE Resource_List_Page SHALL fetch resources from the backend API instead of using mock data
2. THE Resource_List_Page SHALL implement server-side pagination with configurable page size (25, 50, 100) and display current page, total count, and page navigation controls
3. WHEN the user changes a filter (Customer, Account, Resource Type, search text), THE Resource_List_Page SHALL send the filter parameters to the backend API and display the filtered results
4. WHEN the user clicks a column header, THE Resource_List_Page SHALL send the sort parameter to the backend API and display the sorted results
5. WHILE the Resource_List_Page is fetching data, THE Resource_List_Page SHALL display a loading state in the table body without removing the table header
6. IF the Resource_List_Page API request fails, THEN THE Resource_List_Page SHALL display an inline error message with a retry button

### Requirement 5: 리소스 동기화 API 연동

**User Story:** As an MSP engineer, I want to trigger resource synchronization from the UI, so that I can ensure the resource inventory is up-to-date with AWS.

#### Acceptance Criteria

1. WHEN the user clicks the "Sync Resources" button on the Resource_List_Page, THE Resource_List_Page SHALL send a sync request to the backend API
2. WHILE the sync operation is in progress, THE Resource_List_Page SHALL display a spinning indicator on the "Sync Resources" button and disable the button
3. WHEN the sync operation completes successfully, THE Toast_System SHALL display a success message with the sync summary (resources discovered, updated, removed)
4. IF the sync operation fails, THEN THE Toast_System SHALL display an error message with the failure reason
5. WHEN the sync operation completes, THE Resource_List_Page SHALL automatically re-fetch the resource list to reflect updated data

### Requirement 6: 벌크 모니터링 활성화/비활성화 API 연동

**User Story:** As an MSP engineer, I want to enable or disable monitoring for multiple resources at once via the backend, so that alarm configurations are actually created or removed in CloudWatch.

#### Acceptance Criteria

1. WHEN the user clicks "활성화" in the Enable modal with metric configurations, THE Resource_List_Page SHALL send a bulk enable request to the backend API containing the selected resource IDs and metric threshold configurations
2. WHEN the user clicks "비활성화" in the Disable modal, THE Resource_List_Page SHALL send a bulk disable request to the backend API containing the selected resource IDs
3. WHILE the bulk operation is in progress, THE Resource_List_Page SHALL display a progress indicator in the modal and disable the submit button
4. WHEN the bulk operation completes successfully, THE Toast_System SHALL display a success message with the count of resources processed
5. IF the bulk operation partially fails, THEN THE Toast_System SHALL display a warning message listing the resource IDs that failed
6. WHEN the bulk operation completes, THE Resource_List_Page SHALL clear the selection and re-fetch the resource list

### Requirement 7: Resource Detail 백엔드 연동

**User Story:** As an MSP engineer, I want the resource detail page to show real alarm configurations and current metric values from the backend, so that I can manage alarms for a specific resource.

#### Acceptance Criteria

1. WHEN the Resource_Detail_Page loads, THE Resource_Detail_Page SHALL fetch the resource metadata (ID, name, type, account, region, monitoring status) from the backend API
2. WHEN the Resource_Detail_Page loads, THE Resource_Detail_Page SHALL fetch the alarm configuration list (metric, threshold, unit, direction, severity, state, current_value, source) from the backend API
3. WHEN the Resource_Detail_Page loads, THE Resource_Detail_Page SHALL fetch the recent events for the resource from the backend API
4. WHILE the Resource_Detail_Page is fetching data, THE Resource_Detail_Page SHALL display skeleton loading placeholders for the header, alarm table, and events section
5. IF the Resource_Detail_Page API request fails, THEN THE Resource_Detail_Page SHALL display an error message with a retry button
6. THE Resource_Detail_Page SHALL display the Severity badge (SEV-1 through SEV-5) as a read-only outline badge for each alarm row
7. THE Resource_Detail_Page SHALL display the Source badge (System, Customer, Custom) for each alarm row indicating the threshold origin

### Requirement 8: 알람 설정 저장 API 연동

**User Story:** As an MSP engineer, I want to save alarm configuration changes on the resource detail page to the backend, so that threshold modifications are applied to actual CloudWatch alarms.

#### Acceptance Criteria

1. WHEN the user modifies a threshold value or toggles a metric monitor on the Resource_Detail_Page, THE Resource_Detail_Page SHALL track the change as an unsaved modification and display an unsaved changes indicator
2. WHEN the user clicks "Save Changes", THE Resource_Detail_Page SHALL send the modified alarm configurations to the backend API
3. WHILE the save operation is in progress, THE Resource_Detail_Page SHALL disable the "Save Changes" button and display a saving indicator
4. WHEN the save operation completes successfully, THE Toast_System SHALL display a success message and THE Resource_Detail_Page SHALL clear the unsaved changes indicator
5. IF the save operation fails, THEN THE Toast_System SHALL display an error message and THE Resource_Detail_Page SHALL retain the unsaved changes
6. WHEN the user clicks "Reset to Defaults", THE Resource_Detail_Page SHALL revert all threshold values to the system default values without sending an API request
7. WHEN the user toggles the Monitoring Status switch, THE Resource_Detail_Page SHALL send an enable or disable monitoring request to the backend API for that resource

### Requirement 9: 커스텀 메트릭 추가 API 연동

**User Story:** As an MSP engineer, I want to add custom CloudWatch metrics to a resource's alarm configuration, so that I can monitor non-standard metrics.

#### Acceptance Criteria

1. WHEN the user clicks "Add Custom Metric" on the Resource_Detail_Page, THE Resource_Detail_Page SHALL fetch available CloudWatch metrics for the resource from the backend API (list_metrics)
2. THE Resource_Detail_Page SHALL display the available metrics in an autocomplete dropdown showing "MetricName (Namespace)" format
3. WHEN the user selects a metric and submits the custom metric form, THE Resource_Detail_Page SHALL add the metric to the alarm configuration table as an unsaved change
4. WHEN a selected custom metric exists in CloudWatch, THE Resource_Detail_Page SHALL display a green validation indicator ("Metric found")
5. WHEN a selected custom metric does not exist in CloudWatch, THE Resource_Detail_Page SHALL display an amber warning ("Metric not found in CloudWatch. Alarm will be INSUFFICIENT_DATA.")

### Requirement 10: Alarms 페이지 백엔드 연동

**User Story:** As an MSP engineer, I want the alarms page to show real alarm data from the backend with filtering and pagination, so that I can monitor all alarm states across accounts.

#### Acceptance Criteria

1. WHEN the Alarms_Page loads, THE Alarms_Page SHALL fetch alarms from the backend API instead of using mock data
2. THE Alarms_Page SHALL implement server-side pagination with page navigation controls and total count display
3. WHEN the user selects a state filter (ALL, ALARM, INSUFFICIENT, OK, OFF), THE Alarms_Page SHALL send the filter to the backend API and display filtered results
4. WHEN the user enters a search term, THE Alarms_Page SHALL send the search query to the backend API and display matching results
5. WHILE the Alarms_Page is fetching data, THE Alarms_Page SHALL display a loading state in the table body
6. THE Alarms_Page SHALL display summary cards (Total, ALARM count, OK count, INSUFFICIENT count) fetched from the backend API

### Requirement 11: 고객사 CRUD API 연동

**User Story:** As an MSP engineer, I want to create, read, update, and delete customers through the UI, so that I can manage customer organizations in the system.

#### Acceptance Criteria

1. WHEN the Settings_Page loads, THE Settings_Page SHALL fetch the customer list from the backend API instead of using hardcoded data
2. WHEN the user submits the "Register Customer" form with a display name and entity code, THE Settings_Page SHALL send a create customer request to the backend API
3. WHEN the customer creation succeeds, THE Toast_System SHALL display a success message and THE Settings_Page SHALL re-fetch the customer list
4. IF the customer creation fails (duplicate code, validation error), THEN THE Settings_Page SHALL display the error message inline below the form
5. WHEN the user clicks a delete action on a customer row, THE Settings_Page SHALL display a confirmation dialog before sending a delete request to the backend API

### Requirement 12: 어카운트 CRUD API 연동

**User Story:** As an MSP engineer, I want to register, test, and manage AWS accounts through the UI, so that I can onboard new accounts for monitoring.

#### Acceptance Criteria

1. WHEN the Settings_Page loads, THE Settings_Page SHALL fetch the account list from the backend API instead of using hardcoded data
2. WHEN the user submits the "Connect Account" form, THE Settings_Page SHALL send a create account request to the backend API with account_id, role_arn, name, and customer_id
3. WHEN the account creation succeeds, THE Toast_System SHALL display a success message and THE Settings_Page SHALL re-fetch the account list
4. IF the account creation fails (invalid ARN, duplicate account), THEN THE Settings_Page SHALL display the error message inline below the form
5. WHEN the user clicks "Test Connection" on an account row, THE Settings_Page SHALL send a connection test request to the backend API and display the result (connected/failed) in the status column
6. WHILE the connection test is in progress, THE Settings_Page SHALL display a spinning indicator on the "Test Connection" button

### Requirement 13: 임계치 오버라이드 관리

**User Story:** As an MSP engineer, I want to view and manage threshold overrides at the customer level, so that I can customize alarm thresholds per customer organization.

#### Acceptance Criteria

1. THE Settings_Page SHALL display a "Default Thresholds" section with horizontal scrollable resource type tabs covering all 30 resource types
2. WHEN the user selects a resource type tab, THE Settings_Page SHALL fetch and display the metric threshold table for that type from the backend API, showing system default values and customer override values
3. WHEN the user modifies a customer override value and saves, THE Settings_Page SHALL send the updated threshold to the backend API
4. THE Settings_Page SHALL display the threshold hierarchy (System → Customer) with visual indicators showing which level is active for each metric
5. WHEN the threshold save operation succeeds, THE Toast_System SHALL display a success message

### Requirement 14: 토스트 알림 시스템

**User Story:** As an MSP engineer, I want to see toast notifications for operation results, so that I can confirm whether my actions succeeded or failed.

#### Acceptance Criteria

1. THE Toast_System SHALL render toast notifications in a fixed position (top-right corner) that stack vertically when multiple toasts are active
2. THE Toast_System SHALL support four toast variants: success (green), error (red), warning (amber), info (blue)
3. WHEN a toast is displayed, THE Toast_System SHALL auto-dismiss the toast after 5 seconds
4. THE Toast_System SHALL allow the user to manually dismiss a toast by clicking a close button
5. THE Toast_System SHALL provide a global function or context that any component can call to trigger a toast notification

### Requirement 15: 에러 핸들링 및 로딩 상태 공통 패턴

**User Story:** As an MSP engineer, I want consistent loading and error states across all pages, so that I can understand the system status at a glance.

#### Acceptance Criteria

1. WHILE any page is loading data, THE page SHALL display skeleton placeholders that match the layout of the expected content
2. IF an API request fails, THEN THE page SHALL display an inline error component with the error message and a "Retry" button
3. WHEN the user clicks the "Retry" button, THE page SHALL re-send the failed API request
4. WHILE a mutation operation (create, update, delete) is in progress, THE page SHALL disable the submit button and display a loading spinner inside the button
5. IF a network connection error occurs, THEN THE Toast_System SHALL display a persistent error toast with the message "네트워크 연결을 확인해주세요"

### Requirement 16: 모니터링 토글 API 연동

**User Story:** As an MSP engineer, I want the monitoring toggle on the resource table to actually enable or disable monitoring via the backend, so that toggling has a real effect.

#### Acceptance Criteria

1. WHEN the user clicks the monitoring toggle on a resource row in the Resource_List_Page, THE Resource_List_Page SHALL send an enable or disable monitoring request to the backend API for that resource
2. WHILE the toggle API request is in progress, THE Resource_List_Page SHALL display the toggle in a loading state (disabled with spinner)
3. WHEN the toggle operation succeeds, THE Resource_List_Page SHALL update the toggle state to reflect the new monitoring status
4. IF the toggle operation fails, THEN THE Resource_List_Page SHALL revert the toggle to the previous state and THE Toast_System SHALL display an error message

### Requirement 17: Export CSV 기능

**User Story:** As an MSP engineer, I want to export resource and alarm data as CSV files, so that I can share reports with stakeholders.

#### Acceptance Criteria

1. WHEN the user clicks "Export CSV" on the Resource_List_Page, THE Resource_List_Page SHALL request a CSV export from the backend API with the current filter parameters applied
2. WHEN the user clicks "Export Report" on the Alarms_Page, THE Alarms_Page SHALL request a CSV export from the backend API with the current filter and state parameters applied
3. WHEN the CSV export is ready, THE page SHALL trigger a browser file download with a filename containing the export type and date (e.g., "resources_2024-01-15.csv")
4. WHILE the export is being generated, THE page SHALL display a loading indicator on the export button
