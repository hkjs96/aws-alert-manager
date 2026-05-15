"""pre-commit wrapper: frontend vitest 단위 테스트 실행."""
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
    """npx vitest run 을 frontend/ 에서 실행한다."""
    result = subprocess.run([_npx(), "vitest", "run"], cwd=FRONTEND)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
