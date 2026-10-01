"""Credential handling for the Kling AI API.

Kling accepts two credential mechanisms and both travel in the same
``Authorization: Bearer <token>`` header. A single API key is sent verbatim. The older
Access Key / Secret Key pair instead signs a short-lived JWT that becomes the token.
The single API key wins when both are configured, so a user who adds one does not have
to clear the pair first.
"""

import time

import jwt
from griptape_nodes.retained_mode.griptape_nodes import GriptapeNodes

SERVICE = "Kling"
API_KEY_ENV_VAR = "KLING_API_KEY"
ACCESS_KEY_ENV_VAR = "KLING_ACCESS_KEY"
SECRET_KEY_ENV_VAR = "KLING_SECRET_KEY"  # noqa: S105

JWT_LIFETIME_SECONDS = 1800
# Kling's clock can run slightly behind ours, which would reject a token that is valid now.
JWT_NOT_BEFORE_LEEWAY_SECONDS = 5


def encode_jwt_token(access_key: str, secret_key: str) -> str:
    """Sign the short-lived JWT that the Access Key / Secret Key pair authenticates with."""
    headers = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": access_key,
        "exp": int(time.time()) + JWT_LIFETIME_SECONDS,
        "nbf": int(time.time()) - JWT_NOT_BEFORE_LEEWAY_SECONDS,
    }
    return jwt.encode(payload, secret_key, algorithm="HS256", headers=headers)


def get_auth_token() -> str:
    """Return the bearer token for the configured credentials.

    Raises:
        ValueError: If neither credential mechanism is completely configured.
    """
    token = _resolve_auth_token()
    if token is None:
        raise ValueError(_credentials_error_message())
    return token


def get_auth_headers() -> dict[str, str]:
    """Return the headers for a JSON request to the Kling API.

    Raises:
        ValueError: If neither credential mechanism is completely configured.
    """
    return {"Content-Type": "application/json", "Authorization": f"Bearer {get_auth_token()}"}


def validate_credentials() -> list[Exception]:
    """Return validation errors when no credential mechanism is completely configured."""
    if _resolve_auth_token() is None:
        return [ValueError(_credentials_error_message())]
    return []


def _get_secret(secret_name: str) -> str | None:
    # Each mechanism is optional, so a missing secret is an expected outcome here rather
    # than an error worth logging.
    return GriptapeNodes.SecretsManager().get_secret(secret_name, should_error_on_not_found=False)


def _resolve_auth_token() -> str | None:
    """Return the bearer token, or None when no mechanism is completely configured."""
    api_key = _get_secret(API_KEY_ENV_VAR)
    if api_key:
        return api_key

    access_key = _get_secret(ACCESS_KEY_ENV_VAR)
    secret_key = _get_secret(SECRET_KEY_ENV_VAR)
    if access_key and secret_key:
        return encode_jwt_token(access_key, secret_key)

    return None


def _credentials_error_message() -> str:
    """Describe what to set, naming the half of a pair that is missing."""
    access_key = _get_secret(ACCESS_KEY_ENV_VAR)
    secret_key = _get_secret(SECRET_KEY_ENV_VAR)

    if access_key and not secret_key:
        return (
            f"Kling {ACCESS_KEY_ENV_VAR} is set but {SECRET_KEY_ENV_VAR} is empty. "
            f"Set {SECRET_KEY_ENV_VAR}, or set {API_KEY_ENV_VAR} to a Kling API key instead."
        )
    if secret_key and not access_key:
        return (
            f"Kling {SECRET_KEY_ENV_VAR} is set but {ACCESS_KEY_ENV_VAR} is empty. "
            f"Set {ACCESS_KEY_ENV_VAR}, or set {API_KEY_ENV_VAR} to a Kling API key instead."
        )
    return (
        f"Kling credentials not found. Set {API_KEY_ENV_VAR} to your Kling API key, or set both "
        f"{ACCESS_KEY_ENV_VAR} and {SECRET_KEY_ENV_VAR} if you use an Access Key / Secret Key pair."
    )
