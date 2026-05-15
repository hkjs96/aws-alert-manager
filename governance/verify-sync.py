"""pre-commit: 모든 에이전트 설정의 manifest_version 동기화 검증.

Windows cp949 환경 대응 -- 이모지 없이 ASCII 출력만 사용.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _manifest_version() -> str:
    """governance/hooks-manifest.yaml 에서 manifest_version 값을 읽는다."""
    path = ROOT / "governance" / "hooks-manifest.yaml"
    content = path.read_text(encoding="utf-8")
    m = re.search(r'manifest_version:\s*["\']([^"\']+)["\']', content)
    return m.group(1) if m else ""


def _read_version_file(path: Path) -> str:
    """버전 텍스트 파일을 읽어 반환한다. 파일이 없으면 빈 문자열."""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8").strip()


def _claude_version() -> str:
    """_manifest_version 필드를 .claude/settings.json 에서 읽는다."""
    path = ROOT / ".claude" / "settings.json"
    if not path.exists():
        return ""
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("_manifest_version", "")


def _kiro_version() -> str:
    """Kiro 버전 파일을 읽는다."""
    return _read_version_file(ROOT / ".kiro" / "hooks" / "MANIFEST_VERSION")


def _gemini_version() -> str:
    """Gemini 버전 파일을 읽는다."""
    return _read_version_file(ROOT / ".gemini" / "MANIFEST_VERSION")


def _codex_version() -> str:
    """Codex 버전 파일을 읽는다."""
    return _read_version_file(ROOT / ".codex" / "MANIFEST_VERSION")


def main() -> int:
    """버전 동기화 검증 실행. 불일치 시 1 반환."""
    expected = _manifest_version()
    if not expected:
        print(
            "[hooks-sync] FAIL: governance/hooks-manifest.yaml 에서"
            " manifest_version 을 찾을 수 없습니다."
        )
        return 1

    checks: dict[str, str] = {
        ".claude/settings.json        ": _claude_version(),
        ".kiro/hooks/MANIFEST_VERSION ": _kiro_version(),
        ".gemini/MANIFEST_VERSION     ": _gemini_version(),
        ".codex/MANIFEST_VERSION      ": _codex_version(),
    }

    failed = {p: v for p, v in checks.items() if v != expected}

    if failed:
        print(
            "[hooks-sync] FAIL: manifest_version 불일치"
            " -- 아래 파일을 동기화하세요:"
        )
        for path, ver in failed.items():
            current = f'"{ver}"' if ver else "(없음)"
            print(
                f"  {path.strip():<35}"
                f"  현재={current:<20}"
                f'  필요="{expected}"'
            )
        print()
        print(
            "  [방법] governance/hooks-manifest.yaml 의 manifest_version 을 올리고\n"
            "         4개 에이전트 MANIFEST_VERSION / _manifest_version 을"
            " 동일하게 갱신한 뒤 커밋하세요."
        )
        return 1

    print(
        f"[hooks-sync] OK: 모든 에이전트 설정 동기화 확인"
        f" (version={expected})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
