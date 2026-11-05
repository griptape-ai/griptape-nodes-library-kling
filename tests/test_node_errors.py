"""Tests that every Kling node reports failures as ``NodeError``.

Requests go through the real ``requests`` stack: only the adapter that would open the socket is
replaced, so ``raise_for_status``, ``.json()`` and the exception types are the ones a live failure
produces. Secrets come from a stubbed manager.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import kling_auth
import pytest
import requests
from griptape.artifacts import ImageUrlArtifact, VideoUrlArtifact
from griptape_nodes.exe_types.core_types import NodeError
from image_to_video import KlingAI_ImageToVideo
from kling_v3_multi_shot import KlingV3MultiShot
from lip_sync import KlingAI_LipSync
from motion_control import KlingAI_MotionControl
from text_to_video import KlingAI_TextToVideo
from video_extension import KlingAI_VideoExtension

SETTINGS_LINK = "#settings-secrets?filter=KLING_API_KEY"
TASK_ID = "task-123"
FAILED_BODY = {
    "code": 0,
    "data": {"task_id": TASK_ID, "task_status": "failed", "task_status_msg": "Content did not pass review"},
}
SUBMITTED_BODY = {"code": 0, "data": {"task_id": TASK_ID, "task_status": "submitted"}}
REFUSED_BODY = {"code": 1002, "message": "Authorization is invalid", "request_id": "req-7"}

NODE_CLASSES = [
    KlingAI_TextToVideo,
    KlingAI_ImageToVideo,
    KlingAI_VideoExtension,
    KlingAI_LipSync,
    KlingV3MultiShot,
    KlingAI_MotionControl,
]

Route = Callable[[requests.PreparedRequest], tuple[int, Any]]


def _secrets(values: dict[str, str]) -> Iterator[None]:
    with patch.object(kling_auth, "GriptapeNodes") as griptape_nodes:
        griptape_nodes.SecretsManager.return_value.get_secret.side_effect = lambda name, **_: values.get(name)
        yield


@pytest.fixture
def api_key() -> Iterator[None]:
    yield from _secrets({"KLING_API_KEY": "test-key"})


@pytest.fixture
def key_pair() -> Iterator[None]:
    yield from _secrets({"KLING_ACCESS_KEY": "access", "KLING_SECRET_KEY": "secret-key-example-padded-to-32-bytes"})


@pytest.fixture
def no_key() -> Iterator[None]:
    yield from _secrets({})


@pytest.fixture
def kling_api_server() -> Iterator[Callable[[Route], None]]:
    """Answer every Kling call from a route, replacing only the adapter that would open the socket."""
    patcher = None

    def install(route: Route) -> None:
        nonlocal patcher

        def send(_adapter: Any, request: requests.PreparedRequest, **_kwargs: Any) -> requests.Response:
            status, body = route(request)
            response = requests.Response()
            response.status_code = status
            response._content = json.dumps(body).encode()
            response.request = request
            return response

        patcher = patch("requests.adapters.HTTPAdapter.send", send)
        patcher.start()

    with patch("time.sleep"):
        yield install
    if patcher:
        patcher.stop()


def _run(node: Any) -> None:
    """Run a node the way the engine does, through the generator when it has one."""
    result = node.process()
    if result is not None:
        for step in result:
            step()


def _failed_task(request: requests.PreparedRequest) -> tuple[int, Any]:
    return (200, SUBMITTED_BODY) if request.method == "POST" else (200, FAILED_BODY)


@pytest.mark.parametrize("node_class", NODE_CLASSES)
@pytest.mark.usefixtures("no_key")
def test_a_missing_key_is_the_only_validation_error_and_links_to_settings(node_class: type) -> None:
    errors = node_class(name="node").validate_before_node_run()

    assert errors is not None
    assert len(errors) == 1
    assert isinstance(errors[0], NodeError)
    assert "KLING_API_KEY is not set" in str(errors[0])
    assert errors[0].links[0].url == SETTINGS_LINK


@pytest.mark.usefixtures("api_key")
def test_a_failed_task_carries_the_reason_and_task_id(kling_api_server: Callable[[Route], Any]) -> None:
    kling_api_server(_failed_task)
    node = KlingAI_TextToVideo(name="node")
    node.set_parameter_value("prompt", "a cat")

    with pytest.raises(NodeError) as error:
        _run(node)

    assert str(error.value) == "Kling could not finish the video generation: Content did not pass review."
    assert error.value.fields == {"task_id": TASK_ID, "status": "failed"}
    assert error.value.response == FAILED_BODY


@pytest.mark.usefixtures("api_key")
def test_a_submit_without_a_task_id_reports_the_response(kling_api_server: Callable[[Route], Any]) -> None:
    kling_api_server(lambda _request: (200, {"code": 0, "data": {}}))
    node = KlingAI_VideoExtension(name="node")
    node.set_parameter_value("video_id", "vid-1")

    with pytest.raises(NodeError, match="no task ID") as error:
        _run(node)

    assert error.value.response == {"code": 0, "data": {}}


@pytest.mark.usefixtures("api_key")
def test_a_401_with_the_api_key_set_links_to_update_it(kling_api_server: Callable[[Route], Any]) -> None:
    kling_api_server(lambda _request: (401, REFUSED_BODY))
    node = KlingAI_TextToVideo(name="node")
    node.set_parameter_value("prompt", "a cat")

    with pytest.raises(NodeError, match="Update KLING_API_KEY") as error:
        node._process()

    assert error.value.links[0].url == "#settings-secrets?filter=KLING_API_KEY"


@pytest.mark.usefixtures("key_pair")
def test_a_401_with_only_the_key_pair_shows_kling_s_message_and_no_link(
    kling_api_server: Callable[[Route], Any],
) -> None:
    kling_api_server(lambda _request: (401, REFUSED_BODY))
    node = KlingAI_TextToVideo(name="node")
    node.set_parameter_value("prompt", "a cat")

    with pytest.raises(NodeError) as error:
        node._process()

    assert str(error.value) == "Authorization is invalid"
    assert error.value.links == []


@pytest.mark.parametrize("failed_wired", [False, True])
@pytest.mark.usefixtures("api_key")
def test_motion_control_failed_task(failed_wired: bool, kling_api_server: Callable[[Route], Any]) -> None:
    kling_api_server(_failed_task)
    node = KlingAI_MotionControl(name="node")
    node._has_outgoing_connections = lambda _parameter: failed_wired
    node.set_parameter_value("reference_image", ImageUrlArtifact("https://example.com/a.png"))
    node.set_parameter_value("reference_video", VideoUrlArtifact("https://example.com/a.mp4"))

    if failed_wired:
        node.process()
        assert node.parameter_output_values["was_successful"] is False
    else:
        with pytest.raises(NodeError, match="Content did not pass review"):
            node.process()
    assert node.parameter_output_values["generation_id"] == TASK_ID


@pytest.mark.parametrize("filename", sorted(p.name for p in (Path(__file__).parent.parent / "kling").glob("*.py")))
def test_every_module_loads_the_way_the_engine_loads_it(filename: str) -> None:
    """The engine loads each file standalone with the library folder on `sys.path`, with no parent package."""
    library = Path(__file__).parent.parent / "kling"
    script = (
        "import importlib.util, sys; "
        f"sys.path.insert(0, {str(library)!r}); sys.modules['kling'] = None; sys.modules['kling_nodes'] = None; "
        f"spec = importlib.util.spec_from_file_location('engine_loaded_module', {str(library / filename)!r}); "
        "module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False)  # noqa: S603
    assert result.returncode == 0, result.stderr
