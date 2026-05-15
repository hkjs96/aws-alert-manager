"""pre-commit wrapper: frontend TypeScript 타입 검사 (tsc --noEmit).

Windows 에서 npx 가 .cmd 확장자를 통해 실행되므로 shutil.which 로 경로를 탐색한다.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def _npx() -> str:
    """플랫폼에 맞는 npx 실행 경로를 반환한다."""
    for name in ("npx", "npx.cmd"):
        path = shutil.which(name)
        if path:
            return path
    return "npx"


def main() -> int:
    """npx tsc --noEmit 을 frontend/ 에서 실행한다."""
    result = subprocess.run([_npx(), "tsc", "--noEmit"], cwd=FRONTEND)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
