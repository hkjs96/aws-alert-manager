# AWS Monitoring Engine - 배포 가이드

> 콘솔(AWS Management Console)에서 수동 배포하는 절차입니다.
> SAM CLI 불필요, 순수 CloudFormation 사용.

---

## 사전 준비

- Lambda 코드 업로드용 S3 버킷 1개 (예: `my-deploy-bucket`)
- AWS 콘솔 접근 권한 (CloudFormation, Lambda, S3, IAM, SNS, EventBridge)

---

## 1단계: 코드 패키징 (로컬)

로컬에서 zip 파일 3개를 만듭니다.

### 1-1. common_layer.zip

Lambda Layer 규칙에 맞게 `python/` 디렉터리 안에 넣어야 합니다.

```
임시폴더/
└── python/
    └── common/
        ├── __init__.py
        ├── tag_resolver.py
        ├── sns_notifier.py
        └── collectors/
            ├── __init__.py
            ├── ec2.py
            ├── rds.py
            └── elb.py
```

`python/` 폴더를 기준으로 zip 압축:

```bash
# git bash / Linux / macOS
mkdir -p /tmp/layer/python
cp -r common/ /tmp/layer/python/common/
cd /tmp/layer
zip -r common_layer.zip python/ -x "**/__pycache__/*" "**/*.pyc"
```

### 1-2. daily_monitor.zip

```bash
mkdir -p /tmp/daily_monitor
cp daily_monitor/handler.py /tmp/daily_monitor/
cd /tmp/daily_monitor
zip -r daily_monitor.zip .
```

### 1-3. remediation_handler.zip

```bash
mkdir -p /tmp/remediation_handler
cp remediation_handler/handler.py /tmp/remediation_handler/
cd /tmp/remediation_handler
zip -r remediation_handler.zip .
```

---

## 2단계: S3 업로드 (콘솔)

1. AWS 콘솔 → S3 → 배포 버킷 열기
2. 폴더 생성: 버전 식별용 prefix (예: `v20260306` 또는 `latest`)
3. 해당 폴더에 3개 파일 업로드:
   - `common_layer.zip`
   - `daily_monitor.zip`
   - `remediation_handler.zip`

최종 S3 경로 예시:
```
s3://my-deploy-bucket/v20260306/common_layer.zip
s3://my-deploy-bucket/v20260306/daily_monitor.zip
s3://my-deploy-bucket/v20260306/remediation_handler.zip
```

---

## 3단계: CloudFormation 스택 생성 (콘솔)

1. AWS 콘솔 → CloudFormation → **스택 생성** → "새 리소스 사용(표준)"
2. **템플릿 지정**: "템플릿 파일 업로드" → `template.yaml` 선택
3. **스택 이름**: `aws-monitoring-engine-prod` (또는 원하는 이름)
4. **파라미터 입력**:

| 파라미터 | 값 | 설명 |
|---------|-----|------|
| `DeploymentBucket` | `my-deploy-bucket` | S3 버킷 이름 |
| `CodeVersion` | `v20260306` | S3 prefix (2단계에서 만든 폴더명) |
| `Environment` | `prod` | 배포 환경 (dev/staging/prod) |
| `DefaultCpuThreshold` | `80` | CPU 임계치 (기본값 사용 가능) |
| `DefaultMemoryThreshold` | `80` | Memory 임계치 |
| `DefaultConnectionsThreshold` | `100` | DB 연결 수 임계치 |
| `DefaultFreeMemoryGBThreshold` | `2` | 여유 메모리 임계치 (GB) |
| `DefaultFreeStorageGBThreshold` | `10` | 여유 스토리지 임계치 (GB) |
| `DefaultDiskThreshold` | `85` | 디스크 사용률 임계치 |

5. **스택 옵션**: 기본값 유지
6. **검토**:
   - ✅ "AWS CloudFormation에서 사용자 지정 이름으로 IAM 리소스를 생성할 수 있음을 승인합니다." 체크
7. **스택 생성** 클릭

---

## 4단계: 배포 확인

스택 상태가 `CREATE_COMPLETE`가 되면:

1. **출력(Outputs)** 탭에서 생성된 리소스 ARN 확인
2. Lambda 콘솔에서 두 함수가 정상 생성되었는지 확인:
   - `aws-monitoring-engine-daily-monitor-prod`
   - `aws-monitoring-engine-remediation-handler-prod`
3. SNS 콘솔에서 4개 토픽 확인 후 이메일 구독 추가

---

## 코드 업데이트 시

1. 변경된 코드로 zip 재패키징 (1단계)
2. S3에 새 버전 prefix로 업로드 (예: `v20260307`)
3. CloudFormation → 해당 스택 → **업데이트** → 기존 템플릿 사용
4. `CodeVersion` 파라미터만 새 prefix로 변경
5. 업데이트 실행

---

## SNS 구독 설정

배포 후 알림을 받으려면 SNS 토픽에 구독을 추가해야 합니다:

1. AWS 콘솔 → SNS → 토픽 선택
2. **구독 생성** → 프로토콜: 이메일 → 엔드포인트: 수신할 이메일 주소
3. 확인 이메일에서 구독 승인

| 토픽 | 용도 |
|------|------|
| `aws-monitoring-engine-alert-prod` | 임계치 초과 알림 |
| `aws-monitoring-engine-remediation-prod` | Auto-Remediation 완료 알림 |
| `aws-monitoring-engine-lifecycle-prod` | 리소스 생명주기 알림 |
| `aws-monitoring-engine-error-prod` | 오류 알림 |
