"""pre-commit wrapper: backend pytest 실행.

backend/ 를 cwd 로 설정하여 conftest.py 및 내부 import 가 정상 동작하도록 한다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def main() -> int:
    """backend/tests/ 전체를 -x (첫 실패에서 중단) 로 실행한다."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-x", "-q", "--tb=short"],
        cwd=BACKEND,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
