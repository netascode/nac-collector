"""
This module is the main entry point for the NAC Collector application.
It handles the authentication and data collection processes.
"""

import logging
import time
import click

from nac_collector.cisco_client_sdwan import CiscoClientSDWAN
from nac_collector.cisco_client_ise import CiscoClientISE
from nac_collector.github_repo_wrapper import GithubRepoWrapper
from nac_collector.constants import (
    GIT_TMP,
    MAX_RETRIES,
    RETRY_AFTER,
    TIMEOUT,
)


@click.command()
@click.option(
    "--solution",
    "-s",
    type=click.Choice(["SDWAN", "ISE"], case_sensitive=False),
    required=True,
    help="Solutions supported [SDWAN, ISE]",
)
@click.option(
    "--username",
    "-u",
    type=str,
    required=True,
    envvar="NAC_USERNAME",
    help="Username for authentication. Can also be set using the NAC_USERNAME environment variable",
)
@click.option(
    "--password",
    "-p",
    type=str,
    required=True,
    envvar="NAC_PASSWORD",
    help="Password for authentication. Can also be set using the NAC_PASSWORD environment variable",
)
@click.option(
    "--url",
    "-url",
    type=str,
    required=True,
    envvar="NAC_URL",
    help="Base URL for the service. Can also be set using the NAC_URL environment variable",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose output",
)
@click.option(
    "--git-provider",
    "-g",
    is_flag=True,
    help="Generate endpoint.yaml automatically using provider github repo",
)
def cli(
    solution: str,
    username: str,
    password: str,
    url: str,
    verbose: bool,
    git_provider: bool,
) -> None:
    """
    Command Line Interface (CLI) function for the application.

    Parameters:
        solution (str): The name of the solution to be used.
        username (str): The username for authentication.
        password (str): The password for authentication.
        url (str): The URL of the server to connect to.
        verbose (bool): If True, detailed output will be printed to the console.
        git_provider (bool): If True, the solution will be fetched from a Git provider.

    Returns:
        None
    """

    # Record the start time
    start_time = time.time()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO if verbose else logging.CRITICAL,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    if git_provider:
        wrapper = GithubRepoWrapper(
            repo_url=f"https://github.com/CiscoDevNet/terraform-provider-{solution.lower()}.git",
            clone_dir=GIT_TMP,
            solution=solution.lower(),
        )
        wrapper.get_definitions()

    if solution == "SDWAN":
        client = CiscoClientSDWAN(
            username=username,
            password=password,
            base_url=url,
            max_retries=MAX_RETRIES,
            retry_after=RETRY_AFTER,
            timeout=TIMEOUT,
            ssl_verify=False,
        )

        # Authenticate
        if not client.authenticate():
            print("Authentication failed. Exiting...")
            return

        endpoints_yaml_file = f"endpoints_{solution.lower()}.yaml"
        final_dict = client.get_from_endpoints(endpoints_yaml_file)
        client.write_to_json(final_dict, f"{solution.lower()}")

    elif solution == "ISE":
        client = CiscoClientISE(
            username=username,
            password=password,
            base_url=url,
            max_retries=MAX_RETRIES,
            retry_after=RETRY_AFTER,
            timeout=TIMEOUT,
            ssl_verify=False,
        )

        # Authenticate
        if not client.authenticate():
            print("Authentication failed. Exiting...")
            return

        endpoints_yaml_file = f"endpoints_{solution.lower()}.yaml"
        final_dict = client.get_from_endpoints(endpoints_yaml_file)
        client.write_to_json(final_dict, f"{solution.lower()}")

    else:
        pass

    # Record the stop time
    stop_time = time.time()

    # Calculate the total execution time
    total_time = stop_time - start_time
    print(f"Total execution time: {total_time:.2f} seconds")


if __name__ == "__main__":
    cli()  # pylint: disable=no-value-for-parameter
