"""#213: the Playwright scrapers use the ``Stealth`` class from playwright-stealth
2.x. Dependency declarations must not allow the 1.x releases, which lack it."""
import re
from pathlib import Path

import pytest


def test_playwright_stealth_declarations_require_2x():
    packaging = pytest.importorskip("packaging.specifiers")
    root = Path(__file__).resolve().parents[2]
    pattern = r"""["']?playwright-stealth([<>=!~][^"',\s]*(?:\s*,\s*[<>=!~][^"',\s]*)*)"""
    for name in ("pyproject.toml", "requirements.txt", "requirements-docker.txt"):
        text = (root / name).read_text(encoding="utf-8")
        match = re.search(pattern, text)
        assert match, f"playwright-stealth not declared in {name}"
        spec = packaging.SpecifierSet(match.group(1).strip())
        assert not spec.contains("1.0.6"), f"{name} allows {spec} (includes 1.0.6)"
        assert spec.contains("2.0.3"), f"{name} excludes 2.x: {spec}"
