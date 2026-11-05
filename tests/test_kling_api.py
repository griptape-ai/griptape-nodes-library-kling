"""Tests for reporting a failed Kling API call.

Kling reports some failures in the body of an HTTP 200, and its `code` is an int that the engine's
own response parsing does not pick up. The note about which credential mechanism won is attached only
where it can explain the failure.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import kling_api
import pytest
import requests
from griptape_nodes.exe_types.core_types import NodeError
from kling_api import raise_for_kling_error

PRECEDENCE_NOTE = "KLING_API_KEY takes precedence"


def _response(status_code: int, body: object) -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(body).encode()
    return response


@pytest.fixture(autouse=True)
def no_precedence_note():
    with patch.object(kling_api, "credential_precedence_note", return_value=None):
        yield


def test_a_successful_response_raises_nothing() -> None:
    raise_for_kling_error(_response(200, {"code": 0, "data": {"task_id": "abc"}}))
    raise_for_kling_error(_response(200, {"data": {"task_id": "abc"}}))


def test_a_failure_in_the_body_of_a_200_raises_with_kling_s_reason_and_code() -> None:
    body = {"code": 1201, "message": "Invalid parameter", "request_id": "req-1"}

    with pytest.raises(NodeError) as error:
        raise_for_kling_error(_response(200, body))

    assert str(error.value) == "Invalid parameter"
    assert error.value.fields == {"status_code": 200, "request_id": "req-1", "error_code": 1201}
    assert error.value.response == body


def test_a_retired_model_reports_kling_s_explanation() -> None:
    with pytest.raises(NodeError, match="The model is discontinued") as error:
        raise_for_kling_error(_response(404, {"code": 1203, "message": "The model is discontinued"}))

    assert error.value.fields["error_code"] == 1203
    assert error.value.links == []


def test_a_refused_credential_links_to_the_secret() -> None:
    """The live API answers a bad token with 401 and code 1002."""
    with pytest.raises(NodeError, match="refused the API key") as error:
        raise_for_kling_error(_response(401, {"code": 1002, "message": "The token was expected to have 3 parts"}))

    assert error.value.links[0].url == "#settings-secrets?filter=KLING_API_KEY"


@pytest.mark.parametrize("code", [1002, 1102])
def test_a_credential_failure_explains_which_mechanism_won(code: int) -> None:
    with patch.object(kling_api, "credential_precedence_note", return_value=PRECEDENCE_NOTE):
        with pytest.raises(NodeError) as error:
            raise_for_kling_error(_response(401, {"code": code, "message": "api key not found"}))

    assert PRECEDENCE_NOTE in str(error.value)
    assert error.value.fields["error_code"] == code
    assert error.value.links


def test_an_unrelated_failure_does_not_blame_the_credentials() -> None:
    with patch.object(kling_api, "credential_precedence_note", return_value=PRECEDENCE_NOTE):
        with pytest.raises(NodeError) as error:
            raise_for_kling_error(_response(404, {"code": 1203, "message": "The model is discontinued"}))

    assert PRECEDENCE_NOTE not in str(error.value)
