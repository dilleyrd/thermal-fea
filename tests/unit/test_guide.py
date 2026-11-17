"""The user guide (task M11.4): generated pages are current and the site builds."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "build_guide.py"
MKDOCS_YML = ROOT / "mkdocs.yml"


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("build_guide", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def generator() -> ModuleType:
    return _load_generator()


@pytest.fixture(scope="module")
def pages(generator: ModuleType) -> dict[str, str]:
    return generator.render_all()


def _nav_files(text: str) -> list[str]:
    nav = text.split("\nnav:", 1)[1]
    return re.findall(r":\s+(\S+\.md)\s*$", nav, flags=re.MULTILINE)


def test_generated_pages_are_up_to_date(generator: ModuleType, pages: dict[str, str]) -> None:
    assert generator.out_of_date(pages) == [], "run scripts/build_guide.py"
    assert generator.main(["--check"]) == 0


def test_check_mode_writes_nothing(generator: ModuleType, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(generator, "GUIDE", tmp_path)
    assert generator.main(["--check"]) == 1  # nothing there yet: out of date
    assert list(tmp_path.iterdir()) == []


def test_every_correlation_is_documented(pages: dict[str, str]) -> None:
    from thermalfea.convection.correlation_info import CORRELATION_INFO
    from thermalfea.convection.correlations import CORRELATIONS

    assert set(CORRELATIONS) == set(CORRELATION_INFO)
    text = pages["correlations.md"]
    for cid, info in CORRELATION_INFO.items():
        assert f"`{cid}`" in text
        assert info.formula in text
        assert info.validity in text
    assert "task M11.1" in text  # no literature source is recorded: the page says so


def test_every_theory_heading_is_in_the_theory_page(pages: dict[str, str]) -> None:
    source = (ROOT / "docs" / "theory.md").read_text(encoding="utf-8")
    headings = re.findall(r"^#{1,6} (.+)$", source, flags=re.MULTILINE)
    assert len(headings) >= 12
    for heading in headings:
        assert heading in pages["theory.md"], heading
    # features on hold are kept, with a note
    assert pages["theory.md"].count("Not available in this version") == 2


def _plain(text: str) -> str:
    """Undo the Markdown escaping, so source and page compare character for character."""
    for char in "_*|":
        text = text.replace("\\" + char, char)
    return text.replace("&lt;", "<").replace("&gt;", ">")


def test_every_theory_formula_line_survives(pages: dict[str, str]) -> None:
    source = (ROOT / "docs" / "theory.md").read_text(encoding="utf-8")
    page = _plain(pages["theory.md"])
    for line in source.splitlines():
        stripped = _plain(line).strip().lstrip("-*0123456789. ").strip()
        if stripped and not stripped.startswith(("#", "|")):
            assert stripped in page, line


def test_every_material_is_listed(pages: dict[str, str]) -> None:
    import json

    data = ROOT / "src" / "thermalfea" / "materials" / "data"
    for name in ("solids.json", "fluids.json"):
        for item in json.loads((data / name).read_text(encoding="utf-8")):
            assert item["name"] in pages["materials.md"]


def test_every_verification_case_is_listed(pages: dict[str, str]) -> None:
    source = (ROOT / "docs" / "verification.md").read_text(encoding="utf-8")
    for case in sorted(set(re.findall(r"^\| (V-\d+[a-d]?) \|", source, flags=re.MULTILINE))):
        assert f"| {case} |" in pages["verification.md"], case
    for case in ("V-22a", "V-23", "V-24", "V-36"):
        assert case in pages["verification.md"].split("## The cases")[0]


def test_every_unit_quantity_is_listed(pages: dict[str, str]) -> None:
    from thermalfea.core.units import PRESETS

    for preset in PRESETS:
        assert preset in pages["units.md"]


def test_every_nav_file_exists() -> None:
    files = _nav_files(MKDOCS_YML.read_text(encoding="utf-8"))
    assert len(files) >= 12
    for name in files:
        assert (ROOT / "guide" / name).is_file(), name
    for tutorial in ("t4-plate", "fin-quench", "cold-plate"):
        assert f"tutorials/{tutorial}.md" in files


def test_guide_settings() -> None:
    text = MKDOCS_YML.read_text(encoding="utf-8")
    assert re.search(r"^docs_dir: guide$", text, flags=re.MULTILINE)
    assert re.search(r"^site_dir: site$", text, flags=re.MULTILINE)
    assert "site/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert 'docs = ["mkdocs"]' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_strict_build(tmp_path: Path) -> None:
    pytest.importorskip("mkdocs")
    result = subprocess.run(
        [sys.executable, "-m", "mkdocs", "build", "--strict", "-d", str(tmp_path / "site")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "site" / "index.html").is_file()
    assert (tmp_path / "site" / "theory" / "index.html").is_file()
