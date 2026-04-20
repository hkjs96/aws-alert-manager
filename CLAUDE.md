# AWS Monitoring Engine — Claude Guide

이 파일은 Claude가 이 저장소에서 작업할 때 참고하는 프로젝트 가이드다.
기존 Kiro 스티어링(`.kiro/steering/`)은 그대로 유지하고, 그 내용을 Claude에서도 일관되게 쓸 수 있도록 본 문서로 조합한다.

> **참고**: 이 문서는 `.kiro/steering/`의 규칙을 Claude Code 워크플로에 맞게 재편한 것이다. 상세 내용은 각 소스 파일을 그대로 인용/import하므로 Kiro 사이드 수정 시 자동으로 반영된다.

---

## 프로젝트 개요

- **시스템**: EC2 / RDS / ELB 등 AWS 리소스를 태그(`Monitoring=on`) 기반으로 자동 모니터링하는 서버리스 엔진
- **구성 요소**
  - `daily_monitor/` — EventBridge Scheduler로 매일 09:00 KST에 실행되는 Lambda (메트릭 점검 → SNS 알림)
  - `remediation_handler/` — CloudTrail 이벤트 기반 무단 변경 감지 / 자동 복구 Lambda
  - `common/` — Collector, 알람 레지스트리, Tag Resolver, SNS Notifier 등 공통 모듈
  - `frontend/` — Next.js 16 + React 19 기반 관리 UI
  - `template.yaml` — 순수 CloudFormation 배포 템플릿 (SAM 미사용)
- **런타임**: Python 3.12 (Lambda), Next.js 16, CloudFormation 2010-09-09
- **배포**: [DEPLOY.md](./DEPLOY.md) 참조

---

## 항상 따르는 규칙 (Always)

Python / 인프라 / 프론트엔드 전역에서 **모든 작업**에 적용된다.

- 코딩 거버넌스: @.kiro/steering/coding-governance.md
- 안티 패턴 (절대 금지 목록): @.kiro/steering/anti-patterns.md
- 프론트엔드 아키텍처 작업 원칙 (설계 3단계 절대 규칙): @.kiro/steering/frontend-ruels.md

### 핵심 원칙 요약

1. **보안**: 하드코딩된 시크릿(AWS 키/비밀번호/토큰) 금지. 환경 변수 또는 Secrets Manager/SSM 사용.
2. **boto3 클라이언트**: `functools.lru_cache` 싱글턴만 사용. `global` 변수 / 함수 내 `boto3.client()` 금지.
3. **에러 처리**: `botocore.exceptions.ClientError`만 catch. `except Exception`은 최상위 핸들러 제외 금지.
4. **로깅**: `logger.error("메시지: %s", e)` 포맷 (f-string 로깅 금지).
5. **복잡도**: 로컬 변수 ≤ 15, statements ≤ 50, branches ≤ 12, 함수 인자 ≤ 5.
6. **중복 금지**: 동일 로직이 2곳 이상 반복되면 공통 함수로 추출.
7. **알람 매칭**: 이름 문자열 매칭 금지 — 메타데이터(Namespace/MetricName/Dimensions) 기반.
8. **풀스캔 금지**: `describe_alarms()` 전체 조회 후 필터링 금지 — `AlarmNamePrefix` 사용.
9. **TypeScript**: `any` 금지, `page.tsx`/`layout.tsx`에 `'use client'` 금지, 민감 데이터를 Client Component props로 전달 금지.
10. **CloudFormation**: 리전/계정 ID 하드코딩 금지 (Pseudo Parameters 사용), Lambda 런타임은 `Mappings`에서 단일 관리.

---

## 디렉토리별 세부 규칙

작업 중인 디렉토리에 따라 추가로 적용되는 규칙이 있다. 해당 디렉토리에 들어가면 Claude Code가 자동으로 하위 `CLAUDE.md`를 읽는다.

| 작업 대상 | 추가로 읽을 파일 |
|----------|----------------|
| `common/`, `daily_monitor/`, `remediation_handler/`, `tests/` (Python) | [`common/CLAUDE.md`](./common/CLAUDE.md) |
| `frontend/**/*.{ts,tsx,css}` (Next.js) | [`frontend/CLAUDE.md`](./frontend/CLAUDE.md) |

