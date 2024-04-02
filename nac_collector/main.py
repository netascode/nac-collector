import click
import logging
import time

from nac_collector.cisco_api_wrapper import CiscoClient
from nac_collector.github_repo_wrapper import GithubRepoWrapper
from nac_collector.constants import (
    AUTH_TYPE_MAPPING,
    AUTH_ENDPOINT_MAPPING,
    SOLUTION_ENDPOINTS,
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
    help="Username for authentication",
)
@click.option(
    "--password",
    "-p",
    type=str,
    required=True,
    help="Password for authentication",
)
@click.option(
    "--url",
    "-url",
    type=str,
    required=True,
    help="Base URL for the service",
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

    auth_type = AUTH_TYPE_MAPPING.get(solution)

    client = CiscoClient(
        username=username,
        password=password,
        base_url=url,
        auth_type=auth_type,
        ssl_verify=False,
        solution=solution.lower(),
    )

    solution_auth_endpoints = SOLUTION_ENDPOINTS.get(solution, [])
    for endpoint in solution_auth_endpoints:
        auth_endpoint = AUTH_ENDPOINT_MAPPING.get(endpoint)
        client.authenticate(auth_endpoint=auth_endpoint)

    endpoints_yaml_file = f"endpoints_{solution.lower()}.yaml"
    client.get_from_endpoints(endpoints_yaml_file, MAX_RETRIES, RETRY_AFTER, TIMEOUT)

    # Record the stop time
    stop_time = time.time()

    # Calculate the total execution time
    total_time = stop_time - start_time
    print(f"Total execution time: {total_time:.2f} seconds")


if __name__ == "__main__":
    cli()
