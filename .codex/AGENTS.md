# Codex/Agent Context & Governance

이 파일은 Codex 및 기타 범용 AI 에이전트가 프로젝트를 이해하기 위한 지침입니다.

## 1. 훅 준수
모든 작업은 `governance/hooks-manifest.yaml`에 정의된 훅 규칙을 따라야 합니다.

## 2. 수동 체크리스트
에이전트는 파일 수정 전후에 다음 사항을 반드시 체크하십시오:
- [ ] 시크릿 하드코딩 여부 (Secret Leak Guard)
- [ ] 백엔드 거버넌스 (§1-§4) 준수 여부
- [ ] 관련 유닛 테스트 실행 결과
