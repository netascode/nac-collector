import base64
import json
from unittest.mock import Mock, patch

import httpx
import pytest

from nac_collector.controller.sdwan import CiscoClientSDWAN

pytestmark = pytest.mark.unit


def _make_jwt(payload: dict) -> str:
    """Build a fake JWT (header.payload.signature) with the given payload dict."""
    header = (
        base64.urlsafe_b64encode(json.dumps({"alg": "HS256"}).encode())
        .rstrip(b"=")
        .decode()
    )
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    signature = "fake_signature"
    return f"{header}.{body}.{signature}"


@pytest.fixture
def sdwan_client_with_token():
    """SDWAN client configured with a valid mock JWT containing a csrf field."""
    token = _make_jwt({"csrf": "test-csrf-token-123", "sub": "admin"})
    return CiscoClientSDWAN(
        username="",
        password="",
        base_url="https://sdwan.example.com",
        max_retries=3,
        retry_after=1,
        timeout=5,
        ssl_verify=False,
        api_token=token,
    )


@pytest.fixture
def sdwan_client_no_token():
    """SDWAN client configured without api_token (session auth)."""
    return CiscoClientSDWAN(
        username="admin",
        password="admin_pass",
        base_url="https://sdwan.example.com",
        max_retries=3,
        retry_after=1,
        timeout=5,
        ssl_verify=False,
    )


class TestTokenAuthHappyPath:
    """Happy-path test: mock JWT with csrf field, server returns 200."""

    def test_authenticate_token_success(self, sdwan_client_with_token):
        mock_response = Mock()
        mock_response.status_code = 200

        with patch.object(httpx.Client, "get", return_value=mock_response):
            result = sdwan_client_with_token.authenticate()

        assert result is True
        assert sdwan_client_with_token.client is not None
        assert (
            sdwan_client_with_token.base_url == "https://sdwan.example.com/dataservice"
        )

        # Verify headers were set correctly
        headers = sdwan_client_with_token.client.headers
        assert "Bearer " in headers["Authorization"]
        assert headers["X-XSRF-TOKEN"] == "test-csrf-token-123"
        assert headers["Content-Type"] == "application/json"

    def test_authenticate_dispatches_to_token_when_api_token_set(
        self, sdwan_client_with_token
    ):
        """authenticate() should call _authenticate_token when api_token is truthy."""
        with patch.object(
            CiscoClientSDWAN, "_authenticate_token", return_value=True
        ) as mock_token:
            with patch.object(
                CiscoClientSDWAN, "_authenticate_session"
            ) as mock_session:
                sdwan_client_with_token.authenticate()

        mock_token.assert_called_once()
        mock_session.assert_not_called()

    def test_authenticate_dispatches_to_session_when_no_token(
        self, sdwan_client_no_token
    ):
        """authenticate() should call _authenticate_session when api_token is empty."""
        with patch.object(CiscoClientSDWAN, "_authenticate_token") as mock_token:
            with patch.object(
                CiscoClientSDWAN, "_authenticate_session", return_value=True
            ) as mock_session:
                sdwan_client_no_token.authenticate()

        mock_session.assert_called_once()
        mock_token.assert_not_called()


class TestTokenAuthMissingCsrf:
    """Test: JWT payload does NOT contain 'csrf' field."""

    def test_authenticate_token_missing_csrf_returns_false(self):
        token = _make_jwt({"sub": "admin", "exp": 9999999999})
        client = CiscoClientSDWAN(
            username="",
            password="",
            base_url="https://sdwan.example.com",
            max_retries=3,
            retry_after=1,
            timeout=5,
            ssl_verify=False,
            api_token=token,
        )

        result = client.authenticate()

        assert result is False
        assert client.client is None


class TestTokenAuthInvalidJWT:
    """Test: malformed JWT strings."""

    def test_authenticate_token_invalid_jwt_no_dots(self):
        client = CiscoClientSDWAN(
            username="",
            password="",
            base_url="https://sdwan.example.com",
            max_retries=3,
            retry_after=1,
            timeout=5,
            ssl_verify=False,
            api_token="not-a-jwt",
        )

        result = client.authenticate()

        assert result is False

    def test_authenticate_token_invalid_base64_payload(self):
        client = CiscoClientSDWAN(
            username="",
            password="",
            base_url="https://sdwan.example.com",
            max_retries=3,
            retry_after=1,
            timeout=5,
            ssl_verify=False,
            api_token="header.!!!invalid-base64!!!.signature",
        )

        result = client.authenticate()

        assert result is False


class TestTokenAuthServerErrors:
    """Test: valid JWT but server rejects the token."""

    def test_authenticate_token_server_returns_401(self, sdwan_client_with_token):
        mock_response = Mock()
        mock_response.status_code = 401

        with patch.object(httpx.Client, "get", return_value=mock_response):
            result = sdwan_client_with_token.authenticate()

        assert result is False

    def test_authenticate_token_request_error(self, sdwan_client_with_token):
        with patch.object(
            httpx.Client, "get", side_effect=httpx.RequestError("Connection refused")
        ):
            result = sdwan_client_with_token.authenticate()

        assert result is False


class TestDefaultApiToken:
    """Test: api_token defaults to empty string."""

    def test_api_token_defaults_to_empty_string(self):
        client = CiscoClientSDWAN(
            username="admin",
            password="pass",
            base_url="https://sdwan.example.com",
            max_retries=3,
            retry_after=1,
            timeout=5,
            ssl_verify=False,
        )
        assert client.api_token == ""
