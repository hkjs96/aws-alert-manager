"""Run project regression verification.

Two modes:

- Gate mode (default): inspect the working tree and run only the relevant,
  fast tier. Skips immediately when nothing relevant changed. The Claude Stop
  hook calls this every turn, so it must stay light and fast. Heavy
  property-based (pbt) / e2e tests are excluded.
- --full mode: the entire suite incl. pbt/e2e. Manual (/test) or pre-push only.

Each step is bounded by a wall-clock timeout, so a runaway (e.g. unbounded
memory growth) is force-killed.

Output is intentionally ASCII/English: this runs as a hook and Windows consoles
default to cp949, which cannot encode characters like the em dash.

This script is intentionally cross-platform so Claude hooks and humans can run
the same verification flow without depending on PowerShell.
"""

from __future__ import annotations

import argparse
import atexit
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

# Per-step wall-clock cap (seconds). On a runaway, kill the whole process so
# memory cannot grow without bound.
BACKEND_TIMEOUT = 300
FRONTEND_TIMEOUT = 300

# Single-instance lock. The Stop hook calls this every turn; if verification is
# slow, a new run can start before the previous one finishes and processes pile
# up (memory/CPU blowup). If one is already running, a new call exits at once.
# A stale lock left by a dead process is ignored after a timeout.
_LOCK = Path(tempfile.gettempdir()) / "aam_verify_all.lock"
_LOCK_STALE_SECONDS = 1800


def acquire_lock() -> bool:
    """Grab the lock and return True; return False if another run holds it."""
    if _LOCK.exists() and (time.time() - _LOCK.stat().st_mtime) > _LOCK_STALE_SECONDS:
        _LOCK.unlink(missing_ok=True)
    try:
        fd = os.open(str(_LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    atexit.register(lambda: _LOCK.unlink(missing_ok=True))
    return True


def executable(name: str) -> str:
    resolved = shutil.which(name)
    if resolved:
        return resolved
    if sys.platform == "win32":
        resolved = shutil.which(f"{name}.cmd")
        if resolved:
            return resolved
    return name


def changed_files() -> list[str]:
    """Return changed (staged/unstaged/untracked) paths from git, POSIX form."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    files: list[str] = []
    for line in result.stdout.splitlines():
        path = line[3:].strip()  # 'XY <path>': 2 status chars + space, then path
        if "->" in path:  # rename: 'old -> new'
            path = path.split("->")[-1].strip()
        if path:
            files.append(path.replace("\\", "/"))
    return files


def run_step(label: str, command: list[str], cwd: Path, timeout: int, *, report_only: bool = False) -> None:
    print(f"\n==> {label}", flush=True)
    try:
        result = subprocess.run(command, cwd=cwd, check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"\nTIMEOUT: {label} exceeded {timeout}s - killed (possible runaway)", file=sys.stderr)
        raise SystemExit(1)
    if result.returncode != 0 and not report_only:
        print(f"\nFAILED: {label} exited with {result.returncode}", file=sys.stderr)
        raise SystemExit(result.returncode)


def _run_full() -> int:
    print("Running FULL regression suite (incl. pbt/e2e)...", flush=True)
    run_step(
        "Backend full (pytest)",
        [sys.executable, "-m", "pytest", "tests", "-q", "--tb=short"],
        BACKEND,
        BACKEND_TIMEOUT,
    )
    run_step(
        "Frontend type check (tsc)",
        [executable("npx"), "tsc", "--noEmit"],
        FRONTEND,
        FRONTEND_TIMEOUT,
    )
    run_step(
        "Frontend unit tests (vitest)",
        [executable("npx"), "vitest", "run"],
        FRONTEND,
        FRONTEND_TIMEOUT,
    )
    print("\nFull verification passed.", flush=True)
    return 0


def _run_gate() -> int:
    files = changed_files()
    backend_changed = any(f.startswith("backend/") and f.endswith(".py") for f in files)
    frontend_changed = any(f.startswith("frontend/") and f.endswith((".ts", ".tsx")) for f in files)

    if not backend_changed and not frontend_changed:
        print("verify_all (gate): no relevant source changes - skipping.", flush=True)
        return 0

    # Diff audit (report only, never fails the gate).
    run_step("Diff Summary (--stat)", ["git", "diff", "--stat"], ROOT, 30, report_only=True)

    if backend_changed:
        # Fast unit tier only: exclude the heavy pbt/e2e tests.
        run_step(
            "Backend unit tests (pytest -m 'not pbt and not e2e')",
            [sys.executable, "-m", "pytest", "tests", "-q", "--tb=short", "-m", "not pbt and not e2e"],
            BACKEND,
            BACKEND_TIMEOUT,
        )
    if frontend_changed:
        run_step(
            "Frontend type check (tsc)",
            [executable("npx"), "tsc", "--noEmit"],
            FRONTEND,
            FRONTEND_TIMEOUT,
        )
        run_step(
            "Frontend unit tests (vitest)",
            [executable("npx"), "vitest", "run"],
            FRONTEND,
            FRONTEND_TIMEOUT,
        )

    print("\nGate verification passed.", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Project regression verification")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run the entire suite incl. pbt/e2e (manual/pre-push). Default is change-aware gate mode.",
    )
    args = parser.parse_args()

    # Local opt-out: if .claude/verify.off exists, skip the automatic (gate)
    # verification. The Stop hook may call this every turn, but it returns here
    # immediately so no tests run (prevents the memory spike). Manual --full is
    # unaffected. Delete that file to re-enable.
    if not args.full and (ROOT / ".claude" / "verify.off").exists():
        print(
            "verify_all: gate disabled by .claude/verify.off - skipping. "
            "(full manual run: python scripts/verify_all.py --full)",
            flush=True,
        )
        return 0

    if not acquire_lock():
        print("verify_all: another verification already running - skipping (prevents pile-up).", flush=True)
        return 0

    return _run_full() if args.full else _run_gate()


if __name__ == "__main__":
    raise SystemExit(main())
