$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RootDir = Split-Path -Parent $ScriptDir

python "$RootDir\scripts\verify_all.py"
exit $LASTEXITCODE
