"""Helpers shared by the tutorial examples (``examples/tutorial_*.py``).

The three tutorials of the user guide (``guide/tutorials/*.md``) each have an example
script that builds the same model as the page, returns the numbers the page quotes and
writes the pictures and the model file the page refers to. This module holds what those
scripts share: the folders, a figure writer that does not use ``pyplot``, and a model
writer (:func:`thermalfea.api.save`).
"""

from __future__ import annotations

from pathlib import Path

from matplotlib.figure import Figure

from thermalfea import api
from thermalfea.model.model import Model

#: Folder of the tutorial pages; images go to ``IMAGES``, finished models to ``MODELS``.
TUTORIALS = Path(__file__).resolve().parents[1] / "guide" / "tutorials"
IMAGES = TUTORIALS / "img"
MODELS = TUTORIALS / "models"

#: Width of every picture of the pages [pixel].
IMAGE_WIDTH_PX = 900


def save_figure(fig: Figure, path: Path, width_px: int = IMAGE_WIDTH_PX) -> Path:
    """Write a figure as a PNG about ``width_px`` pixels wide.

    The plot functions of :mod:`thermalfea.post.plots` return Agg figures and save at
    200 dpi; a tutorial picture is smaller, so the figure is written again here.

    Parameters
    ----------
    fig : matplotlib.figure.Figure
    path : Path
        Target file; its folder is created.
    width_px : int
        Wanted width [pixel]; the dpi follows from the figure width.

    Returns
    -------
    Path
        ``path``.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=width_px / fig.get_figwidth())
    return path


def save_model(model: Model, name: str, folder: Path | None = None) -> Path:
    """Save ``model`` as ``<folder>/<name>.tfea`` (default :data:`MODELS`) and return the path."""
    target = (folder if folder is not None else MODELS) / f"{name}.tfea"
    target.parent.mkdir(parents=True, exist_ok=True)
    api.save(model, target)
    return target
