"""Loads the built-in physics so that their term factories are registered.

Each physics module registers the term (or constraint) factory of its boundary-condition
classes when it is imported (Plan §7 rule 6). ``compile`` imports this module once; a new
built-in load adds one import line here, and nothing changes in the compiler, the
serialiser or the drivers. Physics defined outside the package only has to be imported
before a problem is compiled.
"""

from __future__ import annotations

from . import (  # noqa: F401
    body_loads,
    conduction,
    prescribed,
    radiation_ambient,
    surface_loads,
)
