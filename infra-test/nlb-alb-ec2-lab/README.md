# NLB → ALB → EC2(2대) 트래픽 테스트 인프라

## 구조

```
Client → NLB (TCP:80) → ALB (HTTP:80) → EC2 × 2 (httpd + CW Agent)
```

- EC2 2대: Amazon Linux 2023, CW Agent (mem_used_percent, disk_used_percent)
- ALB: EC2 2대를 타겟으로 라운드로빈
- NLB: ALB를 타겟으로 (TargetType: alb)
- 모든 리소스에 `Monitoring=on` 태그

## 사전 요구사항

- AWS CLI v2 + SSO 프로필 `bjs` 로그인: `aws sso login --profile bjs`
- VPC + 퍼블릭 서브넷 2개 (서로 다른 AZ)

## 배포

```bash
cp parameters.example.json parameters.json
# parameters.json 편집

cd infra-test/nlb-alb-ec2-lab
./deploy.sh parameters.json
```

AmiId 미지정 시 SSM에서 AL2023 최신 AMI 자동 조회.
IAM Role 생성 포함 (`CAPABILITY_NAMED_IAM`).

## 트래픽 테스트

```bash
# 기본 3분 (180초)
./traffic.sh

# 커스텀 시간 (초)
./traffic.sh 60
```

NLB DNS를 스택 Output에서 자동 조회하여 1초에 1요청 전송.

## 삭제

```bash
./delete.sh
```

## 비용 참고

- EC2 t3.micro × 2, ALB, NLB — 테스트 후 반드시 삭제
- CW Agent 메트릭은 배포 후 ~2분이면 CloudWatch에 나타남
- NLB → ALB 트래픽은 배포 후 헬스체크 통과까지 ~1분 대기
