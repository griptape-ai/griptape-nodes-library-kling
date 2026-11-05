"""Tests for reporting a failed Kling API call."""

from __future__ import annotations

import json
from unittest.mock import patch

import kling_api
import pytest
import requests
from griptape_nodes.exe_types.core_types import NodeError
from kling_api import raise_for_kling_error

NOTE = "KLING_API_KEY takes precedence"


def _response(status_code: int, body: object) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    return response


@pytest.fixture(autouse=True)
def api_key_set():
    with patch("kling_errors.using_api_key", return_value=True):
        yield


def _raise(status: int, body: object, note: str | None = None) -> NodeError:
    with patch.object(kling_api, "credential_precedence_note", return_value=note), pytest.raises(NodeError) as error:
        raise_for_kling_error(_response(status, body))
    return error.value


def test_a_failure_in_the_body_of_a_200_raises_with_the_int_error_code() -> None:
    body = {"code": 1201, "message": "Invalid parameter", "request_id": "req-1"}

    error = _raise(200, body)

    assert str(error) == "Invalid parameter"
    assert error.fields == {"status_code": 200, "request_id": "req-1", "error_code": 1201}
    assert error.response == body


def test_a_success_raises_nothing() -> None:
    raise_for_kling_error(_response(200, {"code": 0, "data": {"task_id": "abc"}}))


def test_a_401_links_to_the_secret() -> None:
    error = _raise(401, {"code": 1002, "message": "The token was expected to have 3 parts"})

    assert "refused the API key" in str(error)
    assert error.links[0].url == "#settings-secrets?filter=KLING_API_KEY"


def test_a_403_and_an_auth_code_in_a_200_are_not_a_refused_key() -> None:
    assert _raise(403, {"code": 1103, "message": "Unauthorized access"}).links == []
    assert _raise(200, {"code": 1004, "message": "Authorization has expired"}).links == []


def test_an_empty_balance_gets_the_precedence_note_and_an_unrelated_failure_does_not() -> None:
    assert NOTE in str(_raise(200, {"code": 1102, "message": "Balance not enough"}, NOTE))
    assert NOTE not in str(_raise(404, {"code": 1203, "message": "Model discontinued"}, NOTE))
