# 구현 계획: LB/TG 알람 테스트 인프라

## 개요

ALB/NLB/Target Group 알람 엔진 동작을 실제 AWS 환경에서 검증하기 위한 독립형 CloudFormation 테스트 스택과 PBT 테스트를 구현한다. 모든 파일은 `infra-test/lb-tg-alarm-lab/` 디렉터리에 생성하며, 기존 운영 코드는 일절 수정하지 않는다.

## Tasks

- [x] 1. CloudFormation 템플릿 작성
  - [x] 1.1 `infra-test/lb-tg-alarm-lab/template.yaml` 생성 — Parameters 섹션
    - `AWSTemplateFormatVersion: '2010-09-09'` 순수 CFN
    - Parameters: `VpcId` (AWS::EC2::VPC::Id), `SubnetId` (AWS::EC2::Subnet::Id), `SubnetId2` (AWS::EC2::Subnet::Id), `KeyPairName` (AWS::EC2::KeyPair::KeyName), `AmiId` (AWS::EC2::Image::Id), `AllowedIpCidr` (String)
    - 모든 파라미터는 필수 (기본값 없음), Description 포함
    - _Requirements: 2.1, 2.2, 2.5_

  - [x] 1.2 Security Group 리소스 추가
    - `AlbSecurityGroup`: HTTP:80 인바운드 from `AllowedIpCidr`, 아웃바운드 all `0.0.0.0/0`
    - `Ec2SecurityGroup`: HTTP:80 인바운드 from `AlbSecurityGroup` + `AllowedIpCidr` (NLB pass-through), SSH:22 from `AllowedIpCidr`, 아웃바운드 all `0.0.0.0/0`
    - 공통 태그: `Monitoring=on`, `Project=lb-tg-alarm-lab`, `Environment=test`
    - DeletionPolicy 미지정 (기본 Delete)
    - _Requirements: 6.1, 6.2, 6.3, 1.4, 2.4, 9.2_

  - [x] 1.3 EC2 인스턴스 리소스 추가
    - `TestEc2Instance`: t3.micro, `AmiId` 파라미터 사용, `KeyPairName` 사용
    - UserData: `#!/bin/bash\nyum update -y\npython3 -m http.server 80 &`
    - 태그: `Monitoring=on`, `Project=lb-tg-alarm-lab`, `Environment=test`, `Name=lb-tg-alarm-lab-ec2`, `Threshold_CPU=70`
    - `Ec2SecurityGroup` 연결
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 9.3_

  - [x] 1.4 ALB 경로 리소스 추가
    - `TestAlb`: Application Load Balancer, Subnets: [SubnetId, SubnetId2], AlbSecurityGroup 연결
    - 태그: `Monitoring=on`, `Project=lb-tg-alarm-lab`, `Environment=test`, `Name=lb-tg-alarm-lab-alb`, `Threshold_RequestCount=5000`
    - `TestAlbTargetGroup`: HTTP/80, HealthCheck path `/`, VpcId 참조
    - TG 태그: `Monitoring=on`, `Project=lb-tg-alarm-lab`, `Environment=test`, `Name=lb-tg-alarm-lab-alb-tg`, `Threshold_RequestCount=3000`
    - `TestAlbListener`: HTTP:80, DefaultAction forward to TestAlbTargetGroup
    - Targets에 TestEc2Instance 등록
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 9.4_

  - [x] 1.5 NLB 경로 리소스 추가
    - `TestNlb`: Network Load Balancer, Subnets: [SubnetId, SubnetId2]
    - 태그: `Monitoring=on`, `Project=lb-tg-alarm-lab`, `Environment=test`, `Name=lb-tg-alarm-lab-nlb`, `Threshold_ProcessedBytes=1000000`, `Threshold_ActiveFlowCount=100`
    - `TestNlbTargetGroup`: TCP/80, TCP HealthCheck, VpcId 참조
    - TG 태그: `Monitoring=on`, `Project=lb-tg-alarm-lab`, `Environment=test`, `Name=lb-tg-alarm-lab-nlb-tg`, `Threshold_HealthyHostCount=1`
    - `TestNlbListener`: TCP:80, DefaultAction forward to TestNlbTargetGroup
    - Targets에 TestEc2Instance 등록
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 9.5, 9.6_

  - [x] 1.6 Outputs 섹션 추가
    - EC2 InstanceId, ALB ARN, NLB ARN, ALB TG ARN, NLB TG ARN, ALB DNS Name
    - 검증 시 리소스 식별에 사용
    - _Requirements: 1.2, 8.1_

- [x] 2. 체크포인트 — 템플릿 구조 확인
  - 전체 테스트 실행하여 기존 테스트 회귀 없음 확인
  - 질문이 있으면 사용자에게 확인

