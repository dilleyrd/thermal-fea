"""Write the verification models shipped with the GUI (Examples menu).

Each ``examples/vNN_*.py`` script whose ``run`` returns a ``"case"`` with a model is imported,
run with its defaults (element type ``Q4``) and its model saved as
``src/thermalfea/gui/examples/<script name>.tfea``. An ``index.json`` beside them lists the
file names and titles (first line of each script's docstring).

Run from the project root with the project venv::

    .venv\\Scripts\\python.exe scripts\\make_example_models.py
"""

from __future__ import annotations

import importlib
import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
OUTPUT = ROOT / "src" / "thermalfea" / "gui" / "examples"
ETYPE = "Q4"


def main() -> int:
    """Generate the example models; return the number written."""
    sys.path.insert(0, str(EXAMPLES))
    sys.path.insert(0, str(ROOT / "src"))
    from thermalfea import api

    OUTPUT.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, str]] = []
    for script in sorted(EXAMPLES.glob("v[0-9]*_*.py")):
        module = importlib.import_module(script.stem)
        takes_etype = bool(inspect.signature(module.run).parameters)
        result = module.run(ETYPE) if takes_etype else module.run()
        case = result.get("case")
        if case is None:
            sys.stdout.write(f"skip {script.name}: no model (run returns no case)\n")
            continue
        name = f"{script.stem}.tfea"
        api.save(case.model, OUTPUT / name)
        title = (module.__doc__ or script.stem).strip().splitlines()[0]
        index.append({"file": name, "title": title})
        sys.stdout.write(f"wrote {name}: {title}\n")
    text = json.dumps(index, indent=2, ensure_ascii=False)
    (OUTPUT / "index.json").write_text(text + "\n", encoding="utf-8")
    sys.stdout.write(f"{len(index)} example model(s) in {OUTPUT}\n")
    return len(index)


if __name__ == "__main__":
    main()
