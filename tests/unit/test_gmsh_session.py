"""M2.3 — gmsh session."""

from __future__ import annotations

import logging
import threading

import pytest

from thermalfea.core.errors import GeometryError
from thermalfea.geometry.gmsh_session import GmshSession, fresh_model


def build_rectangle(name: str, w: float, h: float) -> tuple[float, int]:
    """Build a w x h rectangle; return its area and the number of surfaces in the model."""
    with fresh_model(name) as gmsh:
        tag = gmsh.model.occ.addRectangle(0.0, 0.0, 0.0, w, h)
        gmsh.model.occ.synchronize()
        assert gmsh.model.getCurrent() == name
        return gmsh.model.occ.getMass(2, tag), len(gmsh.model.getEntities(2))


def test_singleton() -> None:
    assert GmshSession.get() is GmshSession.get()


def test_two_builds_in_a_row() -> None:
    session = GmshSession.get()
    area, n = build_rectangle("first", 2.0, 3.0)
    assert area == pytest.approx(6.0)
    assert n == 1
    serial = session.serial
    assert session.model_name == "first"
    area, n = build_rectangle("second", 1.0, 0.5)
    assert area == pytest.approx(0.5)
    assert n == 1  # the previous model was cleared
    assert session.model_name == "second"
    assert session.serial == serial + 1


def test_model_stays_alive_after_the_block() -> None:
    session = GmshSession.get()
    build_rectangle("kept", 2.0, 1.0)
    with session.use(session.serial) as gmsh:
        assert len(gmsh.model.getEntities(2)) == 1
        assert gmsh.model.getCurrent() == "kept"
    with pytest.raises(GeometryError, match="rebuilt"), session.use(session.serial - 1):
        pass


def test_build_from_non_main_thread() -> None:
    result: dict[str, object] = {}

    def work() -> None:
        try:
            result["value"] = build_rectangle("threaded", 4.0, 0.25)
        except BaseException as exc:  # noqa: BLE001 - reported to the main thread
            result["error"] = exc

    thread = threading.Thread(target=work)
    thread.start()
    thread.join(timeout=60)
    assert not thread.is_alive()
    assert "error" not in result, result.get("error")
    area, n = result["value"]  # type: ignore[misc]
    assert area == pytest.approx(1.0)
    assert n == 1
    # and the main thread can carry on afterwards
    assert build_rectangle("main-again", 1.0, 1.0)[0] == pytest.approx(1.0)


def test_first_initialisation_can_happen_in_a_worker_thread() -> None:
    session = GmshSession.get()
    session.finalize()
    assert session.model_name is None
    with pytest.raises(GeometryError, match="no built geometry"), session.use():
        pass
    test_build_from_non_main_thread()


def test_concurrent_builds_are_serialised() -> None:
    errors: list[BaseException] = []
    areas: dict[int, float] = {}

    def work(i: int) -> None:
        try:
            areas[i] = build_rectangle(f"model-{i}", 1.0 + i, 1.0)[0]
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors
    assert areas == {i: pytest.approx(1.0 + i) for i in range(4)}


def test_lock_is_reentrant() -> None:
    session = GmshSession.get()
    with fresh_model("outer") as gmsh:
        gmsh.model.occ.addRectangle(0, 0, 0, 1, 1)
        gmsh.model.occ.synchronize()
        with session.use() as again:
            assert again is gmsh


def test_messages_go_to_logging_not_the_terminal(
    caplog: pytest.LogCaptureFixture, capfd: pytest.CaptureFixture[str]
) -> None:
    with caplog.at_level(logging.DEBUG, logger="thermalfea"):
        with fresh_model("noisy") as gmsh:
            gmsh.model.occ.addRectangle(0, 0, 0, 1, 1)
            gmsh.model.occ.synchronize()
            gmsh.logger.write("something odd", level="warning")
            gmsh.model.mesh.generate(2)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("something odd" in r.getMessage() for r in warnings)
    assert all(r.name == "thermalfea.geometry.gmsh_session" for r in warnings)
    assert any(r.levelno == logging.DEBUG and "gmsh:" in r.getMessage() for r in caplog.records)
    out, err = capfd.readouterr()
    assert out == "" and err == ""
    assert GmshSession.get().flush_messages() == []
