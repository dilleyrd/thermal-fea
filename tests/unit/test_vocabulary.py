"""M11.49: the part / boundary / edge / point vocabulary."""

from __future__ import annotations

import pytest

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.model.vocabulary import ROLES, domain_dim, entity_word, role_dim, role_of


@pytest.mark.parametrize("analysis", ["planar", "axisymmetric"])
def test_domain_dim_of_each_analysis(analysis) -> None:
    assert domain_dim(api.new_model(analysis)) == 2


def test_domain_dim_of_an_unbuilt_model_needs_no_geometry() -> None:
    model = api.new_model("planar", "Fresh")
    assert not model.geometry
    assert domain_dim(model) == 2


def test_unknown_analysis_raises() -> None:
    model = api.new_model()
    object.__setattr__(model, "analysis", "spherical")
    with pytest.raises(ModelError, match="spherical"):
        domain_dim(model)


def test_roles_of_a_2d_domain() -> None:
    assert [role_dim(r, 2) for r in ROLES] == [2, 1, None, 0]
    assert [role_of(d, 2) for d in (2, 1, 0)] == ["part", "boundary", "point"]  # not "edge"


def test_roles_of_a_synthetic_3d_domain() -> None:
    assert [role_dim(r, 3) for r in ROLES] == [3, 2, 1, 0]
    assert [role_of(d, 3) for d in (3, 2, 1, 0)] == ["part", "boundary", "edge", "point"]


def test_role_dim_accepts_a_model_and_role_of_inverts_it() -> None:
    model = api.new_model("axisymmetric")
    for role in ("part", "boundary", "point"):
        dim = role_dim(role, model)
        assert dim is not None and role_of(dim, model) == role


def test_bad_role_and_bad_dim_raise() -> None:
    with pytest.raises(ModelError):
        role_dim("volume", 2)
    with pytest.raises(ModelError):
        role_of(3, 2)


def test_entity_word_singular_and_plural() -> None:
    model = api.new_model()
    assert [entity_word(d, model) for d in (2, 1, 0)] == ["part", "boundary", "point"]
    assert [entity_word(d, model, plural=True) for d in (2, 1, 0)] == [
        "parts", "boundaries", "points",
    ]  # fmt: skip
    assert entity_word(1, 3) == "edge" and entity_word(1, 3, plural=True) == "edges"
