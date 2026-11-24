"""Entry script of thermalfea-cli.exe (the console program built by thermalfea.spec)."""

import sys

from thermalfea.cli import main

if __name__ == "__main__":
    sys.exit(main())
