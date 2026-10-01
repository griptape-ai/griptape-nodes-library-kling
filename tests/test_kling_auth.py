"""Tests for Kling credential resolution.

Kling accepts two credential mechanisms that are indistinguishable once they reach the
``Authorization`` header, so the only place the choice between them is observable is here.
These tests pin which mechanism wins, the claims the Access Key / Secret Key pair signs, and
the fact that a registered-but-empty secret does not count as configured. Secrets come from a
stubbed manager, so nothing reads the developer's real environment or touches the network.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

import jwt
import kling_auth
import pytest
from kling_auth import (
    ACCESS_KEY_ENV_VAR,
    API_KEY_ENV_VAR,
    JWT_LIFETIME_SECONDS,
    JWT_NOT_BEFORE_LEEWAY_SECONDS,
    SECRET_KEY_ENV_VAR,
    get_auth_headers,
    get_auth_token,
    validate_credentials,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

API_KEY = "api-key-kling-example"
ACCESS_KEY = "access-key-example"
# At least 32 bytes, or signing warns that the HMAC key is too short for SHA256.
SECRET_KEY = "secret-key-example-padded-to-32-bytes"  # noqa: S105

# A fixed instant so the signed token's exp and nbf claims are exact rather than approximate.
FROZEN_TIME = 1_700_000_000.0


@pytest.fixture
def secrets() -> Iterator[Callable[..., None]]:
    """Return a callable that sets the secrets ``kling_auth`` will read.

    The real manager falls back to the OS environment, which would let an engineer's own
    ``KLING_API_KEY`` decide the outcome of these tests.
    """
    values: dict[str, str] = {}

    def get_secret(secret_name: str, **_kwargs: object) -> str | None:
        return values.get(secret_name)

    with patch.object(kling_auth, "GriptapeNodes") as griptape_nodes:
        griptape_nodes.SecretsManager.return_value.get_secret.side_effect = get_secret
        yield values.update


def test_api_key_is_sent_verbatim(secrets: Callable[..., None]) -> None:
    secrets({API_KEY_ENV_VAR: API_KEY})

    assert get_auth_token() == API_KEY


def test_api_key_wins_over_a_configured_pair(secrets: Callable[..., None]) -> None:
    """Adding an API key switches mechanisms without the user clearing the old pair first."""
    secrets({API_KEY_ENV_VAR: API_KEY, ACCESS_KEY_ENV_VAR: ACCESS_KEY, SECRET_KEY_ENV_VAR: SECRET_KEY})

    assert get_auth_token() == API_KEY


def test_pair_signs_a_short_lived_jwt(secrets: Callable[..., None]) -> None:
    secrets({ACCESS_KEY_ENV_VAR: ACCESS_KEY, SECRET_KEY_ENV_VAR: SECRET_KEY})

    with patch("time.time", return_value=FROZEN_TIME):
        token = get_auth_token()

    assert jwt.get_unverified_header(token) == {"alg": "HS256", "typ": "JWT"}
    claims = jwt.decode(token, SECRET_KEY, algorithms=["HS256"], options={"verify_exp": False, "verify_nbf": False})
    assert claims == {
        "iss": ACCESS_KEY,
        "exp": int(FROZEN_TIME) + JWT_LIFETIME_SECONDS,
        "nbf": int(FROZEN_TIME) - JWT_NOT_BEFORE_LEEWAY_SECONDS,
    }


def test_secret_key_is_never_transmitted(secrets: Callable[..., None]) -> None:
    """The secret key is the HMAC key, so it must not appear in the header it signs."""
    secrets({ACCESS_KEY_ENV_VAR: ACCESS_KEY, SECRET_KEY_ENV_VAR: SECRET_KEY})

    assert SECRET_KEY not in get_auth_headers()["Authorization"]


@pytest.mark.parametrize("empty_value", ["", None])
def test_an_empty_api_key_falls_through_to_the_pair(secrets: Callable[..., None], empty_value: str | None) -> None:
    """Registering a secret writes an empty default for it, which must not count as configured."""
    secrets({API_KEY_ENV_VAR: empty_value, ACCESS_KEY_ENV_VAR: ACCESS_KEY, SECRET_KEY_ENV_VAR: SECRET_KEY})

    assert get_auth_token() != ""


def test_headers_carry_the_token_as_a_bearer(secrets: Callable[..., None]) -> None:
    secrets({API_KEY_ENV_VAR: API_KEY})

    assert get_auth_headers() == {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    }


def test_no_credentials_raises_before_any_request(secrets: Callable[..., None]) -> None:
    secrets({})

    with pytest.raises(ValueError, match=API_KEY_ENV_VAR):
        get_auth_headers()


def test_all_credentials_empty_raises(secrets: Callable[..., None]) -> None:
    secrets({API_KEY_ENV_VAR: "", ACCESS_KEY_ENV_VAR: "", SECRET_KEY_ENV_VAR: ""})

    with pytest.raises(ValueError, match=API_KEY_ENV_VAR):
        get_auth_headers()


def test_half_a_pair_names_the_missing_half(secrets: Callable[..., None]) -> None:
    secrets({ACCESS_KEY_ENV_VAR: ACCESS_KEY})

    with pytest.raises(ValueError, match=f"{SECRET_KEY_ENV_VAR} is empty"):
        get_auth_token()


def test_the_other_half_of_a_pair_names_the_missing_half(secrets: Callable[..., None]) -> None:
    secrets({SECRET_KEY_ENV_VAR: SECRET_KEY})

    with pytest.raises(ValueError, match=f"{ACCESS_KEY_ENV_VAR} is empty"):
        get_auth_token()


@pytest.mark.parametrize(
    "configured",
    [
        pytest.param({API_KEY_ENV_VAR: API_KEY}, id="api-key"),
        pytest.param({ACCESS_KEY_ENV_VAR: ACCESS_KEY, SECRET_KEY_ENV_VAR: SECRET_KEY}, id="pair"),
    ],
)
def test_validation_passes_for_either_mechanism(secrets: Callable[..., None], configured: dict[str, str]) -> None:
    secrets(configured)

    assert validate_credentials() == []


@pytest.mark.parametrize(
    "configured",
    [
        pytest.param({}, id="nothing"),
        pytest.param({ACCESS_KEY_ENV_VAR: ACCESS_KEY}, id="access-key-only"),
        pytest.param({SECRET_KEY_ENV_VAR: SECRET_KEY}, id="secret-key-only"),
    ],
)
def test_validation_reports_incomplete_credentials(secrets: Callable[..., None], configured: dict[str, str]) -> None:
    secrets(configured)

    errors = validate_credentials()

    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)
