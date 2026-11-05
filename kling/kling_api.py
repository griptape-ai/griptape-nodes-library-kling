"""Turning a failed Kling API call into something the person running the node can act on.

``raise_for_status`` reports the status line and throws the body away, but Kling puts the
only actionable detail in the body. A retired model, an exhausted account balance and a
rejected credential are three unrelated problems that differ only by ``code`` and
``message``, and the first of them arrives as a bare "404 Client Error", which reads as a
broken URL and sends the reader looking in the wrong place entirely.
"""

import requests
from kling_auth import credential_precedence_note
from kling_errors import error_from_response, response_failed


def raise_for_kling_error(response: requests.Response, *, action: str) -> None:
    """Raise carrying Kling's own explanation when a request failed.

    Args:
        response: The response to a Kling API call.
        action: What the node was attempting, completing the sentence "Attempted to ...".

    Raises:
        NodeError: If the response reports either an HTTP or an API-level failure. The status code,
            Kling's error code, the request ID and the response body are attached to it.
    """
    if not response_failed(response):
        return

    # A rejected credential and an empty balance can both mean the token came from the wrong
    # mechanism, so the note about which one won rides along; kling_errors attaches it only for those.
    raise error_from_response(response, action=action, precedence_note=credential_precedence_note())
