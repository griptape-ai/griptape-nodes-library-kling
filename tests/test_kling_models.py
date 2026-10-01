"""Tests for the dropdowns of Kling models and the migration off retired ones.

Retiring a model is two separate problems. A node built from code must stop offering the
retired id, which is just a list; a workflow saved while the id was still offered restores
its own dropdown over the node's, which is not. These tests cover both, and pin the
invariant the two halves rely on: the id a retired selection migrates to is also the one
``Options`` snaps an unrecognized value to, so the two paths cannot disagree.

Nodes are constructed directly rather than through the library registry, which is how the
engine's own value-set pipeline (converters, then validators, then the node's hooks) gets
exercised without a running engine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

import kling_models
import pytest
from griptape_nodes.exe_types.core_types import Parameter
from image_to_video import KlingAI_ImageToVideo
from kling_models import (
    DEFAULT_IMAGE_TO_VIDEO_MODEL,
    DEFAULT_TEXT_TO_VIDEO_MODEL,
    DROPDOWN_UI_OPTION,
    IMAGE_TO_VIDEO_MODELS,
    LIP_SYNC_MODELS,
    RETIRED_IMAGE_TO_VIDEO_MODELS,
    RETIRED_TEXT_TO_VIDEO_MODELS,
    TEXT_TO_VIDEO_MODELS,
    install_retired_model_migration,
)
from lip_sync import KlingAI_LipSync
from text_to_video import KlingAI_TextToVideo

if TYPE_CHECKING:
    from griptape_nodes.exe_types.node_types import BaseNode

MODEL_PARAMETER = "model_name"


class _Endpoint(NamedTuple):
    """A node and the model lists it was built from, so each can be checked against the other."""

    node_class: type[BaseNode]
    live_models: list[str]
    retired_models: list[str]
    default_model: str


ENDPOINTS = [
    pytest.param(
        _Endpoint(
            KlingAI_TextToVideo,
            TEXT_TO_VIDEO_MODELS,
            RETIRED_TEXT_TO_VIDEO_MODELS,
            DEFAULT_TEXT_TO_VIDEO_MODEL,
        ),
        id="text2video",
    ),
    pytest.param(
        _Endpoint(
            KlingAI_ImageToVideo,
            IMAGE_TO_VIDEO_MODELS,
            RETIRED_IMAGE_TO_VIDEO_MODELS,
            DEFAULT_IMAGE_TO_VIDEO_MODEL,
        ),
        id="image2video",
    ),
]


def _offered_models(node: BaseNode) -> list[str]:
    """The ids the model dropdown currently offers, as ``Options`` resolves them."""
    parameter = node.get_parameter_by_name(MODEL_PARAMETER)
    assert parameter is not None
    return parameter.ui_options[DROPDOWN_UI_OPTION]


def _replay_saved_dropdown(node: BaseNode, saved_choices: list[str]) -> None:
    """Restore a dropdown the way loading a workflow saved before the retirement does.

    The saved ``ui_options`` land on the parameter after the node is built, and the merge in
    ``Parameter.ui_options`` puts them ahead of what the ``Options`` trait publishes, so this
    is enough to put a retired id back among the valid choices.
    """
    parameter = node.get_parameter_by_name(MODEL_PARAMETER)
    assert parameter is not None
    parameter.ui_options = {**parameter.ui_options, DROPDOWN_UI_OPTION: saved_choices}


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_the_dropdown_offers_exactly_the_live_models(endpoint: _Endpoint) -> None:
    node = endpoint.node_class(name="node")

    assert _offered_models(node) == endpoint.live_models


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_the_default_is_also_what_an_unrecognized_value_snaps_to(endpoint: _Endpoint) -> None:
    """``Options`` snaps an unrecognized value to ``choices[0]`` before the migration sees it.

    The migration resolves a retired id to the node's default instead, so reordering the live
    list would leave the two paths answering differently for the same saved workflow.
    """
    assert endpoint.default_model == endpoint.live_models[0]


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_live_and_retired_models_are_disjoint(endpoint: _Endpoint) -> None:
    assert not set(endpoint.live_models) & set(endpoint.retired_models)


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_a_retired_value_resolves_to_the_default(endpoint: _Endpoint) -> None:
    node = endpoint.node_class(name="node")

    for retired_model in endpoint.retired_models:
        node.set_parameter_value(MODEL_PARAMETER, retired_model)

        assert node.get_parameter_value(MODEL_PARAMETER) == endpoint.default_model


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_a_retired_value_resolves_to_the_default_from_a_saved_dropdown(endpoint: _Endpoint) -> None:
    """The case the migration exists for: the saved dropdown makes the retired id valid again."""
    for retired_model in endpoint.retired_models:
        node = endpoint.node_class(name="node")
        _replay_saved_dropdown(node, [retired_model, *endpoint.live_models])

        node.set_parameter_value(MODEL_PARAMETER, retired_model)

        assert node.get_parameter_value(MODEL_PARAMETER) == endpoint.default_model
        assert _offered_models(node) == endpoint.live_models


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_a_saved_dropdown_of_only_retired_models_still_leaves_a_usable_node(endpoint: _Endpoint) -> None:
    """Repairing by replacing rather than filtering is what keeps the dropdown non-empty.

    ``Options`` reads ``choices[0]`` to resolve an unrecognized value, so a dropdown filtered
    down to nothing would raise ``IndexError`` on the next assignment instead of migrating.
    """
    node = endpoint.node_class(name="node")
    _replay_saved_dropdown(node, list(endpoint.retired_models))

    node.set_parameter_value(MODEL_PARAMETER, endpoint.retired_models[0])

    assert node.get_parameter_value(MODEL_PARAMETER) == endpoint.default_model
    assert _offered_models(node) == endpoint.live_models


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_a_live_value_is_left_alone(endpoint: _Endpoint) -> None:
    node = endpoint.node_class(name="node")

    for live_model in endpoint.live_models:
        node.set_parameter_value(MODEL_PARAMETER, live_model)

        assert node.get_parameter_value(MODEL_PARAMETER) == live_model


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_a_live_selection_survives_a_saved_dropdown_repair(endpoint: _Endpoint) -> None:
    """Repairing the dropdown must not disturb a selection that is still valid."""
    node = endpoint.node_class(name="node")
    still_live = endpoint.live_models[-1]
    _replay_saved_dropdown(node, [*endpoint.retired_models, still_live])

    node.set_parameter_value(MODEL_PARAMETER, still_live)

    assert node.get_parameter_value(MODEL_PARAMETER) == still_live


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_a_retired_substitution_is_reported(endpoint: _Endpoint, caplog: pytest.LogCaptureFixture) -> None:
    """Silently changing the model would make a workflow render something nobody asked for.

    Only the saved-dropdown path can report it. On a node built from code the retired id is
    not among the choices, so ``Options``'s own converter has already snapped it to
    ``choices[0]`` before the migration is reached, and there is nothing left to recognize.
    """
    node = endpoint.node_class(name="node")
    retired_model = endpoint.retired_models[0]
    _replay_saved_dropdown(node, [retired_model, *endpoint.live_models])

    with caplog.at_level("WARNING", logger=kling_models.logger.name):
        node.set_parameter_value(MODEL_PARAMETER, retired_model)

    assert retired_model in caplog.text
    assert endpoint.default_model in caplog.text


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_choosing_a_live_model_is_not_reported(endpoint: _Endpoint, caplog: pytest.LogCaptureFixture) -> None:
    node = endpoint.node_class(name="node")

    with caplog.at_level("WARNING", logger=kling_models.logger.name):
        node.set_parameter_value(MODEL_PARAMETER, endpoint.live_models[-1])

    assert caplog.text == ""


@pytest.mark.parametrize("endpoint", ENDPOINTS)
def test_every_live_model_drives_the_duration_controls(endpoint: _Endpoint) -> None:
    """Each live model needs its own branch in ``after_value_set`` to lay out the panel.

    The two duration controls are mutually exclusive, so a model the chain does not handle
    leaves whichever pair the previous selection chose. Nothing ties the dropdown's contents
    to the branches, which is what this checks: adding a model to the live list without
    giving it a branch fails here rather than shipping a stale panel.
    """
    node = endpoint.node_class(name="node")

    for live_model in endpoint.live_models:
        node.set_parameter_value(MODEL_PARAMETER, live_model)

        hidden = {
            name: node.get_parameter_by_name(name).ui_options.get("hide", False)
            for name in ("duration", "klingv3_duration")
        }
        assert sum(hidden.values()) == 1, f"{live_model} left the duration controls as {hidden}"


def test_lip_sync_offers_its_own_models() -> None:
    """Lip-sync still serves the models the video endpoints retired, so it shares no list."""
    node = KlingAI_LipSync(name="node")

    assert _offered_models(node) == LIP_SYNC_MODELS


def test_a_migration_target_outside_the_live_models_is_refused() -> None:
    """A typo here would quietly migrate every saved workflow onto a model Kling cannot serve."""
    node = KlingAI_TextToVideo(name="node")
    parameter = Parameter(name="model", type="str", tooltip="")

    with pytest.raises(ValueError, match="not a live model"):
        install_retired_model_migration(
            node,
            parameter,
            live_models=TEXT_TO_VIDEO_MODELS,
            retired_models=RETIRED_TEXT_TO_VIDEO_MODELS,
            default_model=RETIRED_TEXT_TO_VIDEO_MODELS[0],
        )
