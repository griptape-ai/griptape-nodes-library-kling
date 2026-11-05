"""What the Kling nodes raise beyond `NodeError.from_*`: failures in a 200 body and task failures."""

from __future__ import annotations

from typing import Any

import requests
from griptape_nodes.exe_types.core_types import NodeError

PROVIDER = "Kling"
API_KEY_NAME = "KLING_API_KEY"
KLING_KEYS_URL = "https://app.klingai.com/global/dev/api-key"

SUCCESS_CODE = 0
HTTP_UNAUTHORIZED = 401
# A rejected credential and an empty balance can both mean the token came from the wrong mechanism.
CREDENTIAL_SENSITIVE_CODES = (1002, 1102)


def _body(response: requests.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def response_failed(response: requests.Response) -> bool:
    """True when Kling failed the call by HTTP status or by the `code` in the body of a 200."""
    return not (response.ok and _body(response).get("code") in (None, SUCCESS_CODE))


def error_from_exception(exc: Exception, *, fields: dict[str, str | int] | None = None) -> NodeError:
    """A refused key is a 401 only: Kling's 403 body is unconfirmed."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return NodeError.from_request_exception(
        exc, provider=PROVIDER, secret_name=API_KEY_NAME, key_refused=status == HTTP_UNAUTHORIZED, fields=fields
    )


def error_from_response(response: requests.Response, *, precedence_note: str | None = None) -> NodeError:
    """Adds Kling's int `code` as `error_code`, which the engine only reads from strings."""
    code = _body(response).get("code")
    error = NodeError.from_http_response(
        response,
        provider=PROVIDER,
        secret_name=API_KEY_NAME,
        key_refused=response.status_code == HTTP_UNAUTHORIZED,
        fields={"error_code": code} if code is not None else None,
    )
    if precedence_note and code in CREDENTIAL_SENSITIVE_CODES:
        return NodeError(f"{error} {precedence_note}", fields=error.fields, response=error.response, links=error.links)
    return error


def task_id_from_response(response: requests.Response) -> str:
    data = _body(response).get("data")
    task_id = data.get("task_id") if isinstance(data, dict) else None
    if not task_id:
        msg = "Kling accepted the request but sent no task ID."
        raise NodeError(msg, fields={"status_code": response.status_code}, response=_body(response) or None)
    return str(task_id)


def task_failed_error(label: str, result: dict[str, Any], *, task_id: str) -> NodeError:
    reason = (result.get("data") or {}).get("task_status_msg") or "no reason given"
    msg = f"Kling could not finish the {label}: {str(reason).rstrip('.')}."
    return NodeError(msg, fields={"task_id": task_id, "status": "failed"}, response=result)


def task_timeout_error(label: str, *, task_id: str) -> NodeError:
    msg = f"The Kling {label} did not finish. It may still be running in Kling. Run the node again."
    return NodeError(msg, fields={"task_id": task_id})


def task_result_error(what: str, *, task_id: str, result: dict[str, Any] | None = None) -> NodeError:
    msg = f"Kling finished the task but its result has no {what}."
    return NodeError(msg, fields={"task_id": task_id}, response=result)


def validation_errors_to_raise(errors: list[Exception]) -> Exception:
    if len(errors) == 1:
        return errors[0]
    return NodeError("Fix these inputs and run the node again: " + "; ".join(str(e) for e in errors))
