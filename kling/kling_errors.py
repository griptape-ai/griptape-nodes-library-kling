"""Build ``NodeError``s from Kling responses and failures.

Kling answers a failed call with ``{"code": 1002, "message": "...", "request_id": "..."}``, sometimes under
an HTTP 200. These helpers read the reason out of that body so the message is Kling's own words, and attach
the status code, error code, request ID, task ID and response body to the ``NodeError`` instead of printing
them into the text.

This module is imported by bare name (``from kling_errors import ...``) because the engine loads each node
file on its own with the library folder on ``sys.path``.
"""

from __future__ import annotations

from typing import Any

import requests
from griptape_nodes.exe_types.core_types import NodeError, NodeErrorLink

API_KEY_NAME = "KLING_API_KEY"
KLING_KEYS_URL = "https://app.klingai.com/global/dev/api-key"
# Filtering on the shared prefix shows the API key and the Access Key / Secret Key pair together.
SECRETS_LINK_URL = "#settings-secrets?filter=KLING"

SUCCESS_CODE = 0
# Kling's authorization family: 1000 auth failed, 1001 empty, 1002 invalid, 1003 not yet valid, 1004 expired.
CREDENTIAL_REJECTED_CODES = (1000, 1001, 1002, 1003, 1004)
ACCOUNT_BALANCE_CODE = 1102

HTTP_UNAUTHORIZED = 401
MAX_REPORTED_BODY_CHARS = 500

Fields = dict[str, str | int | float | bool]


def secrets_link(label: str = "Add the API key") -> NodeErrorLink:
    """A link that opens Settings -> API Keys & Secrets filtered to the Kling credentials."""
    return NodeErrorLink(label=label, url=SECRETS_LINK_URL)


def missing_credentials_error(message: str | None = None) -> NodeError:
    """The error for a node that runs without Kling credentials, linking to Settings and to Kling's key page."""
    return NodeError(
        message
        or (
            f"{API_KEY_NAME} is not set. Add it in Settings → API Keys & Secrets, then run the node again. "
            "If you use an Access Key / Secret Key pair, set both KLING_ACCESS_KEY and KLING_SECRET_KEY instead."
        ),
        links=[secrets_link(), NodeErrorLink(label="Get a Kling API key", url=KLING_KEYS_URL)],
    )


def json_body(response: requests.Response) -> dict[str, Any]:
    """Kling's JSON body, or an empty mapping when the response carries something else.

    A gateway failure in front of Kling answers with HTML, and the error path has to survive that
    to report the status code at all.
    """
    try:
        body = response.json()
    except ValueError:
        return {}
    if not isinstance(body, dict):
        return {}
    return body


def truncated_text(response: requests.Response) -> str:
    """The raw body, bounded, for responses that carry no ``message`` to quote."""
    text = (response.text or "").strip()
    if not text:
        return "no response body"
    if len(text) > MAX_REPORTED_BODY_CHARS:
        return f"{text[:MAX_REPORTED_BODY_CHARS]}..."
    return text


def response_failed(response: requests.Response) -> bool:
    """True when Kling reported a failure, by HTTP status or by the ``code`` in the body."""
    code = json_body(response).get("code")
    return not (response.ok and code in (None, SUCCESS_CODE))


