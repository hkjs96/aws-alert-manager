#!/usr/bin/env python3
"""nlb-alb-ec2-lab CFN stack deploy script.

Windows git-bash 환경에서 AWS CLI file:// + UTF-8 한글 인코딩 문제를
우회하기 위해 boto3로 직접 배포한다.

Usage:
    python3 deploy.py [parameters.json]
"""
import json
import sys
import time
from pathlib import Path

import boto3

STACK_NAME = "nlb-alb-ec2-lab"
PROFILE = "bjs"
REGION = "us-east-1"


def get_session():
    session = boto3.Session(profile_name=PROFILE, region_name=REGION)
    return session.client("cloudformation")


def load_template():
    return Path("template.yaml").read_text(encoding="utf-8")


def load_parameters(param_file: str):
    with open(param_file, encoding="utf-8") as f:
        raw = json.load(f)
    return [{"ParameterKey": p["ParameterKey"], "ParameterValue": p["ParameterValue"]} for p in raw]


def get_stack_status(cfn):
    try:
        resp = cfn.describe_stacks(StackName=STACK_NAME)
        return resp["Stacks"][0]["StackStatus"]
    except cfn.exceptions.ClientError:
        return "NOT_FOUND"


def wait_for_stack(cfn, target_status, timeout=600):
    print(f"  대기 중... (목표: {target_status})")
    start = time.time()
    while time.time() - start < timeout:
        status = get_stack_status(cfn)
        if status == target_status:
            return status
        if "FAILED" in status or "ROLLBACK_COMPLETE" == status:
            print(f"  오류: 스택 상태 = {status}")
            return status
        time.sleep(10)
    print(f"  타임아웃 ({timeout}s)")
    return get_stack_status(cfn)


def print_outputs(cfn):
    resp = cfn.describe_stacks(StackName=STACK_NAME)
    outputs = resp["Stacks"][0].get("Outputs", [])
    if outputs:
        print("\nOutputs:")
        for o in outputs:
            print(f"  {o['OutputKey']:25s} {o['OutputValue']}")


def main():
    param_file = sys.argv[1] if len(sys.argv) > 1 else "parameters.json"
    if not Path(param_file).exists():
        print(f"오류: {param_file} 파일을 찾을 수 없습니다.")
        sys.exit(1)

    cfn = get_session()
    template_body = load_template()
    parameters = load_parameters(param_file)

    status = get_stack_status(cfn)
    print(f"스택 배포 시작: {STACK_NAME} (리전: {REGION})")

    if status == "NOT_FOUND":
        print("새 스택 생성 중...")
        cfn.create_stack(
            StackName=STACK_NAME,
            TemplateBody=template_body,
            Parameters=parameters,
            Capabilities=["CAPABILITY_NAMED_IAM"],
        )
        final = wait_for_stack(cfn, "CREATE_COMPLETE")
        if final != "CREATE_COMPLETE":
            print(f"스택 생성 실패: {final}")
            sys.exit(1)
    else:
        print(f"기존 스택 업데이트 중... (현재: {status})")
        try:
            cfn.update_stack(
                StackName=STACK_NAME,
                TemplateBody=template_body,
                Parameters=parameters,
                Capabilities=["CAPABILITY_NAMED_IAM"],
            )
            final = wait_for_stack(cfn, "UPDATE_COMPLETE")
            if final != "UPDATE_COMPLETE":
                print(f"스택 업데이트 실패: {final}")
                sys.exit(1)
        except cfn.exceptions.ClientError as e:
            if "No updates" in str(e):
                print("변경 사항 없음.")
            else:
                raise

    print(f"\n스택 배포 완료: {STACK_NAME}")
    print_outputs(cfn)


if __name__ == "__main__":
    main()