- [x] 3. 지원 파일 작성
  - [x] 3.1 `infra-test/lb-tg-alarm-lab/parameters.example.json` 생성
    - 6개 파라미터의 예시 값 포함 (placeholder)
    - JSON 배열 형식 (`ParameterKey`/`ParameterValue`)
    - _Requirements: 2.3_

  - [x] 3.2 `infra-test/lb-tg-alarm-lab/deploy.sh` 생성
    - `set -euo pipefail`
    - 파라미터 파일 경로를 인자로 받음 (`$1`)
    - `aws cloudformation deploy --profile bjs --region ap-northeast-2 --stack-name lb-tg-alarm-lab --template-file template.yaml --parameter-overrides file://$1`
    - 실패 시 에러 메시지 + exit 1
    - SSO 세션 만료 안내 메시지
    - _Requirements: 7.1, 7.2, 7.5, 1.5_

  - [x] 3.3 `infra-test/lb-tg-alarm-lab/delete.sh` 생성
    - `set -euo pipefail`
    - `aws cloudformation delete-stack --profile bjs --region ap-northeast-2 --stack-name lb-tg-alarm-lab`
    - `aws cloudformation wait stack-delete-complete --profile bjs --region ap-northeast-2 --stack-name lb-tg-alarm-lab`
    - 실패 시 에러 메시지 + exit 1
    - _Requirements: 7.3, 7.4, 7.5_

- [x] 4. 문서 작성
  - [x] 4.1 `infra-test/lb-tg-alarm-lab/verify.md` 생성
    - 5개 검증 시나리오: (a) EC2 기본 알람, (b) ALB LB 레벨 알람, (c) NLB 동적 메트릭 알람, (d) TG 메트릭 존재/디멘션 확인, (e) TG 알람 미지원 확인
    - 각 시나리오별 AWS CLI 명령어, 예상 결과 ("현재 동작함" / "미구현(갭)")
    - 리소스별 태그 설계 테이블
    - 예상 알람 결과 테이블 (리소스, 타입, 메트릭, 생성 여부, 알람 유형, 사유)
    - TG 알람 미지원 사유 코드 레벨 설명
    - NLB 하드코딩 알람 부재 사유 설명
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 9.1, 10.1, 10.2, 10.3, 10.4, 10.5, 10.6_

  - [x] 4.2 `infra-test/lb-tg-alarm-lab/README.md` 생성
    - 프로젝트 개요, 디렉터리 구조, 사전 요구사항
    - 배포/삭제 명령어, 검증 절차 요약
    - 한국어 작성
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5_

- [x] 5. PBT 테스트 작성
  - [x] 5.1 `tests/test_pbt_cfn_template_tags.py` 생성 — 공통 태그 완전성 테스트
    - **Property 1: 공통 태그 완전성**
    - **Validates: Requirements 1.4, 9.2**
    - 템플릿 YAML 파싱 후 모든 taggable 리소스에 `Monitoring=on`, `Project=lb-tg-alarm-lab`, `Environment=test` 태그 존재 확인
    - `# Feature: lb-tg-alarm-test-infra, Property 1: 공통 태그 완전성` 주석 포함
    - hypothesis + pytest.mark.parametrize 사용

  - [ ]* 5.2 DeletionPolicy 안전성 테스트 추가
    - **Property 2: DeletionPolicy 안전성**
    - **Validates: Requirements 2.4**
    - 모든 리소스의 DeletionPolicy가 absent 또는 Delete인지 확인

  - [ ]* 5.3 Security Group 아웃바운드 개방 테스트 추가
    - **Property 3: Security Group 아웃바운드 개방**
    - **Validates: Requirements 6.3**
    - 모든 SG 리소스의 SecurityGroupEgress에 `0.0.0.0/0` 전체 아웃바운드 규칙 존재 확인

  - [ ]* 5.4 단위 테스트 추가 — 템플릿 구조 검증
    - 파라미터 6개 존재 확인 (VpcId, SubnetId, SubnetId2, KeyPairName, AmiId, AllowedIpCidr)
    - EC2 인스턴스 타입 t3.micro 확인
    - EC2 UserData에 http.server 포함 확인
    - ALB/NLB 리소스 타입 및 Scheme 확인
    - TG 프로토콜/포트/헬스체크 설정 확인
    - Listener 포트 및 DefaultActions 확인
    - _Requirements: 2.1, 2.2, 3.2, 3.3, 4.1, 4.5, 5.1, 5.6_

- [x] 6. 최종 체크포인트 — 전체 테스트 통과 확인
  - 전체 테스트 스위트 실행: `pytest tests/ -v`
  - 모든 PBT 테스트 PASS 확인
  - 기존 테스트 회귀 없음 확인
  - 질문이 있으면 사용자에게 확인

## Notes

- `*` 표시된 태스크는 선택 사항이며 빠른 MVP를 위해 건너뛸 수 있음
- 각 태스크는 특정 요구사항을 참조하여 추적 가능
- 체크포인트에서 점진적 검증 수행
- 기존 운영 코드(`common/`, `daily_monitor/`, `template.yaml`)는 일절 수정하지 않음
- 속성 테스트는 템플릿 YAML 파싱 기반으로 정합성 속성을 검증
