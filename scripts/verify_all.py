"""Run the full project regression suite and audit diffs.

This script is intentionally cross-platform so Claude hooks and humans can run
the same verification flow without depending on PowerShell.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def executable(name: str) -> str:
    resolved = shutil.which(name)
    if resolved:
        return resolved
    if sys.platform == "win32":
        resolved = shutil.which(f"{name}.cmd")
        if resolved:
            return resolved
    return name


def run_step(label: str, command: list[str], cwd: Path, report_only: bool = False) -> None:
    print(f"\n==> {label}", flush=True)
    result = subprocess.run(command, cwd=cwd, check=False)
    if result.returncode != 0 and not report_only:
        print(f"\nFAILED: {label} exited with {result.returncode}", file=sys.stderr)
        raise SystemExit(result.returncode)


def main() -> int:
    print("Starting full project regression verification...", flush=True)

    # 1. Diff Audit (Report only, do not fail)
    print("\n--- Regression Prevention: Diff Audit ---", flush=True)
    run_step("Changed Files (--name-only)", ["git", "diff", "--name-only"], ROOT, report_only=True)
    run_step("Diff Summary (--stat)", ["git", "diff", "--stat"], ROOT, report_only=True)
    print("------------------------------------------", flush=True)

    # 2. Test Suites (Must pass)
    run_step(
        "Backend tests (pytest)",
        [sys.executable, "-m", "pytest", "tests", "-x", "-q", "--tb=short"],
        BACKEND,
    )
    run_step(
        "Frontend type check (tsc)",
        [executable("npx"), "tsc", "--noEmit"],
        FRONTEND,
    )
    run_step(
        "Frontend unit tests (vitest)",
        [executable("npx"), "vitest", "run"],
        FRONTEND,
    )

    print("\nAll verification steps passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
