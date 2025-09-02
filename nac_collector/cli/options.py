import click
from nac_collector.constants import TIMEOUT

solution = click.option(
    "--solution",
    "-s",
    type=click.Choice(
        ["SDWAN", "ISE", "NDO", "FMC", "CATALYSTCENTER", "NDFC"], case_sensitive=False
    ),
    required=True,
    help="Solutions supported [SDWAN, ISE, NDO, FMC, CATALYSTCENTER, NDFC]",
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

domain = click.option(
    "--domain",
    "-d",
    type=str,
    default="local",
    envvar="NAC_DOMAIN",
    help="Domain for authentication (NDFC only). Default is 'local'. Can also be set using the NAC_DOMAIN environment variable",
)

fabric_name = click.option(
    "--fabric-name",
    "-f",
    type=str,
    default=None,
    envvar="NAC_FABRIC_NAME",
    help="Fabric name for NDFC operations (NDFC only). Can also be set using the NAC_FABRIC_NAME environment variable",
)

output_dir = click.option(
    "--output-dir",
    type=str,
    default=".",
    help="Output directory for generated files. Default is current directory",
)

endpoints = click.option(
    "--endpoints",
    type=str,
    default=None,
    help="Endpoints configuration",
)

no_ssl_verify = click.option(
    "--no-ssl-verify",
    is_flag=True,
    help="Disable SSL certificate verification",
)
