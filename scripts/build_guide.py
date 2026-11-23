"""Generate the reference pages of the user guide (``guide/``) from the project's sources.

Run ``.venv/Scripts/python.exe scripts/build_guide.py`` to rewrite the generated pages, or
with ``--check`` to write nothing and exit non-zero when a generated page is out of date.

The generated pages are:

* ``theory.md``        from ``docs/theory.md``
* ``correlations.md``  from ``thermalfea.convection.correlation_info`` and the theory text
* ``materials.md``     from ``src/thermalfea/materials/data/*.json``
* ``verification.md``  from ``docs/verification.md``
* ``units.md``         from ``thermalfea.core.units``

Nothing technical is typed in here: every formula, range and number is read from those
sources. The pages are checked in, because they are part of the site source.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "guide"
DOCS = ROOT / "docs"
DATA = ROOT / "src" / "thermalfea" / "materials" / "data"

GENERATED_NOTE = (
    '!!! info "Generated page"\n'
    "    This page is generated from {source} by `scripts/build_guide.py`.\n"
    "    Do not edit it here: change the source and run the script again."
)

#: The reference text the correlations and most property tables come from (Theory §8).
REFERENCE_TEXT = (
    "Bergman, Lavine, Incropera and DeWitt, *Fundamentals of Heat and Mass Transfer*, "
    "7th ed., Wiley, 2011"
)

# --------------------------------------------------------------------------------------
# Markdown conversion of the plain-text project documents
# --------------------------------------------------------------------------------------

_TOKEN = re.compile(r"(`[^`\n]*`)|(\\.)|(\*\*)|(\*)|(_)|(<)|(>)")
_LIST_ITEM = re.compile(r"^(\s*)([-*]|\d+\.)\s+(.*)$")
_HEADING = re.compile(r"^(#{1,6}) (.*)$")
_EMPHASIS = re.compile(r"(?<![\w*\\`])\*(?=[^\s*])([^*\n]+(?:\n[^*\n]+)*?)(?<=[^\s*\\])\*(?![\w*])")
_SECTION_NUMBER =re.compile(r"§(\d+(?:\.\d+)?)")


def escape_inline(text: str) -> str:
    """Protect the characters of a formula that Markdown would otherwise interpret.

    Code spans, existing backslash escapes and paired ``**bold**`` markers are kept; a lone
    ``*`` and every ``_`` are escaped, and ``<`` and ``>`` become entities.

    Parameters
    ----------
    text : str
        One line of the source document.

    Returns
    -------
    str
        The line, safe for Python-Markdown.

    """

    def sub(match: re.Match[str]) -> str:
        if match.group(3):
            return "**"
        if match.group(1) or match.group(2):
            return match.group(0)
        if match.group(4):
            return r"\*"
        if match.group(5):
            return r"\_"
        return "&lt;" if match.group(6) else "&gt;"

    return _TOKEN.sub(sub, text)


def bold_markers(text: str) -> int:
    """Count the ``**`` markers of a line that :func:`escape_inline` leaves in place."""
    return sum(1 for m in _TOKEN.finditer(text) if m.group(3))


def anchor_of(number: str) -> str:
    """Return the explicit heading id used for a section number (``"8.1"`` -> ``sec-8-1``)."""
    return "sec-" + number.replace(".", "-")


def to_markdown(text: str, notes: dict[str, str] | None = None) -> str:
    """Convert a project document (plain text with light Markdown) to MkDocs Markdown.

    Headings get an explicit id when they carry a section sign (``§8.1`` becomes
    ``{#sec-8-1}``), formulas are escaped by :func:`escape_inline`, a blank line is put
    before lists and tables, and nested list items are indented to four spaces.

    Parameters
    ----------
    text : str
        The document text.
    notes : dict of str to str, optional
        Heading text (start of it) -> Markdown block inserted right after that heading.
        Every key must match a heading, or ``ValueError`` is raised.

    Returns
    -------
    str
        Markdown without a trailing newline.
    """
    notes = dict(notes or {})
    # *emphasis* (opening star before text, closing star after text, may span lines).
    text = _EMPHASIS.sub(lambda m: "\x01" + m.group(1) + "\x02", text)
    out: list[str] = []
    in_list = False
    in_table = False
    bold = 0  # ** markers seen in the current paragraph; must be even where it ends
    for raw in text.rstrip("\n").split("\n"):
        line = raw.rstrip()
        if bold % 2 and (not line or _HEADING.match(line) or line.lstrip().startswith("|")):
            raise ValueError(f"unbalanced ** before: {line!r}")
        bold += bold_markers(line)
        if not line:
            bold = 0
            out.append("")
            in_list = in_table = False
            continue
        heading = _HEADING.match(line)
        if heading:
            hashes, title = heading.groups()
            if out and out[-1] != "":
                out.append("")
            number = _SECTION_NUMBER.search(title)
            suffix = f" {{#{anchor_of(number.group(1))}}}" if number else ""
            out.append(f"{hashes} {escape_inline(title)}{suffix}")
            for key in list(notes):
                if title.startswith(key):
                    out += ["", notes.pop(key)]
            out.append("")
            in_list = in_table = False
            continue
        if line.lstrip().startswith("|"):
            if not in_table and out and out[-1] != "":
                out.append("")
            out.append(escape_inline(line))
            in_table, in_list = True, False
            continue
        item = _LIST_ITEM.match(line)
        if item:
            indent, marker, rest = item.groups()
            if not in_list and out and out[-1] != "":
                out.append("")
            out.append(" " * (2 * len(indent)) + f"{marker} " + escape_inline(rest))
            in_list, in_table = True, False
            continue
        if in_table and out and out[-1] != "":
            out.append("")
        in_table = False
        out.append(escape_inline(line))
    if notes:
        raise ValueError(f"no heading matches the notes {sorted(notes)}")
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip("\n")
    return result.replace("\x01", "*").replace("\x02", "*")


def sections(text: str, level: str) -> dict[str, list[str]]:
    """Split a document at the headings of one level (``"##"`` or ``"###"``).

    Returns
    -------
    dict of str to list of str
        Heading line (including the hashes) -> the lines below it up to the next heading
        of the same or a higher level. Insertion order is document order.
    """
    result: dict[str, list[str]] = {}
    current: str | None = None
    stops = tuple("#" * n + " " for n in range(1, len(level) + 1))
    for line in text.split("\n"):
        if line.startswith(stops):
            current = line if line.startswith(level + " ") else None
            if current is not None:
                result[current] = []
            continue
        if current is not None:
            result[current].append(line)
    return result


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


# --------------------------------------------------------------------------------------
# theory.md
# --------------------------------------------------------------------------------------

_NOT_AVAILABLE = (
    '!!! warning "Not available in this version"\n'
    "    {what} is not implemented in this version ({task} is on hold). The theory is kept\n"
    "    here for completeness; no solver module uses it yet."
)


def theory_page() -> str:
    """Return the text of ``guide/theory.md``."""
    source = _read(DOCS / "theory.md")
    notes = {
        "§10 Enclosure radiation": _NOT_AVAILABLE.format(
            what="Enclosure radiation (surface-to-surface radiation, §10 to §10.2)",
            task="milestone M9",
        ),
        "§12 Phase change": _NOT_AVAILABLE.format(
            what="Phase change (apparent heat capacity)", task="task M10.2"
        ),
    }
    body = to_markdown(source, notes)
    first, rest = body.split("\n", 1)
    note = GENERATED_NOTE.format(source="`docs/theory.md`")
    return f"{first}\n\n{note}\n{rest}\n"


# --------------------------------------------------------------------------------------
# correlations.md
# --------------------------------------------------------------------------------------

#: Entries whose properties are not taken at the film temperature (Theory §8, §8.1).
_DUCT_ID = "duct_internal"
_NOT_A_BC = (
    "Not offered as a convection boundary condition: internal flow belongs to streams "
    "(see [Theory §9](theory.md#sec-9))."
)


def _section_links(source: str) -> str:
    numbers: list[str] = []
    for found in _SECTION_NUMBER.findall(source):
        if found not in numbers:
            numbers.append(found)
    return ", ".join(f"[Theory §{n}](theory.md#{anchor_of(n)})" for n in numbers)


def correlations_page() -> str:
    """Return the text of ``guide/correlations.md``."""
    from thermalfea.convection.correlation_info import (
        CORRELATION_INFO,
        properties_at,
    )
    from thermalfea.convection.correlations import CORRELATIONS

    missing = set(CORRELATIONS) ^ set(CORRELATION_INFO)
    if missing:
        raise ValueError(f"correlation_info and correlations disagree on {sorted(missing)}")

    theory = _read(DOCS / "theory.md")
    secs = sections(theory, "##")
    sec8 = next(v for k, v in secs.items() if k.startswith("## §8 "))
    first_table = next(i for i, ln in enumerate(sec8) if ln.startswith("|"))
    last_table = first_table
    while last_table + 1 < len(sec8) and sec8[last_table + 1].startswith("|"):
        last_table += 1
    # The first "###" in sec8 starts section 8.1; everything before it is section 8 itself.
    sub = next((i for i, ln in enumerate(sec8) if ln.startswith("### ")), len(sec8))
    # Everything from the first level-3 heading on is sec 8.1 (sections() stops only at ##).
    intro = "\n".join(sec8[:first_table]).strip("\n")
    after = "\n".join(sec8[last_table + 1 : sub]).strip("\n")
    duct = "\n".join(sec8[sub:]).strip("\n")

    lines = [
        "# Correlation reference",
        "",
        GENERATED_NOTE.format(
            source="`src/thermalfea/convection/correlation_info.py` and `docs/theory.md` §8"
        ),
        "",
        "Every convection correlation of the program, with its formula, characteristic "
        "length, inputs, validity range and the place in the [theory manual](theory.md) "
        "it comes from. The texts are copied from the project documents; nothing on this "
        "page is computed.",
        "",
        "## Common relations (Theory §8) {#corr-common}",
        "",
        to_markdown(intro),
        "",
        "## Summary",
        "",
        "| ID | Situation | Characteristic length | Validity |",
        "|---|---|---|---|",
    ]
    for cid, info in CORRELATION_INFO.items():
        validity = escape_inline(info.validity).replace("|", "\\|")
        lines.append(
            f"| [`{cid}`](#corr-{cid.replace('_', '-')}) | {escape_inline(info.title)} "
            f"| {escape_inline(info.length)} | {validity} |"
        )
    lines += ["", "## Correlations", ""]
    for cid, info in CORRELATION_INFO.items():
        inputs = ", ".join(f"`{name}`" for name in info.inputs)
        if info.needs_fluid:
            needs = (
                f"{inputs}, the surface and fluid temperatures, and the fluid "
                "(the keyword inputs of `thermalfea.api.htc`)."
            )
        else:
            needs = f"{inputs}, and the surface and fluid temperatures. No fluid is used."
        if cid == _DUCT_ID:
            where = "The bulk fluid temperature (Theory §8.1)."
        elif info.needs_fluid:
            where = escape_inline(properties_at(cid))
        else:
            where = "None: the correlation does not use fluid properties."
        lines += [
            f"### `{cid}`: {escape_inline(info.title)} {{#corr-{cid.replace('_', '-')}}}",
            "",
            "Formula (copied from the theory document):",
            "",
            "```text",
            info.formula,
            "```",
            "",
            f"- **Characteristic length L_c:** {escape_inline(info.length)}",
            f"- **Inputs:** {needs}",
            f"- **Fluid properties evaluated at:** {where}",
            f"- **Validity range (as recorded):** {escape_inline(info.validity)}",
            f"- **Theory section:** {_section_links(info.source)}",
            f"- **Literature source:** {escape_inline(CORRELATIONS[cid].source)}.",
        ]
        if cid == _DUCT_ID:
            lines.append(f"- **Note:** {_NOT_A_BC}")
        lines.append("")
    lines += [
        "## Validity ranges and warnings",
        "",
        to_markdown(after),
        "",
        "## Internal duct flow, friction factor and pressure drop (Theory §8.1)",
        "",
        "This is the text of §8.1 of the theory document, unchanged. It holds the laminar "
        "Nusselt numbers, the turbulent and transition relations, the optional "
        "Dittus–Boelter relation, the Churchill friction factor and the pressure drop of "
        "a duct.",
        "",
        to_markdown(duct.split("\n", 1)[1] if duct.startswith("### ") else duct),
        "",
        "The stream and network equations that use these relations are in "
        "[Theory §9](theory.md#sec-9).",
        "",
        "## Literature sources",
        "",
        f"Every correlation except the user power law comes from {REFERENCE_TEXT}; each "
        "entry above gives its equation numbers. The Churchill friction factor (1977) is "
        "not in that book. The correlations of the book that the program does not use, "
        "and why, are listed in [Theory §8.2](theory.md#sec-8-2).",
    ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------
# materials.md
# --------------------------------------------------------------------------------------

_SOLID_COLUMNS = (
    ("k", "k [W/(m K)]"),
    ("rho", "ρ [kg/m³]"),
    ("cp", "c_p [J/(kg K)]"),
)
_FLUID_COLUMNS = (
    ("rho", "ρ [kg/m³]"),
    ("cp", "c_p [J/(kg K)]"),
    ("mu", "μ [Pa s]"),
    ("k", "k [W/(m K)]"),
    ("beta", "β [1/K]"),
)


def _g(value: float) -> str:
    return f"{value:g}"


def _load_json(name: str) -> list[dict[str, Any]]:
    return json.loads(_read(DATA / name))


def materials_page() -> str:
    """Return the text of ``guide/materials.md``."""
    solids = _load_json("solids.json")
    fluids = _load_json("fluids.json")
    known = {"name", "source", "note", "k2"} | {key for key, _ in _SOLID_COLUMNS}
    lines = [
        "# Material library",
        "",
        GENERATED_NOTE.format(
            source="`src/thermalfea/materials/data/solids.json` and `fluids.json`"
        ),
        "",
        "The built-in library holds solids (conductivity, density and specific heat) and "
        "fluids (temperature tables of the properties the convection correlations need). "
        "Open it in the program with Tools > Material library.... You can add your own "
        "solids and fluids; they are stored in `%APPDATA%/ThermalFEA/materials.json`.",
        "",
        "Every value comes from Bergman, Lavine, Incropera and DeWitt, *Fundamentals of "
        "Heat and Mass Transfer*, 7th ed., Wiley, 2011, Appendix A, or from the NIST "
        "Chemistry WebBook (water). The source of each entry is listed with it.",
        "",
        "## Solids",
        "",
        "Every built-in solid has constant properties, quoted at 300 K. Most are isotropic; "
        "four are orthotropic and list a second conductivity k2 across the material axis. "
        "A material you create yourself may instead use a table against temperature.",
        "",
        "| Name | " + " | ".join(label for _, label in _SOLID_COLUMNS) + " | Source | Note |",
        "|---|" + "---|" * len(_SOLID_COLUMNS) + "---|---|",
    ]
    for item in solids:
        extra = set(item) - known
        if extra:
            raise ValueError(f"solids.json has keys the generator does not know: {extra}")
        cells = []
        for key, _ in _SOLID_COLUMNS:
            value = item[key]
            if isinstance(value, (int, float)):
                text = f"{_g(value)} (constant)"
                if key == "k" and item.get("k2") is not None:
                    text += f", k2 = {_g(item['k2'])} (constant)"
                cells.append(text)
            else:
                temps = item.get("T")
                span = f", {_g(min(temps))} to {_g(max(temps))} K" if temps else ""
                cells.append(f"table{span}")
        cells.append(escape_inline(item.get("source", "")))
        cells.append(escape_inline(item.get("note", "")))
        lines.append(f"| {escape_inline(item['name'])} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Fluids",
        "",
        "Fluid properties are tables against temperature, interpolated linearly. Outside "
        "the table the end values are used and a warning is logged. For an ideal gas the "
        "expansion coefficient is β = 1/T_film; for a liquid it comes from the β column.",
        "",
    ]
    for item in fluids:
        temps = item["T"]
        columns = [(k, label) for k, label in _FLUID_COLUMNS if item.get(k) is not None]
        lines += [
            f"### {escape_inline(item['name'])}",
            "",
            f"- Source: {escape_inline(item.get('source', ''))}",
            *([f"- Note: {escape_inline(item['note'])}"] if item.get("note") else []),
            f"- Ideal gas: {'yes' if item['ideal_gas'] else 'no'}",
            f"- Temperature range of the tables: {_g(min(temps))} K to {_g(max(temps))} K "
            f"({len(temps)} points)",
            "- Tabulated properties: "
            + ", ".join(label for _, label in columns)
            + ("" if item.get("beta") is not None else " (β is not tabulated; 1/T_film is used)"),
            "",
            "| T [K] | " + " | ".join(label for _, label in columns) + " |",
            "|---|" + "---|" * len(columns),
        ]
        for i, temp in enumerate(temps):
            row = " | ".join(_g(item[key][i]) for key, _ in columns)
            lines.append(f"| {_g(temp)} | {row} |")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


# --------------------------------------------------------------------------------------
# verification.md
# --------------------------------------------------------------------------------------

#: Verification cases whose feature is on hold, with the reason (handover, section 3).
INACTIVE_CASES = (
    ("V-22a to V-22d", "enclosure radiation (milestone M9, on hold)"),
    ("V-23", "enclosure radiation (milestone M9, on hold)"),
    ("V-24", "enclosure radiation (milestone M9, on hold)"),
    ("V-36", "phase change (task M10.2, on hold)"),
)


def verification_page() -> str:
    """Return the text of ``guide/verification.md``."""
    source = _read(DOCS / "verification.md")
    for case, _ in INACTIVE_CASES:
        for part in re.findall(r"V-\d+[a-d]?", case):
            if part not in source:
                raise ValueError(f"{part} is not in docs/verification.md")
    inactive = "\n".join(f"- {case}: {why}" for case, why in INACTIVE_CASES)
    notes = {
        "Enclosure radiation": (
            '!!! warning "Not active in this version"\n'
            "    Enclosure radiation is on hold (milestone M9). The cases V-22a to V-24 "
            "below are\n    specified but not run in this version."
        ),
    }
    body = to_markdown(source, notes)
    first, rest = body.split("\n", 1)
    note = GENERATED_NOTE.format(source="`docs/verification.md`")
    status = (
        "## Which cases are active\n\n"
        "The program is checked against the cases below: each has an analytic or published "
        "answer and a tolerance. The tolerances are part of the specification and are never "
        "loosened to make a case pass. The computed results are not part of this page.\n\n"
        "These cases are specified but **not active in this version**, because the feature "
        "they check is on hold:\n\n"
        f"{inactive}\n\n"
        "All other cases are active in this version. The cases V-33 and V-37 have no "
        "runnable script in `examples/`; they are built inside their tests. V-25 and V-26 "
        "are checks of functions, not of a model.\n\n"
        "## The cases\n"
    )
    return f"{first}\n\n{note}\n\n{status}{rest}\n"


# --------------------------------------------------------------------------------------
# units.md
# --------------------------------------------------------------------------------------


def units_page() -> str:
    """Return the text of ``guide/units.md``."""
    from thermalfea.core import units as u
    from thermalfea.gui.dialogs.units import QUANTITY_NAMES

    presets = list(u.PRESETS)
    lines = [
        "# Unit systems",
        "",
        GENERATED_NOTE.format(source="`src/thermalfea/core/units.py`"),
        "",
        "## What the units setting does",
        "",
        "Choose the units numbers are shown and typed in with Tools > Units.... The dialog "
        "has a \"Preset\" box and one box per quantity. A preset only fills the boxes in; "
        "any one of them can be changed afterwards, and the preset box then reads "
        "\"Custom\". The change is one undo step.",
        "",
        "Units are display units only:",
        "",
        "- The model file (`.tfea`) and the results file store every value in SI, with "
        "temperature in kelvin. Changing units changes neither the model nor its results, "
        "and makes nothing out of date.",
        "- Results (plots, read-outs) are shown in the units of the model stored in the "
        "results file until you change the units in the session; after that they follow "
        "the model.",
        "- Temperature differences follow the temperature unit (K for K and °C, °F "
        "degrees for °F).",
        "- All conversion factors follow from the exact definitions of the inch, foot, "
        "pound, International Table BTU and pound-force.",
        "",
        "## Expressions are always SI",
        "",
        "A function given as an expression is evaluated with t in s, x and y in m and T in "
        "K, and it returns the SI unit of the quantity, whatever the display units are. The "
        "function editor says so when a display unit is not SI. Constants and tables are "
        "converted.",
        "",
        "## Places that still show SI only",
        "",
        "- the HTC calculator window (Tools > HTC calculator...);",
        "- the solve-progress dialog and the solver messages;",
        "- the extra parameters of a correlation;",
        "- CSV and VTU export (the chart CSV, however, follows the display units);",
        "- the text of `thermalfea.api.summary`.",
        "",
        "## Presets",
        "",
        "| Quantity | " + " | ".join(presets) + " |",
        "|---|" + "---|" * len(presets),
    ]
    for quantity, title in QUANTITY_NAMES.items():
        cells = [escape_inline(u.unit_label(quantity, u.PRESETS[p])) for p in presets]
        lines.append(f"| {title} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "The SI presets keep K or °C as it is when you choose them (a model in °F goes to "
        "°C); \"US customary\" always sets °F. In \"US customary\" lengths are in inches "
        "but the heat-transfer units use feet.",
        "",
        "## Units you can choose",
        "",
        "The first unit listed for each quantity is the SI unit.",
        "",
        "| Quantity | Units offered |",
        "|---|---|",
    ]
    for quantity, title in QUANTITY_NAMES.items():
        offered = ", ".join(escape_inline(u.label_of(quantity, unit)) for unit in
                            u.units_of(quantity))
        lines.append(f"| {title} | {offered} |")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------------------

#: File name in ``guide/`` -> function returning its text.
PAGES: dict[str, Callable[[], str]] = {
    "theory.md": theory_page,
    "correlations.md": correlations_page,
    "materials.md": materials_page,
    "verification.md": verification_page,
    "units.md": units_page,
}


def render_all() -> dict[str, str]:
    """Return the text of every generated page, keyed by file name."""
    return {name: build() for name, build in PAGES.items()}


def out_of_date(pages: dict[str, str] | None = None) -> list[str]:
    """Return the names of the generated pages whose checked-in file differs.

    Parameters
    ----------
    pages : dict of str to str, optional
        Output of :func:`render_all` (computed when omitted).
    """
    pages = render_all() if pages is None else pages
    stale = []
    for name, text in pages.items():
        path = GUIDE / name
        current = path.read_bytes().decode("utf-8") if path.is_file() else None
        if current is None or current.replace("\r\n", "\n") != text:
            stale.append(name)
    return stale


def main(argv: Sequence[str] | None = None) -> int:
    """Write (or with ``--check`` verify) the generated pages.

    Returns
    -------
    int
        0 on success; 1 with ``--check`` when a page is out of date.
    """
    parser = argparse.ArgumentParser(description="Generate the reference pages of guide/.")
    parser.add_argument(
        "--check", action="store_true",
        help="write nothing; exit 1 if a generated page is out of date",
    )
    args = parser.parse_args(argv)
    pages = render_all()
    stale = out_of_date(pages)
    if args.check:
        if stale:
            sys.stdout.write("out of date: " + ", ".join(stale) + "\n")
            return 1
        sys.stdout.write("generated pages are up to date\n")
        return 0
    GUIDE.mkdir(exist_ok=True)
    for name in stale:
        (GUIDE / name).write_bytes(pages[name].encode("utf-8"))
        sys.stdout.write(f"wrote guide/{name}\n")
    if not stale:
        sys.stdout.write("nothing to write\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
