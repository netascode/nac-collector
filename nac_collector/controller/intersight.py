import base64
import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import Any, Generator
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from nac_collector.cli import console
from nac_collector.controller.base import CiscoClientController

logger = logging.getLogger("main")

_PAGE_SIZE = 500


class _IntersightAuth(httpx.Auth):
    """httpx.Auth implementation for Intersight HTTP Signature authentication."""

    def __init__(self, api_key_id: str, private_key: Any) -> None:
        self._key_id = api_key_id
        self._key = private_key

    def auth_flow(
        self, request: httpx.Request
    ) -> Generator[httpx.Request, httpx.Response, None]:
        body = request.content or b""
        digest = base64.b64encode(hashlib.sha256(body).digest()).decode()
        date = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        parsed = urlparse(str(request.url))
        host = parsed.netloc
        path = parsed.path
        if parsed.query:
            path = f"{path}?{parsed.query}"

        signing_string = (
            f"(request-target): {request.method.lower()} {path}\n"
            f"date: {date}\n"
            f"host: {host}\n"
            f"digest: SHA-256={digest}"
        )

        if isinstance(self._key, ec.EllipticCurvePrivateKey):
            sig_bytes = self._key.sign(
                signing_string.encode(), ec.ECDSA(hashes.SHA256())
            )
        else:
            sig_bytes = self._key.sign(
                signing_string.encode(), padding.PKCS1v15(), hashes.SHA256()
            )

        sig_b64 = base64.b64encode(sig_bytes).decode()
        request.headers["Date"] = date
        request.headers["Host"] = host
        request.headers["Digest"] = f"SHA-256={digest}"
        request.headers["Authorization"] = (
            f'Signature keyId="{self._key_id}",'
            f'algorithm="hs2019",'
            f'headers="(request-target) date host digest",'
            f'signature="{sig_b64}"'
        )
        yield request


def _load_private_key(secret_key: str) -> Any:
    """
    Load a private key from a file path or a PEM string (with literal \\n escapes).
    Handles both RSA and EC keys in PKCS#1 or PKCS#8 DER encoding.
    """
    import os

    if os.path.isfile(secret_key):
        with open(secret_key, "rb") as f:
            key_data = f.read()
    else:
        key_data = secret_key.replace("\\n", "\n").encode()

    lines = [
        line
        for line in key_data.decode().splitlines()
        if not line.startswith("-----")
    ]
    der = base64.b64decode("".join(lines))
    return serialization.load_der_private_key(der, password=None)


class CiscoClientINTERSIGHT(CiscoClientController):
    """
    Collector for the Cisco Intersight SaaS platform.

    Authentication uses HTTP Signature (hs2019) with an API key ID and RSA/EC private key —
    no username/password required. The signing logic is implemented inline without additional
    dependencies beyond `cryptography` (already a transitive dep).
    """

    SOLUTION = "intersight"
    DEFAULT_BASE_URL = "https://intersight.com"

    def __init__(
        self,
        api_key_id: str,
        secret_key: str,
        base_url: str,
        max_retries: int,
        retry_after: int,
        timeout: int,
        ssl_verify: bool = True,
    ) -> None:
        # Pass empty strings for username/password — Intersight does not use them.
        super().__init__(
            username="",
            password="",
            base_url=base_url or self.DEFAULT_BASE_URL,
            max_retries=max_retries,
            retry_after=retry_after,
            timeout=timeout,
            ssl_verify=ssl_verify,
        )
        self.api_key_id = api_key_id
        self.secret_key = secret_key

    def authenticate(self) -> bool:
        try:
            private_key = _load_private_key(self.secret_key)
        except Exception as e:
            logger.error("Failed to load Intersight private key: %s", e)
            return False

        auth = _IntersightAuth(self.api_key_id, private_key)
        self.client = httpx.Client(
            auth=auth,
            verify=self.ssl_verify,
            timeout=self.timeout,
            headers={"Content-Type": "application/json"},
        )
        logger.info("Intersight client initialised with HTTP Signature auth.")
        return True

    def _fetch_all_pages(self, endpoint: str) -> list[Any]:
        """
        Fetch all pages from an Intersight endpoint using $top/$skip pagination.
        Intersight responses have the shape: {"Results": [...], "Count": N}.
        """
        skip = 0
        all_results: list[Any] = []

        while True:
            sep = "&" if "?" in endpoint else "?"
            full_url = f"{self.base_url}{endpoint}{sep}$top={_PAGE_SIZE}&$skip={skip}"
            response = self._get_full_url(full_url)
            if response is None:
                logger.debug("No response for %s — stopping pagination.", full_url)
                break

            try:
                data = response.json()
            except ValueError:
                logger.error("Failed to decode JSON from %s", full_url)
                break

            results = data.get("Results") or []
            if not isinstance(results, list):
                results = []

            all_results.extend(results)

            if len(results) < _PAGE_SIZE:
                break

            skip += _PAGE_SIZE

        return all_results

    def _get_full_url(self, full_url: str) -> httpx.Response | None:
        """GET a fully-qualified URL directly (bypasses base_url prepend)."""
        response = None

        for _ in range(self.max_retries):
            try:
                if self.client is None:
                    logger.error("Client not initialised")
                    return None
                response = self.client.get(full_url)
            except httpx.TimeoutException:
                logger.error("GET %s timed out.", full_url)
                continue
            except httpx.TransportError as e:
                logger.error("GET %s transport error: %s", full_url, e)
                time.sleep(self.retry_after)
                continue

            if response.status_code == 429:
                wait = int(response.headers.get("Retry-After", self.retry_after))
                logger.info("Rate limited. Retrying in %s s.", wait)
                time.sleep(wait)
            elif response.status_code == 401:
                logger.info("Token outdated — re-authenticating.")
                self.authenticate()
            elif response.status_code == 200:
                return response
            elif response.status_code == 404:
                logger.debug(
                    "GET %s returned 404 — resource not available.", full_url
                )
                return None
            else:
                logger.error(
                    "GET %s returned unexpected status: %s",
                    full_url,
                    response.status_code,
                )
                return None

        return response

    def get_from_endpoints_data(
        self, endpoints_data: list[dict[str, Any]]
    ) -> dict[str, Any]:
        final_dict: dict[str, Any] = {}

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            MofNCompleteColumn(),
            "Time elapsed:",
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                "Fetching Intersight endpoints:", total=len(endpoints_data)
            )

            for ep in endpoints_data:
                name: str = ep["name"]
                endpoint: str = ep["endpoint"]

                # Build filter query string if specified in the endpoint definition
                query_filter: str = ep.get("filter", "")
                url_path = endpoint
                if query_filter:
                    sep = "&" if "?" in endpoint else "?"
                    url_path = f"{endpoint}{sep}$filter={query_filter}"

                results = self._fetch_all_pages(url_path)
                final_dict[name] = results
                logger.info("Fetched %d items for %s", len(results), name)
                progress.advance(task)

        return final_dict
