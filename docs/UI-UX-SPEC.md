# Alarm Manager — UI/UX 통합 설계서 (UI-UX-SPEC)

이 문서는 알람 매니저 웹앱의 사용자 경험(UX) 및 인터페이스(UI) 설계에 관한 통합 결정 사항이다.

---

## 1. 설계 철학 및 범위

### 1-1. 서비스 모듈화 (IEP 준비)
- 본 앱은 단독형으로 시작하나, 향후 **IEP(Internal Engineer Platform)**의 서비스 모듈로 통합될 수 있도록 설계한다.
- 상단바의 **Service Switcher**를 통해 24x7 관제, FinOps 등 다른 서비스로의 확장을 고려한다.

### 1-2. 페이즈 구분
- **Phase 1 (현재)**: 알람 CRUD 자동화, 리소스 조회/필터링, 고객사별 기본 임계치 정의.
- **Phase 2 (향후)**: 24x7 관제 시스템 연동, 알림 라우팅 고도화, 에스컬레이션 체인 도입.

---

## 2. UI 설계 결정 사항

### 2-1. 알람 등급 (Severity) 체계
업계 표준 SEV-1~5 체계를 채택하며, 메트릭 중요도에 따라 자동 부여된다.
- **SEV-1 (Critical)**: 서비스 중단 (HealthyHostCount, StatusCheck 등)
- **SEV-3 (Medium)**: 리소스 포화 근접 (CPU, Memory, Disk 등)
- **SEV-5 (Info)**: 트래픽/용량 참고 (RequestCount 등)

### 2-2. Severity 관리 방식 (CloudWatch Tags)
- Severity 정보는 알람 재생성 없이 업데이트 가능하도록 **CloudWatch 알람 태그(Tags)**에 저장한다.
- UI에서는 1번 페이즈에서 읽기 전용 뱃지로 표시하고, 2번 페이즈에서 드롭다운 수정을 지원한다.

---

## 3. 내비게이션 및 필터링 전략

### 3-1. 글로벌 컨텍스트 필터 (GlobalFilterBar)
- 상단바에 **고객사 → 어카운트 → 서비스/프로젝트**로 이어지는 연쇄 필터를 배치한다.
- 이 필터는 앱 전체의 상태를 결정하며, 페이지 이동 시에도 유지된다.

### 3-2. 관리 메뉴 구조 (Administration)
기존의 모호한 "Settings" 메뉴를 **"Administration"**으로 개편하고 탭 구조를 유지한다.
- **Customers**: 고객사 CRUD 및 기본 정책
- **Accounts**: AWS 계정 연결 및 연결 테스트
- **Threshold Policies**: 리소스 타입별 임계치 오버라이드 관리

---

## 4. 데이터 모델: Customer → Project → Account 계층

고객사가 많은 MSP 비즈니스 모델을 지원하기 위해 3단계 계층 구조를 도입한다.

```
Customer (고객사)
  └── Project / Service (프로젝트/서비스 단위)
        ├── Production Account (환경: prod)
        ├── Staging Account (환경: staging)
        └── Development Account (환경: dev)
```

### 임계치 우선순위 (Priority)
1. **Resource-level**: 특정 리소스의 특정 메트릭 태그 (최고 우선순위)
2. **Project-level**: 프로젝트 내 모든 리소스에 적용 (준비 중)
3. **Customer-level**: 고객사 내 모든 어카운트/리소스에 적용
4. **System Default**: 엔진 하드코딩 기본값 (최저 우선순위)

---

## 5. 로드맵

- **단기**: Administration 메뉴 개편 및 글로벌 필터 UI 안정화.
- **중기**: 프로젝트(Project) 레이어 도입 및 멀티 어카운트 스케일업 지원.
- **장기**: 24x7 모니터링 서비스 추가 및 서비스 스위처 활성화.
