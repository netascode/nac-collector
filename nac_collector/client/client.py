from nac_collector.constants import (
    MAX_RETRIES,
    RETRY_AFTER,
    TIMEOUT,
)

from .base import CiscoClient
from .ise import CiscoClientISE
from .ndo import CiscoClientNDO
from .sdwan import CiscoClientSDWAN

def make_client(
        solution: str,
        username: str, password: str,
        url: str,
        *,
        max_retries: int = MAX_RETRIES,
        retry_after: int = RETRY_AFTER,
        timeout: int = TIMEOUT) -> CiscoClient:
    """
    Create a client suitable for the provided parameter.

    Args:
        solution (str): The solution for which the client is being created.
        username (str): The username for the client authentication.
        password (str): The password for the client authentication.
        url (str): The base URL for the client.
        max_retries (int): The maximum number of retries allowed for requests.
        retry_after (int): The retry duration in seconds after a failed request.
        timeout (int): The timeout duration for requests in seconds.

    Returns:
        CiscoClient: The created client.

    Raises:
        LookupError: If the provided solution is unknown.
    """
    if solution == "SDWAN":
        client = CiscoClientSDWAN(
            username=username,
            password=password,
            base_url=url,
            max_retries=max_retries,
            retry_after=retry_after,
            timeout=timeout,
            ssl_verify=False,
        )

    elif solution == "ISE":
        client = CiscoClientISE(
            username=username,
            password=password,
            base_url=url,
            max_retries=max_retries,
            retry_after=retry_after,
            timeout=timeout,
            ssl_verify=False,
        )
    elif solution == "NDO":
        client = CiscoClientNDO(
            username=username,
            password=password,
            base_url=url,
            max_retries=max_retries,
            retry_after=retry_after,
            timeout=timeout,
            ssl_verify=False,
        )
    else:
        raise LookupError(f"Unknown solution '{solution}'")

    return client