def error_from_response(
    response: requests.Response,
    *,
    action: str,
    precedence_note: str | None = None,
    fields: Fields | None = None,
    attempts: int | None = None,
) -> NodeError:
    """The error for a Kling response the node cannot use.

    Args:
        response: The response to a Kling API call.
        action: What the node was attempting, completing the sentence "Attempted to ...".
        precedence_note: Which credential mechanism supplied the token. Attached only for the codes
            where the wrong credential is a plausible explanation.
        fields: Extra labelled values, such as the task ID.
        attempts: How many tries were made, when the call was retried.
    """
    body = json_body(response)
    code = body.get("code")
    reason = str(body.get("message") or truncated_text(response)).strip()

    error_fields: Fields = {"status_code": response.status_code}
    if code is not None:
        error_fields["error_code"] = code if isinstance(code, int | str) else str(code)
    request_id = body.get("request_id")
    if request_id:
        error_fields["request_id"] = str(request_id)
    error_fields.update(fields or {})

    payload: dict[str, Any] = body if body else {"text": truncated_text(response)}

    refused = code in CREDENTIAL_REJECTED_CODES or response.status_code == HTTP_UNAUTHORIZED
    links: list[NodeErrorLink] = []
    if refused:
        message = (
            f"Kling refused the credentials: {reason.rstrip('.')}. "
            "Update the key in Settings → API Keys & Secrets, then run the node again."
        )
        links = [secrets_link("Update the API key"), NodeErrorLink(label="Get a Kling API key", url=KLING_KEYS_URL)]
    else:
        after = f" after {attempts} attempts" if attempts else ""
        message = f"Attempted to {action}{after}. {reason}"

    if precedence_note and (refused or code == ACCOUNT_BALANCE_CODE):
        message = f"{message} {precedence_note}"

    return NodeError(message, fields=error_fields, response=payload, links=links)


def error_from_request_exception(
    exc: requests.exceptions.RequestException,
    *,
    action: str,
    fields: Fields | None = None,
    attempts: int | None = None,
) -> NodeError:
    """The error for a ``requests`` failure, reading Kling's body when the exception carries one."""
    response = getattr(exc, "response", None)
    if response is not None:
        return error_from_response(response, action=action, fields=fields, attempts=attempts)

    after = f" after {attempts} attempts" if attempts else ""
    if isinstance(exc, requests.exceptions.JSONDecodeError):
        message = f"Attempted to {action}{after}, but Kling's reply was not valid JSON."
    else:
        message = f"Could not reach Kling to {action}{after}: {exc}"
    return NodeError(message, fields=fields or None)


def task_id_from_response(response: requests.Response, *, action: str) -> str:
    """The task ID in a successful submit response.

    Raises:
        NodeError: If the body is not JSON or has no ``data.task_id``.
    """
    body = json_body(response)
    data = body.get("data")
    task_id = data.get("task_id") if isinstance(data, dict) else None
    if not task_id:
        reason = "Kling's reply was not valid JSON." if not body else "Kling's reply had no task ID."
        error_fields: Fields = {"status_code": response.status_code}
        raise NodeError(
            f"Attempted to {action}. {reason}",
            fields=error_fields,
            response=body or {"text": truncated_text(response)},
        )
    return str(task_id)


def task_failed_error(
    label: str,
    reason: str | None,
    *,
    task_id: str,
    result: dict[str, Any] | None = None,
) -> NodeError:
    """The error for a task Kling accepted and then reported as failed."""
    return NodeError(
        f"Kling could not finish the {label}: {(reason or 'no reason given').rstrip('.')}.",
        fields={"task_id": task_id, "status": "failed"},
        response=result,
    )


def task_timeout_error(label: str, *, task_id: str, minutes: float | None = None) -> NodeError:
    """The error for a task that did not reach a final status before the node stopped polling."""
    waited = f" within {minutes:.0f} minutes" if minutes else ""
    return NodeError(
        f"The Kling {label} did not finish{waited}. It may still be running in Kling. "
        "Run the node again, or check the task ID in your Kling account.",
        fields={"task_id": task_id},
    )


def task_result_error(what: str, *, task_id: str, result: dict[str, Any] | None = None) -> NodeError:
    """The error for a finished task whose result is missing something the node needs."""
    return NodeError(
        f"Kling finished the task but its result has no {what}.",
        fields={"task_id": task_id},
        response=result,
    )


def validation_errors_to_raise(errors: list[Exception]) -> Exception:
    """One exception for a list of input problems, for a node that raises from ``process``."""
    if len(errors) == 1:
        return errors[0]
    return NodeError("Fix these inputs and run the node again: " + "; ".join(str(e) for e in errors))
