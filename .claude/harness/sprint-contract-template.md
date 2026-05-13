# Sprint 계약: {기능 이름}

이 문서는 구현 시작 전 **Generator**와 **Evaluator**가 합의하는 계약서다.

## 📝 Generator 제안 (구현 계획)

### 구현 범위 (허용 변경 파일 목록)
- [ ] 
- [ ] 

### 변경 금지 파일/영역 (Regression Prevention)
- [ ] 
- [ ] 

### 보존해야 할 기존 동작
- [ ] 

### Core Invariants 체크리스트
- [ ] 알람 메타데이터 매칭 규칙 준수
- [ ] Server Component try-catch 보호 준수
- [ ] (추가 필요 시 작성)

### 기술적 결정
- 사용 라이브러리: 
- 데이터 모델 변경 사항: 

---

## 🧐 Evaluator 검토 (검증 계획)

### 1단계: RED (의도된 실패 로그 기록)
- 명령: 
- 결과 (로그): 

### 2단계: GREEN (통과 로그 기록)
- 명령: 
- 결과 (로그): 

### 3단계: REFACTOR 및 회귀 검증 (Full Suite)
- 전체 회귀 검증 명령: `python scripts/verify_all.py`
- 결과: 

### 4단계: Evaluator Diff 감사
- [ ] `git diff --name-only` 결과가 위 허용 범위와 일치하는가?
- [ ] `git diff --stat` 결과에 불필요한 코드 변경(회귀)이 없는가?
- [ ] 계약 범위 외 변경 발견 시 즉시 FAIL 처리함.

---

## 🤝 합의
- **Generator**: 동의합니다. 계약 범위 내에서만 구현을 진행합니다.
- **Evaluator**: 계약 위반 발견 시 즉시 FAIL 판정을 내리겠습니다.
