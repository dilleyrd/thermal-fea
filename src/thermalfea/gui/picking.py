"""Pure picking geometry for the viewport: plain NumPy functions, no Qt, no Matplotlib.

All coordinates are 2D model coordinates [m] (or any consistent length unit; tolerances
are in the same unit). Event handling and drawing live in ``viewport_mpl.py``; keeping the
geometry here makes it testable without a window.
"""

from __future__ import annotations

import numpy as np
from numpy import ndarray

_XY = 2  # columns of a planar coordinate array: x and y (the viewport is a plane view)
_MIN_LOOP_POINTS = 3

Box = tuple[float, float, float, float]  # xmin, ymin, xmax, ymax


# ---------------------------------------------------------------------------- distances


def nearest_point(points: ndarray, p: ndarray | tuple[float, float], tol: float) -> int | None:
    """Index of the point nearest to ``p`` if it lies within ``tol``.

    Parameters
    ----------
    points : ndarray, shape (n, 2)
        Candidate points [m].
    p : array_like, shape (2,)
        Query position [m].
    tol : float
        Maximum distance [m].

    Returns
    -------
    int or None
        Row of the nearest point, or ``None`` if there is none within ``tol``.
    """
    pts = np.asarray(points, dtype=float).reshape(-1, _XY)
    if pts.shape[0] == 0:
        return None
    d2 = np.sum((pts - np.asarray(p, dtype=float)) ** 2, axis=1)
    k = int(np.argmin(d2))
    return k if d2[k] <= tol * tol else None


def distance_to_segments(a: ndarray, b: ndarray, p: ndarray | tuple[float, float]) -> ndarray:
    """Distance from ``p`` to each segment ``a[i] - b[i]`` (vectorised).

    Parameters
    ----------
    a, b : ndarray, shape (m, 2)
        Segment end points [m].
    p : array_like, shape (2,)
        Query position [m].

    Returns
    -------
    ndarray, shape (m,)
        Distances [m]; a zero-length segment gives the distance to its point.
    """
    q = np.asarray(p, dtype=float)
    ab = b - a
    ap = q - a
    denom = np.sum(ab * ab, axis=1)
    t = np.divide(
        np.sum(ap * ab, axis=1), denom, out=np.zeros_like(denom), where=denom > 0.0
    )
    foot = a + np.clip(t, 0.0, 1.0)[:, None] * ab
    return np.linalg.norm(q - foot, axis=1)


def polyline_segments(polylines: list[ndarray]) -> tuple[ndarray, ndarray, ndarray]:
    """Flatten polylines into segment arrays.

    Parameters
    ----------
    polylines : list of ndarray, shape (n_i, >=2)
        Sampled curves; only the first two columns (x, y) are used.

    Returns
    -------
    a, b : ndarray, shape (m, 2)
        Start and end of every segment.
    owner : ndarray of int, shape (m,)
        Index into ``polylines`` of the curve each segment belongs to.
    """
    starts: list[ndarray] = []
    ends: list[ndarray] = []
    owners: list[ndarray] = []
    for k, line in enumerate(polylines):
        xy = np.asarray(line, dtype=float)[:, :_XY]
        if xy.shape[0] < _XY:
            continue
        starts.append(xy[:-1])
        ends.append(xy[1:])
        owners.append(np.full(xy.shape[0] - 1, k, dtype=int))
    if not starts:
        empty = np.zeros((0, _XY))
        return empty, empty.copy(), np.zeros(0, dtype=int)
    return np.concatenate(starts), np.concatenate(ends), np.concatenate(owners)


def nearest_segment_owner(
    a: ndarray, b: ndarray, owner: ndarray, p: ndarray | tuple[float, float], tol: float
) -> int | None:
    """Owner of the segment nearest to ``p`` if it lies within ``tol``.

    Parameters
    ----------
    a, b, owner : ndarray
        As returned by :func:`polyline_segments`.
    p : array_like, shape (2,)
        Query position [m].
    tol : float
        Maximum distance [m].

    Returns
    -------
    int or None
        The ``owner`` value of the nearest segment, or ``None``.
    """
    if a.shape[0] == 0:
        return None
    d = distance_to_segments(a, b, p)
    k = int(np.argmin(d))
    return int(owner[k]) if d[k] <= tol else None


# ------------------------------------------------------------------------ point in polygon


def point_in_polygon(polygon: ndarray, p: ndarray | tuple[float, float]) -> bool:
    """Even-odd (ray casting) test of ``p`` against one closed polygon.

    Parameters
    ----------
    polygon : ndarray, shape (n, 2)
        Vertices [m]; the closing edge from the last to the first vertex is implied (a
        repeated first vertex at the end is harmless).
    p : array_like, shape (2,)
        Query position [m].

    Returns
    -------
    bool
    """
    return point_in_loops([polygon], p)


