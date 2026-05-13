# API Handler Lambda Deployment

Amplify deploys the frontend only. If `api_handler/*.py` changes, deploy the API Handler Lambda behind API Gateway separately.

## Dev Environment Defaults

| Item | Value |
| --- | --- |
| AWS profile | `tlsgks678_poc` |
| Region | `us-east-1` |
| CloudFormation stack | `aws-monitoring-engine-dev` |
| Deployment bucket | `bjs-deploy-bucket` |
| Lambda package | `api_handler.zip` |

## Fast Path: Deploy API Handler Only

Run this from the repo root:

```powershell
cd C:\Users\MZC01-TLSGKS678\Desktop\workspace\aws-alert-manager

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
chcp 65001

aws sts get-caller-identity --profile tlsgks678_poc --region us-east-1

'{"tool_input":{"file_path":"api_handler/cw_helper.py"}}' | python .claude\deploy-api-handler.py
```

The script does the following:

1. Creates a new `CodeVersion`, for example `v20260513T103000`.
2. Builds `dist/api_handler.zip`.
3. Uploads it to `s3://bjs-deploy-bucket/<CodeVersion>/api_handler.zip`.
4. Copies unchanged zip artifacts from the previous `CodeVersion` to the new one:
   - `daily_monitor.zip`
   - `remediation_handler.zip`
   - `common_layer.zip`
   - `sqs_worker.zip`
5. Runs `aws cloudformation deploy` with the new `CodeVersion`.

Verify the stack:

```powershell
aws cloudformation describe-stacks `
  --profile tlsgks678_poc `
  --region us-east-1 `
  --stack-name aws-monitoring-engine-dev `
  --query "Stacks[0].StackStatus"

aws cloudformation describe-stacks `
  --profile tlsgks678_poc `
  --region us-east-1 `
  --stack-name aws-monitoring-engine-dev `
  --query "Stacks[0].Parameters[?ParameterKey=='CodeVersion'].ParameterValue" `
  --output text
```

## Manual CloudFormation Stack Update

Use this when the helper script cannot be used. This is a complete copy-paste flow for PowerShell.

It creates a correct `api_handler.zip` layout:

```text
lambda_handler.py
api_handler/
  __init__.py
  cw_helper.py
  lambda_handler.py
  routes/
  ...
```

A new `CodeVersion` prefix is required, otherwise CloudFormation may not pick up the new Lambda code.

```powershell
cd C:\Users\MZC01-TLSGKS678\Desktop\workspace\aws-alert-manager

$PROFILE = "tlsgks678_poc"
$REGION = "us-east-1"
$BUCKET = "bjs-deploy-bucket"
$STACK = "aws-monitoring-engine-dev"
$VERSION = "v" + (Get-Date -Format "yyyyMMddTHHmmss")

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
chcp 65001

# 0. Check AWS credentials
aws sts get-caller-identity `
  --profile $PROFILE `
  --region $REGION

# 1. Build dist/api_handler.zip with the Lambda handler at zip root
Remove-Item dist\api_handler.zip -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force dist | Out-Null

@'
import os
import zipfile

os.makedirs("dist", exist_ok=True)
zip_path = "dist/api_handler.zip"

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    # Lambda Handler in template.yaml is lambda_handler.lambda_handler,
    # so lambda_handler.py must exist at the root of the zip.
    zf.write("api_handler/lambda_handler.py", "lambda_handler.py")

    # Keep the api_handler package too because lambda_handler imports api_handler.routes.*
    for root, _, files in os.walk("api_handler"):
        if "__pycache__" in root:
            continue
        for name in files:
            if name.endswith(".pyc"):
                continue
            full = os.path.join(root, name)
            zf.write(full, full.replace(os.sep, "/"))

print(zip_path)
'@ | python -

# 2. Verify zip contents before uploading
python -c "import zipfile; z=zipfile.ZipFile('dist/api_handler.zip'); names=z.namelist(); print('\n'.join(names[:40])); assert 'lambda_handler.py' in names; assert 'api_handler/cw_helper.py' in names"

