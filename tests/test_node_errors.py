"""Tests that every Kling node reports failures as ``NodeError``.

Requests go through the real ``requests`` stack: only the adapter that would open the socket is
replaced, so ``raise_for_status``, ``.json()`` and the exception types are the ones a live failure
produces. Secrets come from a stubbed manager.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
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

SETTINGS_LINK = "#settings-secrets?filter=KLING"
TASK_ID = "task-123"
FAILED_BODY = {
    "code": 0,
    "data": {"task_id": TASK_ID, "task_status": "failed", "task_status_msg": "Content did not pass review"},
}
SUBMITTED_BODY = {"code": 0, "data": {"task_id": TASK_ID, "task_status": "submitted"}}
PROCESSING_BODY = {"code": 0, "data": {"task_id": TASK_ID, "task_status": "processing"}}

NODE_CLASSES = [
    KlingAI_TextToVideo,
    KlingAI_ImageToVideo,
    KlingAI_VideoExtension,
    KlingAI_LipSync,
    KlingV3MultiShot,
    KlingAI_MotionControl,
]

Route = Callable[[requests.PreparedRequest], tuple[int, Any]]


def _response(status: int, body: Any, request: requests.PreparedRequest) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response._content = body.encode() if isinstance(body, str) else json.dumps(body).encode()
    response.url = request.url or ""
    response.request = request
    return response


@pytest.fixture
def api_key() -> Iterator[None]:
    with patch.object(kling_auth, "GriptapeNodes") as griptape_nodes:
        griptape_nodes.SecretsManager.return_value.get_secret.side_effect = lambda name, **_: (
            "test-key" if name == "KLING_API_KEY" else None
        )
        yield


@pytest.fixture
def no_key() -> Iterator[None]:
    with patch.object(kling_auth, "GriptapeNodes") as griptape_nodes:
        griptape_nodes.SecretsManager.return_value.get_secret.return_value = None
        yield


@pytest.fixture
def kling_api_server() -> Iterator[Callable[[Route], list[requests.PreparedRequest]]]:
    """Install a route for every Kling call, and return the list of requests it saw."""
    seen: list[requests.PreparedRequest] = []
    patches: list[Any] = []

    def install(route: Route) -> list[requests.PreparedRequest]:
        def send(_adapter: Any, request: requests.PreparedRequest, **_kwargs: Any) -> requests.Response:
            seen.append(request)
            status, body = route(request)
            return _response(status, body, request)

        patcher = patch("requests.adapters.HTTPAdapter.send", send)
        patcher.start()
        patches.append(patcher)
        return seen

    with patch("time.sleep"):
        yield install
    for patcher in patches:
        patcher.stop()


def _run(node: Any) -> None:
    """Run a node the way the engine does, through the generator when it has one."""
    result = node.process()
    if result is not None:
        for step in result:
            step()


@pytest.mark.parametrize("node_class", NODE_CLASSES)
@pytest.mark.usefixtures("no_key")
def test_a_missing_key_is_the_only_validation_error_and_links_to_settings(node_class: type) -> None:
    node = node_class(name="node")

    errors = node.validate_before_node_run()

    assert errors is not None
    assert len(errors) == 1
    assert isinstance(errors[0], NodeError)
    assert "KLING_API_KEY is not set" in str(errors[0])
    assert errors[0].links[0].url == SETTINGS_LINK


@pytest.mark.parametrize("node_class", NODE_CLASSES)
@pytest.mark.usefixtures("no_key")
def test_a_missing_key_at_run_time_raises_before_any_input_check(node_class: type) -> None:
    node = node_class(name="node")

    with pytest.raises(NodeError, match="KLING_API_KEY is not set"):
        _run(node)


@pytest.mark.usefixtures("api_key")
def test_a_refused_key_reports_kling_and_the_ids(kling_api_server: Callable[[Route], Any]) -> None:
    body = {"code": 1002, "message": "Authorization is invalid", "request_id": "req-7"}
    kling_api_server(lambda _request: (401, body))
    node = KlingAI_TextToVideo(name="node")
    node.set_parameter_value("prompt", "a cat")

    with pytest.raises(NodeError) as error:
        node._process()

    assert "Authorization is invalid" in str(error.value)
    assert error.value.fields == {"status_code": 401, "error_code": 1002, "request_id": "req-7"}
    assert error.value.response == body
    assert error.value.links[0].url == SETTINGS_LINK


@pytest.mark.parametrize(
    ("node_class", "label"),
    [
        (KlingAI_TextToVideo, "video generation"),
        (KlingAI_VideoExtension, "video extension"),
    ],
)
@pytest.mark.usefixtures("api_key")
def test_a_failed_task_carries_the_reason_and_task_id(
    node_class: type, label: str, kling_api_server: Callable[[Route], Any]
) -> None:
    kling_api_server(lambda request: (200, SUBMITTED_BODY if request.method == "POST" else FAILED_BODY))
    node = node_class(name="node")
    node.set_parameter_value("video_id" if label == "video extension" else "prompt", "vid-1")

    with pytest.raises(NodeError) as error:
        _run(node)

    assert str(error.value) == f"Kling could not finish the {label}: Content did not pass review."
    assert error.value.fields == {"task_id": TASK_ID, "status": "failed"}
    assert error.value.response == FAILED_BODY


@pytest.mark.usefixtures("api_key")
def test_lip_sync_failed_task_raises_instead_of_returning_an_empty_artifact(
    kling_api_server: Callable[[Route], Any],
) -> None:
    kling_api_server(lambda request: (200, SUBMITTED_BODY if request.method == "POST" else FAILED_BODY))
    node = KlingAI_LipSync(name="node")
    node.set_parameter_value("video_input_type", "video_id")
    node.set_parameter_value("video_id", "vid-1")
    node.set_parameter_value("mode", "text2video")
    node.set_parameter_value("text", "hello")
    node.set_parameter_value("voice_id", "genshin_vindi2 (en)")

    with pytest.raises(NodeError, match="Content did not pass review") as error:
        _run(node)

    assert error.value.fields["task_id"] == TASK_ID


@pytest.mark.usefixtures("api_key")
def test_multi_shot_failed_task_raises(kling_api_server: Callable[[Route], Any]) -> None:
    kling_api_server(lambda request: (200, SUBMITTED_BODY if request.method == "POST" else FAILED_BODY))
    node = KlingV3MultiShot(name="node")
    node.parameter_values["shots"] = [{"name": "Shot1", "duration": 3, "description": "a cat walks"}]

    with pytest.raises(NodeError, match="multi-shot generation"):
        _run(node)


@pytest.mark.usefixtures("api_key")
def test_a_poll_that_keeps_failing_gives_up_with_kling_s_reason(kling_api_server: Callable[[Route], Any]) -> None:
    def route(request: requests.PreparedRequest) -> tuple[int, Any]:
        if request.method == "POST":
            return 200, SUBMITTED_BODY
        return 500, {"code": 5000, "message": "Internal error", "request_id": "req-5"}

    kling_api_server(route)
    node = KlingAI_VideoExtension(name="node")
    node.set_parameter_value("video_id", "vid-1")

    with pytest.raises(NodeError) as error:
        _run(node)

    assert "after 120 attempts" in str(error.value)
    assert "Internal error" in str(error.value)
    assert error.value.fields == {"status_code": 500, "error_code": 5000, "request_id": "req-5", "task_id": TASK_ID}


@pytest.mark.usefixtures("api_key")
def test_a_task_that_never_finishes_times_out_with_its_id(kling_api_server: Callable[[Route], Any]) -> None:
    kling_api_server(lambda request: (200, SUBMITTED_BODY if request.method == "POST" else PROCESSING_BODY))
    node = KlingAI_VideoExtension(name="node")
    node.set_parameter_value("video_id", "vid-1")

    with pytest.raises(NodeError, match="did not finish") as error:
        _run(node)

    assert error.value.fields == {"task_id": TASK_ID}


@pytest.mark.usefixtures("api_key")
def test_a_submit_without_a_task_id_reports_the_response(kling_api_server: Callable[[Route], Any]) -> None:
    kling_api_server(lambda _request: (200, {"code": 0, "data": {}}))
    node = KlingAI_VideoExtension(name="node")
    node.set_parameter_value("video_id", "vid-1")

    with pytest.raises(NodeError, match="no task ID") as error:
        _run(node)

    assert error.value.response == {"code": 0, "data": {}}


@pytest.mark.usefixtures("api_key")
def test_input_problems_are_node_errors() -> None:
    node = KlingAI_VideoExtension(name="node")

    with pytest.raises(NodeError, match="Video ID is required"):
        _run(node)


@pytest.mark.usefixtures("api_key")
def test_several_input_problems_are_reported_together() -> None:
    node = KlingAI_LipSync(name="node")
    node.set_parameter_value("video_input_type", "video_id")
    node.set_parameter_value("mode", "text2video")

    with pytest.raises(NodeError) as error:
        _run(node)

    assert "Video ID is required" in str(error.value)
    assert "Text is required" in str(error.value)


@pytest.mark.usefixtures("api_key")
def test_image_to_video_without_an_image_is_a_node_error() -> None:
    node = KlingAI_ImageToVideo(name="node")

    with pytest.raises(NodeError, match="At least one of 'image' or 'image_tail'"):
        _run(node)


class _MotionControlHarness:
    """A motion control node with its Failed output wired or unwired."""

    @staticmethod
    def make(*, failed_wired: bool) -> KlingAI_MotionControl:
        node = KlingAI_MotionControl(name="node")
        node._has_outgoing_connections = lambda _parameter: failed_wired
        node.set_parameter_value("reference_image", ImageUrlArtifact("https://example.com/a.png"))
        node.set_parameter_value("reference_video", VideoUrlArtifact("https://example.com/a.mp4"))
        return node


@pytest.mark.usefixtures("api_key")
def test_motion_control_failed_task_raises_when_failed_is_unwired(kling_api_server: Callable[[Route], Any]) -> None:
    kling_api_server(lambda request: (200, SUBMITTED_BODY if request.method == "POST" else FAILED_BODY))
    node = _MotionControlHarness.make(failed_wired=False)

    with pytest.raises(NodeError, match="Content did not pass review") as error:
        node.process()

    assert error.value.fields == {"task_id": TASK_ID, "status": "failed"}
    assert node.parameter_output_values["generation_id"] == TASK_ID
    assert node.parameter_output_values["video_url"] is None


@pytest.mark.usefixtures("api_key")
def test_motion_control_failed_task_follows_failed_when_wired(kling_api_server: Callable[[Route], Any]) -> None:
    kling_api_server(lambda request: (200, SUBMITTED_BODY if request.method == "POST" else FAILED_BODY))
    node = _MotionControlHarness.make(failed_wired=True)

    node.process()

    assert node.parameter_output_values["was_successful"] is False
    assert "Content did not pass review" in node.parameter_output_values["result_details"]


@pytest.mark.usefixtures("api_key")
def test_motion_control_without_a_reference_image_raises_a_node_error() -> None:
    node = KlingAI_MotionControl(name="node")
    node._has_outgoing_connections = lambda _parameter: False
    node.set_parameter_value("reference_video", VideoUrlArtifact("https://example.com/a.mp4"))

    with pytest.raises(NodeError, match="reference image") as error:
        node.process()

    assert error.value.fields == {"parameter": "reference_image"}
    assert node.parameter_output_values["generation_id"] == ""


@pytest.mark.usefixtures("api_key")
def test_motion_control_timeout_raises(kling_api_server: Callable[[Route], Any]) -> None:
    kling_api_server(lambda request: (200, SUBMITTED_BODY if request.method == "POST" else PROCESSING_BODY))
    node = _MotionControlHarness.make(failed_wired=False)

    with patch("motion_control.time.monotonic", side_effect=[0, 1, 2000, 2001]):
        with pytest.raises(NodeError, match="did not finish within 20 minutes"):
            node.process()