---

## 상황별 참조 (Manual / On-Demand)

다음 문서는 항상 로드되지는 않지만 해당 주제가 나오면 Claude가 참고한다.

- **프로젝트 아키텍처 & 알려진 이슈**
  - 전체 아키텍처: [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)
  - 알려진 이슈 (AWS 제약): [docs/KNOWN-ISSUES.md](./docs/KNOWN-ISSUES.md)
  - Backend 작동 방식: [common/HOW_DOES_THIS_WORK.md](./common/HOW_DOES_THIS_WORK.md)
  - Frontend 작동 방식: [frontend/HOW_DOES_THIS_WORK.md](./frontend/HOW_DOES_THIS_WORK.md)
- **AWS 리소스 Name 태그 네이밍 컨벤션**: @.kiro/steering/resource-naming.md
- **Phase2 알람 등급(Severity) 및 UI 설계 규칙**: @.kiro/steering/phase2-severity-rules.md

---

## 기능별 스펙 (Feature Specs)

Kiro Specs 35개는 `.kiro/specs/<feature-name>/` 아래에 `requirements.md` + `design.md` + `tasks.md` 형식으로 유지된다. Claude도 이 경로를 그대로 사용한다.

- 기능 구현/수정 전 해당 스펙 폴더의 세 문서를 먼저 읽는다.
- 새 기능 추가 시 동일 포맷(EARS: `WHEN ... THE ... SHALL ...`)으로 작성한다.
- 현재 스펙 목록: `ls .kiro/specs/`

주요 스펙 예시:

- `aws-monitoring-engine/` — 본 시스템 전체의 베이스 요구사항
- `tag-driven-alarm-engine/`, `selective-alarm-update/` — 알람 동기화 엔진
- `aurora-rds-monitoring/`, `docdb-monitoring/`, `elasticache-nat-monitoring/` — 리소스별 모니터링
- `alarm-manager-frontend/`, `alarm-manager-frontend-features/`, `create-alarm-modal/` — 프론트엔드
- `global-service-alarm-notification/` — us-east-1 글로벌 서비스 알람 (CloudFront/Route53/WAF)

---

## 배포 & 테스트 워크플로

작업 완료 후 기본 절차 (기존 `deploy-after-tests` 훅과 동일한 흐름):

```bash
# 1. 전체 테스트
pytest tests/ -x -q --tb=short

# 2. 프론트엔드 작업이 있다면
cd frontend && npx vitest --run && npx tsc --noEmit && cd ..

# 3. 통과 시 패키징 + 배포 (필요한 경우에만 사용자에게 확인 후)
#    — dist/*.zip → S3 업로드 → CloudFormation update-stack
```

테스트 실패 시 배포를 중단하고 실패 원인을 먼저 보고한다.

---

## Kiro → Claude 매핑 개요

기존 Kiro 자산과 Claude 측 대응 위치는 다음과 같다.

| Kiro | Claude | 비고 |
|------|--------|------|
| `.kiro/steering/*.md` (`inclusion: always`) | `CLAUDE.md` (본 파일)에서 `@import` | anti-patterns, coding-governance, frontend-ruels |
| `.kiro/steering/*.md` (`inclusion: fileMatch **/*.py`) | `common/CLAUDE.md`에서 `@import` | alarm-rules, resource-checklist |
| `.kiro/steering/*.md` (`inclusion: fileMatch frontend/**`) | `frontend/CLAUDE.md`에서 `@import` | nextjs-rules, tdd-rules |
| `.kiro/steering/*.md` (`inclusion: manual`) | 본 파일의 "상황별 참조" 섹션 | architecture, resource-naming, phase2-severity-rules |
| `.kiro/specs/*/{requirements,design,tasks}.md` | 그대로 사용 | 경로만 동일 |
| `.kiro/hooks/*` | `.claude/settings.json` | 이식 가능한 것만 PostToolUse 등으로 포팅 |