# 3. Read current stack CodeVersion
$OLD_VERSION = aws cloudformation describe-stacks `
  --profile $PROFILE `
  --region $REGION `
  --stack-name $STACK `
  --query "Stacks[0].Parameters[?ParameterKey=='CodeVersion'].ParameterValue" `
  --output text

# 4. Upload the changed API Handler package to the new CodeVersion prefix
aws s3 cp dist\api_handler.zip s3://$BUCKET/$VERSION/api_handler.zip `
  --profile $PROFILE `
  --region $REGION

# 5. Copy unchanged Lambda packages/layers from the current CodeVersion to the new CodeVersion
aws s3 cp s3://$BUCKET/$OLD_VERSION/daily_monitor.zip       s3://$BUCKET/$VERSION/daily_monitor.zip       --profile $PROFILE --region $REGION
aws s3 cp s3://$BUCKET/$OLD_VERSION/remediation_handler.zip s3://$BUCKET/$VERSION/remediation_handler.zip --profile $PROFILE --region $REGION
aws s3 cp s3://$BUCKET/$OLD_VERSION/common_layer.zip        s3://$BUCKET/$VERSION/common_layer.zip        --profile $PROFILE --region $REGION
aws s3 cp s3://$BUCKET/$OLD_VERSION/sqs_worker.zip          s3://$BUCKET/$VERSION/sqs_worker.zip          --profile $PROFILE --region $REGION

# 6. Update CloudFormation stack so Lambda uses the new S3 keys
aws cloudformation deploy `
  --profile $PROFILE `
  --region $REGION `
  --stack-name $STACK `
  --template-file template.yaml `
  --parameter-overrides DeploymentBucket=$BUCKET CodeVersion=$VERSION `
  --capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM `
  --no-fail-on-empty-changeset

# 7. Confirm stack status and deployed CodeVersion
aws cloudformation describe-stacks `
  --profile $PROFILE `
  --region $REGION `
  --stack-name $STACK `
  --query "Stacks[0].{Status:StackStatus,CodeVersion:Parameters[?ParameterKey=='CodeVersion'].ParameterValue|[0]}" `
  --output table
```

The deployment is not applied unless the final `CodeVersion` equals the `$VERSION` value from this run. If it still shows the old value, the stack update did not happen.

Common failure signs:

- `SyntaxError` during the Python zip step: stop immediately. Do not upload `dist/api_handler.zip`; it may be stale from a previous run.
- `'cp949' codec can't decode ...` during `aws cloudformation deploy`: rerun after setting `$env:PYTHONUTF8`, `$env:PYTHONIOENCODING`, and `chcp 65001` as shown above.
- Final `CodeVersion` is unchanged: CloudFormation did not deploy the new Lambda package.

## Manual Direct Lambda Update

This is faster, but use it only for an emergency verification because a later CloudFormation update can revert it.

```powershell
cd C:\Users\MZC01-TLSGKS678\Desktop\workspace\aws-alert-manager

$PROFILE = "tlsgks678_poc"
$REGION = "us-east-1"
$BUCKET = "bjs-deploy-bucket"
$VERSION = "manual-" + (Get-Date -Format "yyyyMMddTHHmmss")
$FUNCTION = "aws-monitoring-engine-api-handler-dev"

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
chcp 65001

Remove-Item dist\api_handler.zip -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force dist | Out-Null

@'
import os
import zipfile

os.makedirs("dist", exist_ok=True)
zip_path = "dist/api_handler.zip"

with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
    zf.write("api_handler/lambda_handler.py", "lambda_handler.py")
    for root, _, files in os.walk("api_handler"):
        if "__pycache__" in root:
            continue
        for name in files:
            if name.endswith(".pyc"):
                continue
            full = os.path.join(root, name)
            zf.write(full, full.replace(os.sep, "/"))

print(zip_path)
'@ | python -

python -c "import zipfile; z=zipfile.ZipFile('dist/api_handler.zip'); names=z.namelist(); print('\n'.join(names[:40])); assert 'lambda_handler.py' in names; assert 'api_handler/cw_helper.py' in names"

aws s3 cp dist\api_handler.zip s3://$BUCKET/$VERSION/api_handler.zip `
  --profile $PROFILE `
  --region $REGION

aws lambda update-function-code `
  --profile $PROFILE `
  --region $REGION `
  --function-name $FUNCTION `
  --s3-bucket $BUCKET `
  --s3-key $VERSION/api_handler.zip
```

## Notes

- Do not rely on `aws lambda update-function-code` for normal operations. It can work temporarily, but the next CloudFormation update can revert the function to the S3 object referenced by the stack `CodeVersion`.
- The durable deployment path is: upload zip artifacts under a new `CodeVersion`, then update the CloudFormation stack.
- Frontend-only changes: push to GitHub and verify the Amplify build.
- Backend changes in `api_handler`, `common`, `daily_monitor`, `remediation_handler`, or `sqs_worker`: package the changed artifact under a new `CodeVersion` and update the stack.
