"""Entry script of ThermalFEA.exe (the windowed program built by thermalfea.spec)."""

import os
import sys

# A windowed frozen program has no console: sys.stdout and sys.stderr are None, and code
# that writes to them would fail. Give them somewhere harmless to write.
for _name in ("stdout", "stderr"):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115

from thermalfea.gui.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
