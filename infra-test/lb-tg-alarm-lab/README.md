# LB/TG 알람 엔진 검증용 테스트 인프라

## 프로젝트 개요

aws-alert-manager의 ALB/NLB/Target Group 메트릭 수집 및 CloudWatch 알람 자동 생성 동작을
실제 AWS 환경에서 검증하기 위한 독립형 테스트 인프라.

기존 운영 코드(`common/`, `daily_monitor/`, `template.yaml`)를 일절 수정하지 않고,
별도 CloudFormation 스택으로 배포·삭제 가능한 임시 테스트 환경을 구성한다.

### 검증 대상

| 항목 | 상태 |
|------|:----:|
| EC2 하드코딩 알람 (CPU/Memory/Disk) | ✅ 동작함 |
| ALB 하드코딩 알람 (RequestCount) | ✅ 동작함 |
| NLB 동적 알람 (ProcessedBytes, ActiveFlowCount) | ⭕/❌ 조건부 |
| NLB 하드코딩 알람 (RequestCount) | ⚠️ namespace 불일치 |
| ALB/NLB TG 알람 | ❌ 미구현 |

---

## 디렉터리 구조

```
infra-test/lb-tg-alarm-lab/
├── template.yaml           # CloudFormation 템플릿 (순수 CFN, SAM 미사용)
├── parameters.example.json # 파라미터 예시 파일
├── deploy.sh               # 배포 스크립트 (SSO profile: bjs)
├── delete.sh               # 삭제 스크립트
├── verify.md               # 검증 절차서 (AWS CLI 명령 + 예상 결과)
└── README.md               # 이 파일
```

---

## 사전 요구사항

- **AWS CLI v2** 설치 및 SSO 프로필 `bjs` 설정 완료
- **SSO 로그인**: `aws sso login --profile bjs`
- **VPC/Subnet**: 배포 대상 VPC ID, 서로 다른 AZ의 서브넷 2개 (ALB 2-AZ 요구사항)
- **KeyPair**: EC2 SSH 접속용 키페어 (ap-northeast-2 리전)
- **AMI ID**: Amazon Linux 2023 AMI ID (ap-northeast-2 리전)

---

## 배포

### 1. 파라미터 파일 준비

`parameters.example.json`을 복사하여 실제 값으로 수정한다:

```bash
cp parameters.example.json parameters.json
# parameters.json 편집: VpcId, SubnetId, SubnetId2, KeyPairName, AmiId, AllowedIpCidr
```

### 2. 스택 배포

```bash
./deploy.sh parameters.json
```

- 스택 이름: `lb-tg-alarm-lab`
- 프로필: `bjs`, 리전: `ap-northeast-2`
- 모든 리소스에 `Project=lb-tg-alarm-lab` 태그 부착

### 3. 생성되는 리소스

- EC2 인스턴스 1개 (t3.micro, HTTP 서버)
- ALB 1개 + Target Group + Listener
- NLB 1개 + Target Group + Listener
- Security Group 2개 (ALB용, EC2용)

---

## 삭제

```bash
./delete.sh
```

스택 내 모든 리소스가 완전히 삭제된다 (DeletionPolicy 미지정 = Delete 기본값).

---

## 검증 절차

배포 후 Daily Monitor Lambda를 수동 실행한 뒤, `verify.md`의 절차에 따라 검증한다.

### 간략 요약

1. **EC2 알람 확인**: `aws cloudwatch describe-alarms --alarm-name-prefix "[EC2]"` → CPU/Memory/Disk 알람 3개
2. **ALB 알람 확인**: `aws cloudwatch describe-alarms --alarm-name-prefix "[ELB]"` → RequestCount 알람
3. **NLB 동적 알람 확인**: `aws cloudwatch list-metrics --namespace AWS/NetworkELB` → 메트릭 존재 시 알람 생성
4. **TG 메트릭 확인**: `aws elbv2 describe-target-groups` → TG 존재 확인, 알람은 미생성
5. **TG 알람 미생성 확인**: `aws cloudwatch describe-alarms` → TG 디멘션 알람 없음

상세 절차, AWS CLI 명령어, 예상 결과는 [verify.md](verify.md) 참조.

---

## 현재 동작 범위 vs 미구현 범위

### 동작 가능 범위

- EC2: `_EC2_ALARMS` 하드코딩 목록(CPU/Memory/Disk) 기반 알람 자동 생성
- ALB: `_ELB_ALARMS` 하드코딩 목록(`AWS/ApplicationELB` RequestCount) 기반 알람 생성
- NLB 동적 알람: `Threshold_*` 태그 → `_parse_threshold_tags()` → `_resolve_metric_dimensions()` 경로로 조건부 생성

### 미구현 범위 (갭)

- **TG 알람 자동 생성**: `_get_alarm_defs("TG")` → 빈 리스트, `_DIMENSION_KEY_MAP`에 TG 매핑 없음, 복합 디멘션 미지원
- **NLB 전용 하드코딩 알람**: `_ELB_ALARMS`에 `AWS/NetworkELB` namespace 정의 없음

---

## 주의사항

- 이 테스트 인프라는 **비용이 발생**한다 (EC2, ALB, NLB). 검증 완료 후 반드시 `./delete.sh`로 삭제할 것
- EC2에 CWAgent가 설치되어 있지 않으므로 Memory/Disk 알람은 INSUFFICIENT_DATA 상태가 정상
- NLB 동적 알람은 실제 트래픽이 발생해야 CloudWatch에 메트릭이 기록됨 (배포 후 약 15분 대기)