def point_in_loops(loops: list[ndarray], p: ndarray | tuple[float, float]) -> bool:
    """Even-odd test of ``p`` against several closed loops (a surface with holes).

    A point inside the outer loop but also inside a hole loop is outside the surface.

    Parameters
    ----------
    loops : list of ndarray, shape (n_i, 2)
        Closed loops [m]; each closing edge is implied.
    p : array_like, shape (2,)
        Query position [m].

    Returns
    -------
    bool
    """
    x, y = float(p[0]), float(p[1])
    inside = False
    for loop in loops:
        v = np.asarray(loop, dtype=float)[:, :_XY]
        if v.shape[0] < _MIN_LOOP_POINTS:
            continue
        x0, y0 = v[:, 0], v[:, 1]
        x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
        straddle = (y0 > y) != (y1 > y)
        dy = np.where(y1 == y0, 1.0, y1 - y0)
        x_cross = x0 + (y - y0) * (x1 - x0) / dy
        crossings = int(np.count_nonzero(straddle & (x < x_cross)))
        inside ^= bool(crossings % 2)
    return inside


def loop_area(loop: ndarray) -> float:
    """Signed area of a closed loop [m^2] (positive when counter-clockwise)."""
    v = np.asarray(loop, dtype=float)[:, :_XY]
    x, y = v[:, 0], v[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def smallest_containing(
    candidates: list[tuple[int, list[ndarray], float]], p: ndarray | tuple[float, float]
) -> int | None:
    """Pick the smallest candidate surface that contains ``p``.

    Parameters
    ----------
    candidates : list of (tag, loops, measure)
        Each surface's tag, its boundary loops and its area [m^2] (used to prefer the
        innermost of nested surfaces).
    p : array_like, shape (2,)
        Query position [m].

    Returns
    -------
    int or None
        Tag of the containing surface with the smallest area, or ``None``.
    """
    best: tuple[float, int] | None = None
    for tag, loops, measure in candidates:
        if point_in_loops(loops, p) and (best is None or measure < best[0]):
            best = (measure, tag)
    return None if best is None else best[1]


def chain_loops(polylines: list[ndarray], tol: float) -> list[ndarray]:
    """Join open polylines end to end into closed loops.

    Parameters
    ----------
    polylines : list of ndarray, shape (n_i, >=2)
        Curves bounding one surface [m]; a curve whose ends meet is a loop by itself.
    tol : float
        Distance [m] below which two end points are the same point.

    Returns
    -------
    list of ndarray, shape (k, 2)
        Closed loops (first point not repeated). Curves that cannot be closed are
        returned as the loop they form so far.
    """
    pending = [np.asarray(line, dtype=float)[:, :_XY] for line in polylines if len(line) >= _XY]
    loops: list[ndarray] = []
    while pending:
        loop = pending.pop(0)
        while np.linalg.norm(loop[0] - loop[-1]) > tol and pending:
            end = loop[-1]
            for i, cand in enumerate(pending):
                if np.linalg.norm(cand[0] - end) <= tol:
                    loop = np.concatenate([loop, cand[1:]])
                elif np.linalg.norm(cand[-1] - end) <= tol:
                    loop = np.concatenate([loop, cand[-2::-1]])
                else:
                    continue
                pending.pop(i)
                break
            else:
                break
        if np.linalg.norm(loop[0] - loop[-1]) <= tol:
            loop = loop[:-1]
        loops.append(loop)
    return loops


# ----------------------------------------------------------------------------- boxes


def normalized_box(p0: tuple[float, float], p1: tuple[float, float]) -> Box:
    """The box spanned by two opposite corners as ``(xmin, ymin, xmax, ymax)``."""
    return (min(p0[0], p1[0]), min(p0[1], p1[1]), max(p0[0], p1[0]), max(p0[1], p1[1]))


def points_in_box(points: ndarray, box: Box) -> ndarray:
    """Boolean mask of the points inside ``box`` (boundary included).

    Parameters
    ----------
    points : ndarray, shape (n, 2)
    box : tuple of 4 float
        ``(xmin, ymin, xmax, ymax)``.

    Returns
    -------
    ndarray of bool, shape (n,)
    """
    pts = np.asarray(points, dtype=float).reshape(-1, _XY)
    x, y = pts[:, 0], pts[:, 1]
    return (x >= box[0]) & (x <= box[2]) & (y >= box[1]) & (y <= box[3])


def all_in_box(points: ndarray, box: Box) -> bool:
    """``True`` if there are points and every one of them lies inside ``box``."""
    pts = np.asarray(points, dtype=float).reshape(-1, _XY)
    return pts.shape[0] > 0 and bool(points_in_box(pts, box).all())
