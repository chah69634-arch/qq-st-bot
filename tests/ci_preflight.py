"""Non-sensitive fresh-clone checks for the full-pytest CI job."""

from __future__ import annotations

import os
from pathlib import Path


_CREDENTIAL_ENV_NAMES = (
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "ANTHROPIC_API_KEY",
)


def _credential_presence() -> bool:
    return any(bool(os.environ.get(name, "").strip()) for name in _CREDENTIAL_ENV_NAMES)


def run_preflight() -> dict[str, bool]:
    """Return only public boolean health signals; never return their values."""
    from core.asset_registry import get_registry
    from core.data_paths import DEFAULT_CHAR_ID

    fixture_root = Path(__file__).parent / "fixtures"
    required_fixture_paths = (
        fixture_root / "public_assets.py",
        fixture_root / "characters" / "cards" / "fixture_character.json",
        fixture_root / "dream_worlds" / "_default",
    )
    registry = get_registry()
    character_ids = registry.list_all("character")
    try:
        registry.resolve(DEFAULT_CHAR_ID, "character")
    except (KeyError, ValueError, FileNotFoundError):
        default_role_resolvable = False
    else:
        default_role_resolvable = True

    return {
        "default_role_resolvable": default_role_resolvable,
        "registry_ids_present": bool(character_ids),
        "fixture_root_exists": all(path.exists() for path in required_fixture_paths),
        "credentials_present": _credential_presence(),
    }


def main() -> int:
    results = run_preflight()
    for name, value in results.items():
        print(f"{name}={'true' if value else 'false'}")
    return 0 if all(
        results[name]
        for name in ("default_role_resolvable", "registry_ids_present", "fixture_root_exists")
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
