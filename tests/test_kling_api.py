"""Tests for reporting a failed Kling API call.

Kling signals three unrelated problems (a retired model, an empty account balance, a
rejected credential) through a ``code`` and a ``message`` in the body, and signals the first
of them with an HTTP status that reads as a broken URL. These tests pin that the body reaches
the reader, that a response carrying no usable body still reports something, and that the
note about which credential mechanism won is attached only where it is actually the
explanation.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import kling_api
import pytest
import requests
from kling_api import (
    ACCOUNT_BALANCE_CODE,
    CREDENTIAL_REJECTED_CODE,
    MAX_REPORTED_BODY_CHARS,
    SUCCESS_CODE,
    raise_for_kling_error,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

ACTION = "submit a generation to Kling"
PRECEDENCE_NOTE = "KLING_API_KEY takes precedence"


def _response(status_code: int, body: object = None, *, text: str | None = None) -> requests.Response:
    """A real ``requests.Response``, so the code under test reads ``ok``/``json`` as it would live."""
    response = requests.Response()
    response.status_code = status_code
    if text is not None:
        response._content = text.encode()
    elif body is not None:
        response._content = json.dumps(body).encode()
    else:
        response._content = b""
    return response


@pytest.fixture
def no_precedence_note() -> Iterator[None]:
    """Silence the note by default: it reads the developer's own configured secrets."""
    with patch.object(kling_api, "credential_precedence_note", return_value=None):
        yield


@pytest.mark.usefixtures("no_precedence_note")
def test_a_successful_response_raises_nothing() -> None:
    raise_for_kling_error(_response(200, {"code": SUCCESS_CODE, "data": {"task_id": "abc"}}), action=ACTION)


@pytest.mark.usefixtures("no_precedence_note")
def test_a_body_without_a_code_is_accepted_when_the_status_is_ok() -> None:
    """Not every Kling endpoint answers with an envelope, and a 200 is not a failure."""
    raise_for_kling_error(_response(200, {"data": {"task_id": "abc"}}), action=ACTION)


@pytest.mark.usefixtures("no_precedence_note")
def test_a_retired_model_reports_klings_own_explanation() -> None:
    """Kling retires a model per endpoint, and the 404 alone reads as a wrong URL."""
    response = _response(404, {"code": 1203, "message": "The model is discontinued"})

    with pytest.raises(RuntimeError) as error:
        raise_for_kling_error(response, action=ACTION)

    assert "404" in str(error.value)
    assert "code 1203" in str(error.value)
    assert "The model is discontinued" in str(error.value)
    assert ACTION in str(error.value)


@pytest.mark.usefixtures("no_precedence_note")
def test_an_api_level_failure_under_an_ok_status_still_raises() -> None:
    """Kling reports some failures in the body of a 200, where ``raise_for_status`` sees nothing."""
    response = _response(200, {"code": 1201, "message": "Invalid parameter"})

    with pytest.raises(RuntimeError, match="Invalid parameter"):
        raise_for_kling_error(response, action=ACTION)


@pytest.mark.usefixtures("no_precedence_note")
def test_a_non_json_body_still_reports_the_status() -> None:
    """A gateway in front of Kling answers with HTML, and the error path has to survive it."""
    response = _response(502, text="<html>Bad Gateway</html>")

    with pytest.raises(RuntimeError) as error:
        raise_for_kling_error(response, action=ACTION)

    assert "502" in str(error.value)
    assert "Bad Gateway" in str(error.value)


@pytest.mark.usefixtures("no_precedence_note")
def test_an_empty_body_says_so_rather_than_reporting_nothing() -> None:
    response = _response(500)

    with pytest.raises(RuntimeError, match="no response body"):
        raise_for_kling_error(response, action=ACTION)


@pytest.mark.usefixtures("no_precedence_note")
def test_a_long_body_is_truncated() -> None:
    """An HTML error page would otherwise bury the status code it was quoted to explain."""
    response = _response(502, text="x" * (MAX_REPORTED_BODY_CHARS * 3))

    with pytest.raises(RuntimeError) as error:
        raise_for_kling_error(response, action=ACTION)

    assert len(str(error.value)) < MAX_REPORTED_BODY_CHARS * 2


@pytest.mark.parametrize("code", [CREDENTIAL_REJECTED_CODE, ACCOUNT_BALANCE_CODE])
def test_a_credential_failure_explains_which_mechanism_won(code: int) -> None:
    """Both codes can mean the token came from a mechanism the user forgot was configured."""
    response = _response(401, {"code": code, "message": "api key not found"})

    with patch.object(kling_api, "credential_precedence_note", return_value=PRECEDENCE_NOTE):
        with pytest.raises(RuntimeError) as error:
            raise_for_kling_error(response, action=ACTION)

    assert PRECEDENCE_NOTE in str(error.value)


def test_an_unrelated_failure_does_not_blame_the_credentials() -> None:
    """A retired model has nothing to do with which key was used, so the note would mislead."""
    response = _response(404, {"code": 1203, "message": "The model is discontinued"})

    with patch.object(kling_api, "credential_precedence_note", return_value=PRECEDENCE_NOTE):
        with pytest.raises(RuntimeError) as error:
            raise_for_kling_error(response, action=ACTION)

    assert PRECEDENCE_NOTE not in str(error.value)
