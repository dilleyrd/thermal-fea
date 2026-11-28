"""M11.66: the American spelling "color" (owner, 2026-11-25).

The program, the guide and the examples never say "colour". The historical records
(review files, the task list and the GUI identity plan) keep the words they quoted.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def british(paths: list[Path]) -> list[str]:
    return [
        str(p.relative_to(ROOT))
        for p in paths
        if "colour" in p.read_text(encoding="utf-8").lower()
    ]


def test_the_program_says_color() -> None:
    sources = sorted((ROOT / "src" / "thermalfea").rglob("*.py"))
    assert sources
    assert not british(sources), british(sources)


def test_the_guide_and_examples_say_color() -> None:
    pages = sorted((ROOT / "guide").rglob("*.md"))
    pages += sorted((ROOT / "examples").rglob("*.md"))
    pages += sorted((ROOT / "examples").rglob("*.py"))
    assert pages
    assert not british(pages), british(pages)
