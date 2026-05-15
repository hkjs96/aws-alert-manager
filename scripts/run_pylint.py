"""pre-commit wrapper: backend Python 파일 pylint 복잡도 검사 (§3).

pre-commit 이 절대 경로로 파일을 넘기므로 backend/ 기준 상대 경로로 변환 후 실행.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"

PYLINT_FLAGS = [
    "--disable=all",
    "--enable=too-many-locals,too-many-statements,too-many-branches,too-many-arguments",
    "--max-locals=15",
    "--max-statements=50",
    "--max-branches=12",
    "--max-args=5",
]


def main() -> int:
    """변경된 .py 파일에 대해 pylint 복잡도 검사를 실행한다."""
    files: list[str] = []
    for arg in sys.argv[1:]:
        p = Path(arg).resolve()
        try:
            files.append(str(p.relative_to(BACKEND)))
        except ValueError:
            files.append(str(p))

    if not files:
        return 0

    result = subprocess.run(
        [sys.executable, "-m", "pylint", *PYLINT_FLAGS, *files],
        cwd=BACKEND,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
