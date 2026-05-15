# Gemini CLI Context & Governance

이 파일은 Gemini CLI 에이전트가 프로젝트를 이해하고 지침을 따르기 위한 전역 컨텍스트입니다.

## 1. 단일 진실의 원천 (SSOT)
모든 훅 정의와 규칙의 원본은 `governance/hooks-manifest.yaml`에 정의되어 있습니다. 
작업 시 해당 파일의 `manifest_version`과 `.gemini/MANIFEST_VERSION`이 일치해야 합니다.

## 2. 훅 실행 지침
Gemini는 현재 자동 훅 트리거를 지원하지 않으므로, 작업 단계별로 `.gemini/hooks-context.md`에 정의된 절차를 **수동으로** 수행해야 합니다.

## 3. 핵심 아키텍처 및 거버넌스
- **Backend:** Python 3.12, Boto3 (lru_cache 싱글턴), Pytest
- **Frontend:** Next.js (App Router), TypeScript, Vitest
- **Rule:** 모든 변경 사항은 `python scripts/verify_agent_work.py`를 통해 최종 검증되어야 합니다.
