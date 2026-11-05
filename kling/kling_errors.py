"""Errors the Kling nodes raise beyond what `NodeError` builds itself.

A missing key, a failed HTTP call and a connection failure come from `NodeError.from_missing_secret`,
`NodeError.from_http_response` and `NodeError.from_request_exception`. This module covers what Kling
adds: a failure reported in the body of an HTTP 200, and a task that ends without a video.

Imported by bare name, because the engine loads each node file on its own.
"""

from __future__ import annotations

from typing import Any

import requests
from griptape_nodes.exe_types.core_types import NodeError

__all__ = [
    "API_KEY_NAME",
    "KLING_KEYS_URL",
    "PROVIDER",
    "error_from_exception",
    "error_from_response",
    "response_failed",
    "task_failed_error",
    "task_id_from_response",
    "task_result_error",
    "task_timeout_error",
    "validation_errors_to_raise",
]

PROVIDER = "Kling"
API_KEY_NAME = "KLING_API_KEY"
KLING_KEYS_URL = "https://app.klingai.com/global/dev/api-key"

SUCCESS_CODE = 0
HTTP_UNAUTHORIZED = 401
# 1000 to 1004 are Kling's authorization codes. 1102 is an empty balance, which the wrong account also causes.
AUTH_CODES = (1000, 1001, 1002, 1003, 1004)
CREDENTIAL_SENSITIVE_CODES = (*AUTH_CODES, 1102)


def _body(response: requests.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def response_failed(response: requests.Response) -> bool:
    """True when Kling failed the call by HTTP status or by the `code` in the body of a 200."""
    return not (response.ok and _body(response).get("code") in (None, SUCCESS_CODE))


def _key_refused(response: requests.Response) -> bool:
    """Kling answers a bad token with 401 and codes 1000 to 1004. Its 403 body is unconfirmed, so a 403 is not one."""
    return response.status_code == HTTP_UNAUTHORIZED or _body(response).get("code") in AUTH_CODES


def error_from_exception(exc: Exception, *, fields: dict[str, str | int] | None = None) -> NodeError:
    """`NodeError.from_request_exception` with Kling's idea of a refused key."""
    response = getattr(exc, "response", None)
    return NodeError.from_request_exception(
        exc,
        provider=PROVIDER,
        secret_name=API_KEY_NAME,
        key_refused=_key_refused(response) if response is not None else None,
        fields=fields,
    )


def error_from_response(response: requests.Response, *, precedence_note: str | None = None) -> NodeError:
    """The error for a failed Kling response. Kling's `code` is an int, so it is added to `fields` here."""
    code = _body(response).get("code")
    error = NodeError.from_http_response(
        response,
        provider=PROVIDER,
        secret_name=API_KEY_NAME,
        key_refused=_key_refused(response),
        fields={"error_code": code} if code is not None else None,
    )
    if precedence_note and code in CREDENTIAL_SENSITIVE_CODES:
        return NodeError(f"{error} {precedence_note}", fields=error.fields, response=error.response, links=error.links)
    return error


def task_id_from_response(response: requests.Response) -> str:
    """The task ID in a successful submit response, or a `NodeError` carrying the response."""
    data = _body(response).get("data")
    task_id = data.get("task_id") if isinstance(data, dict) else None
    if not task_id:
        raise NodeError(
            "Kling accepted the request but sent no task ID.",
            fields={"status_code": response.status_code},
            response=_body(response) or None,
        )
    return str(task_id)


def task_failed_error(label: str, result: dict[str, Any], *, task_id: str) -> NodeError:
    """The error for a task Kling accepted and then reported as failed."""
    reason = (result.get("data") or {}).get("task_status_msg") or "no reason given"
    return NodeError(
        f"Kling could not finish the {label}: {str(reason).rstrip('.')}.",
        fields={"task_id": task_id, "status": "failed"},
        response=result,
    )


def task_timeout_error(label: str, *, task_id: str) -> NodeError:
    """The error for a task that had no final status when the node stopped polling."""
    return NodeError(
        f"The Kling {label} did not finish. It may still be running in Kling. Run the node again.",
        fields={"task_id": task_id},
    )


def task_result_error(what: str, *, task_id: str, result: dict[str, Any] | None = None) -> NodeError:
    """The error for a finished task whose result lacks something the node needs."""
    return NodeError(
        f"Kling finished the task but its result has no {what}.", fields={"task_id": task_id}, response=result
    )


def validation_errors_to_raise(errors: list[Exception]) -> Exception:
    """One exception for a list of input problems."""
    if len(errors) == 1:
        return errors[0]
    return NodeError("Fix these inputs and run the node again: " + "; ".join(str(e) for e in errors))
