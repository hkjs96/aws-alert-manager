"""Run project regression verification.

두 가지 모드:

- 기본(게이트) 모드: 작업 트리의 변경을 보고 *관련 있는 것만, 빠른 tier만* 돌린다.
  관련 변경이 없으면 즉시 건너뛴다. Claude Stop 훅이 매 턴 호출하므로 가볍고 빨라야
  한다. 무거운 property-based(pbt)/e2e 테스트는 제외한다.
- --full 모드: pbt/e2e 포함 전수 스위트. 수동(/test) 또는 push 전에만.

각 단계는 wall-clock timeout으로 묶여, 폭주(메모리 무한 증식 등)해도 강제 종료된다.

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

# 단계별 wall-clock 상한(초). 폭주 시 프로세스를 통째로 죽여 메모리 무한 증식을 막는다.
BACKEND_TIMEOUT = 300
FRONTEND_TIMEOUT = 300

# 단일 인스턴스 락. Stop 훅이 매 턴 호출하는데 검증이 길어지면 이전 실행이 끝나기 전에
# 새 실행이 쌓여 프로세스가 누적된다(메모리/CPU 폭주). 이미 도는 게 있으면 새 호출은
# 즉시 건너뛴다. 죽은 프로세스가 남긴 stale 락은 일정 시간 후 무시한다.
_LOCK = Path(tempfile.gettempdir()) / "aam_verify_all.lock"
_LOCK_STALE_SECONDS = 1800


def acquire_lock() -> bool:
    """다른 verify_all이 실행 중이 아니면 락을 잡고 True, 이미 실행 중이면 False."""
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
    """git 작업 트리에서 변경(스테이징/미스테이징/미추적)된 경로 목록을 POSIX 형태로 반환."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    files: list[str] = []
    for line in result.stdout.splitlines():
        path = line[3:].strip()  # 'XY <path>' — 상태 2글자 + 공백 다음이 경로
        if "->" in path:  # 이름 변경: 'old -> new'
            path = path.split("->")[-1].strip()
        if path:
            files.append(path.replace("\\", "/"))
    return files


def run_step(label: str, command: list[str], cwd: Path, timeout: int, *, report_only: bool = False) -> None:
    print(f"\n==> {label}", flush=True)
    try:
        result = subprocess.run(command, cwd=cwd, check=False, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"\nTIMEOUT: {label} exceeded {timeout}s — killed (폭주 의심)", file=sys.stderr)
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
        print("verify_all (gate): 관련 소스 변경 없음 — 건너뜀.", flush=True)
        return 0

    # Diff 감사(리포트 전용, 실패시키지 않음)
    run_step("Diff Summary (--stat)", ["git", "diff", "--stat"], ROOT, 30, report_only=True)

    if backend_changed:
        # 빠른 단위 tier만: 무거운 pbt/e2e 제외
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
    parser = argparse.ArgumentParser(description="프로젝트 회귀 검증")
    parser.add_argument(
        "--full",
        action="store_true",
        help="pbt/e2e 포함 전수 스위트 실행 (수동/push 전). 미지정 시 변경 인지 게이트 모드.",
    )
    args = parser.parse_args()

    if not acquire_lock():
        print("verify_all: 다른 검증이 이미 실행 중 — 건너뜀(중복 누적 방지).", flush=True)
        return 0

    return _run_full() if args.full else _run_gate()


if __name__ == "__main__":
    raise SystemExit(main())
