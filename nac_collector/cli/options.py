import click
from nac_collector.constants import TIMEOUT

solution = click.option(
    "--solution",
    "-s",
    type=click.Choice(
        ["SDWAN", "ISE", "NDO", "FMC", "CATALYSTCENTER", "MERAKI"], case_sensitive=False
    ),
    required=True,
    help="Solutions supported [SDWAN, ISE, NDO, FMC, CATALYSTCENTER, MERAKI]",
)

username = click.option(
    "--username",
    "-u",
    type=str,
    required=True,
    envvar="NAC_USERNAME",
    help="Username for authentication. Can also be set using the NAC_USERNAME environment variable",
)

password = click.option(
    "--password",
    "-p",
    type=str,
    required=True,
    envvar="NAC_PASSWORD",
    help="Password for authentication. Can also be set using the NAC_PASSWORD environment variable",
)

api_key = click.option(
    "--api-key",
    "-k",
    type=str,
    required=True,
    envvar="NAC_API_KEY",
    help="API key for authentication. Can also be set using the NAC_API_KEY environment variable",
)

url = click.option(
    "--url",
    "-url",
    type=str,
    required=True,
    envvar="NAC_URL",
    help="Base URL for the service. Can also be set using the NAC_URL environment variable",
)

git_provider = click.option(
    "--git-provider",
    "-g",
    is_flag=True,
    help="Generate endpoint.yaml automatically using provider github repo",
)

endpoints_file = click.option(
    "--endpoints-file",
    "-e",
    type=str,
    default=None,
    help="Path to the endpoints YAML file",
)

output = click.option(
    "--output", "-o", type=str, default=None, help="Path to the output json file"
)

timeout = click.option(
    "--timeout",
    "-t",
    type=int,
    help=f"Request timeout in seconds. Default is {TIMEOUT}.",
    default=TIMEOUT,
)
