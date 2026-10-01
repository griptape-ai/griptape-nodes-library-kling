"""Turning a failed Kling API call into something the person running the node can act on.

``raise_for_status`` reports the status line and throws the body away, but Kling puts the
only actionable detail in the body. A retired model, an exhausted account balance and a
rejected credential are three unrelated problems that differ only by ``code`` and
``message``, and the first of them arrives as a bare "404 Client Error", which reads as a
broken URL and sends the reader looking in the wrong place entirely.
"""

import requests
from kling_auth import credential_precedence_note

SUCCESS_CODE = 0
CREDENTIAL_REJECTED_CODE = 1002
ACCOUNT_BALANCE_CODE = 1102

# Both of these can really mean "the token came from the wrong place": one is the credential
# being rejected outright, the other is a credential that authenticated an account other than
# the one the user topped up. Neither points at a shadowed mechanism on its own.
CREDENTIAL_SENSITIVE_CODES = (CREDENTIAL_REJECTED_CODE, ACCOUNT_BALANCE_CODE)

MAX_REPORTED_BODY_CHARS = 500


def raise_for_kling_error(response: requests.Response, *, action: str) -> None:
    """Raise carrying Kling's own explanation when a request failed.

    Args:
        response: The response to a Kling API call.
        action: What the node was attempting, completing the sentence "Attempted to ...".

    Raises:
        RuntimeError: If the response reports either an HTTP or an API-level failure.
    """
    body = _json_body(response)
    code = body.get("code")

    if response.ok and code in (None, SUCCESS_CODE):
        return

    reported_code = "" if code is None else f", code {code}"
    reason = body.get("message") or _truncated_text(response)
    detail = f"Kling returned HTTP {response.status_code}{reported_code}: {reason}"

    if code in CREDENTIAL_SENSITIVE_CODES:
        precedence_note = credential_precedence_note()
        if precedence_note is not None:
            detail = f"{detail} {precedence_note}"

    msg = f"Attempted to {action}. {detail}"
    raise RuntimeError(msg)


def _json_body(response: requests.Response) -> dict:
    """Kling's JSON body, or an empty mapping when the response carries something else.

    A gateway failure in front of Kling answers with HTML, and the error path has to
    survive that to report the status code at all.
    """
    try:
        body = response.json()
    except ValueError:
        return {}
    if not isinstance(body, dict):
        return {}
    return body


def _truncated_text(response: requests.Response) -> str:
    """The raw body, bounded, for responses that carry no ``message`` to quote."""
    text = response.text.strip()
    if not text:
        return "no response body"
    if len(text) > MAX_REPORTED_BODY_CHARS:
        return f"{text[:MAX_REPORTED_BODY_CHARS]}..."
    return text
