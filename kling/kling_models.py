"""The models each Kling endpoint still serves, and the migration off the ones it does not.

Kling retires a model per endpoint rather than across the whole API: ``kling-v1-6`` no
longer serves text-to-video but still serves lip-sync, and ``kling-v1-5`` no longer serves
image-to-video but also still serves lip-sync. There is therefore no single list of live
models to share between nodes, and whether an endpoint serves a model can only be
measured against the API, never inferred from the version number.

Dropping a retired model from a dropdown does not repair the workflows that already
selected it, because the dropdown a saved workflow restores is not the one the node
declares. ``Parameter.ui_options`` merges the saved ``_ui_options`` over what the
``Options`` trait publishes, and ``Options.choices`` reads that merge, so a workflow saved
while a retired model was still offered replays its own ``simple_dropdown`` and puts the
retired id back among the valid choices. ``install_retired_model_migration`` therefore does
two things in one converter: it replaces a replayed dropdown that still offers retired ids
with the node's live list, and it resolves a retired value to the node's default.

Both halves are load-bearing and neither works alone. Without the migration the restored
value is valid again and reaches Kling, which answers 404. Without the repair the value
migrates but ``Options``'s validator, which reads the same stale choices, rejects the
default for not being among them.
"""

from collections.abc import Sequence

from griptape_nodes.exe_types.core_types import Parameter
from griptape_nodes.exe_types.node_types import BaseNode
from griptape_nodes.retained_mode.griptape_nodes import logger

# Measured against the live API 2026-10-01. A request naming anything outside these lists
# comes back as HTTP 404 with code 1203, so adding a model here without measuring it turns
# a dropdown entry into a generation-time failure.
TEXT_TO_VIDEO_MODELS = ["kling-v3", "kling-v2-6", "kling-v2-5-turbo"]
RETIRED_TEXT_TO_VIDEO_MODELS = ["kling-v2-1-master", "kling-v2-master", "kling-v1-6"]
DEFAULT_TEXT_TO_VIDEO_MODEL = "kling-v3"

IMAGE_TO_VIDEO_MODELS = ["kling-v3", "kling-v2-6", "kling-v2-5-turbo"]
RETIRED_IMAGE_TO_VIDEO_MODELS = [
    "kling-v2-1-master",
    "kling-v2-1",
    "kling-v2-master",
    "kling-v1-5",
    "kling-v1",
]
DEFAULT_IMAGE_TO_VIDEO_MODEL = "kling-v3"

# Lip-sync has retired nothing, so it carries no migration.
LIP_SYNC_MODELS = ["kling-v1-5", "kling-v1-6", "kling-v2", "kling-v2-1"]

# The key ``Options`` publishes its choices under, and the one a saved workflow replays.
DROPDOWN_UI_OPTION = "simple_dropdown"


def install_retired_model_migration(
    node: BaseNode,
    parameter: Parameter,
    *,
    live_models: Sequence[str],
    retired_models: Sequence[str],
    default_model: str,
) -> None:
    """Resolve a retired model id on ``parameter`` to ``default_model``.

    Args:
        node: The node owning ``parameter``, named when reporting a substitution.
        parameter: The model-selection parameter, already carrying its ``Options`` trait.
        live_models: Ids Kling still serves on this node's endpoint, which is the set a
            replayed dropdown is repaired to.
        retired_models: Ids Kling no longer serves on this node's endpoint.
        default_model: The id a retired selection resolves to.

    Raises:
        ValueError: If ``default_model`` is not one of ``live_models``, which would migrate
            a dead model to another dead model or to one the dropdown cannot offer.
    """
    if default_model not in live_models:
        msg = f"Kling model '{default_model}' cannot be a migration target: it is not a live model."
        raise ValueError(msg)

    def migrate(value: object) -> object:
        _repair_replayed_dropdown(parameter, live_models=live_models, retired_models=retired_models)
        if value not in retired_models:
            return value
        logger.warning(
            "Kling has retired the model '%s', so '%s' on '%s' is set to '%s' instead. "
            "Choose a current model to stop this being reported.",
            value,
            parameter.name,
            node.name,
            default_model,
        )
        return default_model

    parameter.add_converter(migrate)


def _repair_replayed_dropdown(
    parameter: Parameter,
    *,
    live_models: Sequence[str],
    retired_models: Sequence[str],
) -> None:
    """Replace a dropdown that still offers retired ids with the node's live list.

    A model dropdown is fixed in node code and never narrowed at run time, so choices that
    disagree with ``live_models`` can only have come from a saved workflow. The write is
    guarded because it emits a UI update, and it has to happen here rather than at node
    construction: the saved options are restored after the node is built, and this converter
    is the last thing to run before ``Options``'s validator reads them.
    """
    offered = parameter.ui_options.get(DROPDOWN_UI_OPTION, [])
    if not any(model in offered for model in retired_models):
        return
    parameter.update_ui_options_key(DROPDOWN_UI_OPTION, list(live_models))
