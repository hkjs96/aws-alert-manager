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
cp daily_monitor/lambda_handler.py /tmp/daily_monitor/
cd /tmp/daily_monitor
zip -r daily_monitor.zip .
```

### 1-3. remediation_handler.zip

```bash
mkdir -p /tmp/remediation_handler
cp remediation_handler/lambda_handler.py /tmp/remediation_handler/
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

코드를 수정한 후 Lambda에 반영하는 절차입니다.

### zip 파일 구조 이해

S3에 올리는 zip은 **3개**이며 역할이 다릅니다:

| 파일 | 대상 | 내용 |
|------|------|------|
| `common_layer.zip` | Lambda Layer | `common/` 전체 (tag_resolver, sns_notifier, collectors, alarm_manager 등) |
| `daily_monitor.zip` | Daily Monitor Lambda | `daily_monitor/lambda_handler.py` |
| `remediation_handler.zip` | Remediation Handler Lambda | `remediation_handler/lambda_handler.py` |

두 Lambda 함수는 `common_layer.zip`을 **공유**합니다.
`common/` 하위 파일을 수정했다면 반드시 `common_layer.zip`도 같이 올려야 합니다.

### 업데이트 절차

**1. zip 재패키징 (로컬)**

```bash
# Windows git bash 기준 (Python zipfile 사용)
python -c "
import zipfile, os

def make_zip(zip_path, source_dir):
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(source_dir):
            for f in files:
                if f.endswith('.pyc') or '__pycache__' in root: continue
                full = os.path.join(root, f)
                zf.write(full, os.path.relpath(full, source_dir))

os.makedirs('dist', exist_ok=True)
make_zip('dist/daily_monitor.zip', 'daily_monitor')
make_zip('dist/remediation_handler.zip', 'remediation_handler')

with zipfile.ZipFile('dist/common_layer.zip', 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk('common'):
        for f in files:
            if f.endswith('.pyc') or '__pycache__' in root: continue
            full = os.path.join(root, f)
            zf.write(full, os.path.join('python', os.path.relpath(full, '.')))
"
```

**2. S3 업로드**

새 버전 prefix를 사용해서 업로드합니다 (날짜 기반 권장):

```bash
VERSION=v20260311   # 오늘 날짜로 변경

aws s3 cp dist/common_layer.zip       s3://bjs-deploy-bucket/${VERSION}/common_layer.zip
aws s3 cp dist/daily_monitor.zip      s3://bjs-deploy-bucket/${VERSION}/daily_monitor.zip
aws s3 cp dist/remediation_handler.zip s3://bjs-deploy-bucket/${VERSION}/remediation_handler.zip
```

> 같은 키(`latest/...`)로 덮어쓰기 업로드해도 CloudFormation은 변경을 감지하지 못합니다.
> 반드시 새 prefix를 사용하거나 아래 CFN 업데이트 절차를 따르세요.

**3. CloudFormation 스택 업데이트**

1. AWS 콘솔 → CloudFormation → 해당 스택 선택
2. **업데이트** → "현재 템플릿 사용" 선택
3. 파라미터에서 `CodeVersion`만 새 prefix로 변경 (예: `v20260311`)
4. 나머지 파라미터는 그대로 유지
5. IAM 변경 승인 체크 후 **업데이트 실행**
6. 스택 상태가 `UPDATE_COMPLETE`가 되면 완료

> `CodeVersion` 파라미터 변경이 핵심입니다. 이 값이 바뀌어야 CFN이 새 S3 경로에서 코드를 가져옵니다.

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

---

## AWS CLI SSO 설정 (로컬 배포 자동화용)

AWS CLI로 S3 업로드 / Lambda 업데이트를 자동화하려면 SSO 로그인이 필요합니다.

### 최초 1회: SSO 프로필 설정

```bash
aws configure sso --profile bjs
```

프롬프트 입력값:

| 항목 | 값 |
|------|-----|
| SSO session name | `bjs` |
| SSO start URL | `https://d-9b67040fbd.awsapps.com/start` |
| SSO region | `ap-northeast-2` |
| SSO registration scopes | (엔터, 기본값) |
| CLI default client Region | `ap-northeast-2` |
| CLI default output format | `json` |
| CLI profile name | `bjs` |

설정 완료 후 브라우저가 열리면 SSO 로그인 승인.

### 매번 사용 전: SSO 로그인

세션이 만료되면 다시 로그인 필요 (보통 8~12시간):

```bash
aws sso login --profile bjs
```

### 프로필 지정해서 명령어 실행

```bash
# 확인
aws sts get-caller-identity --profile bjs

# S3 업로드
aws s3 cp dist/remediation_handler.zip s3://bjs-deploy-bucket/v20260311/remediation_handler.zip --profile bjs

# Lambda 코드 업데이트 (CFN 없이 직접)
aws lambda update-function-code \
  --function-name aws-monitoring-engine-remediation-handler-dev \
  --s3-bucket bjs-deploy-bucket \
  --s3-key v20260311/remediation_handler.zip \
  --profile bjs
```

### 기본 프로필로 설정 (매번 --profile 생략하려면)

```bash
export AWS_PROFILE=bjs
```

이후 `--profile bjs` 없이 그냥 `aws s3 cp ...` 사용 가능.

### 트러블슈팅

| 에러 | 원인 | 해결 |
|------|------|------|
| `InvalidRequestException` on `StartDeviceAuthorization` | SSO region 오류 | region을 `ap-northeast-2`로 변경 |
| `Token has expired` | 세션 만료 | `aws sso login --profile bjs` 재실행 |
| `Unable to locate credentials` | 로그인 안 됨 | `aws sso login --profile bjs` 실행 |
