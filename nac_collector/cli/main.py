import logging
import sys
import time
import os

import click
import errorhandler

import nac_collector
from nac_collector.cisco_client_fmc import CiscoClientFMC
from nac_collector.cisco_client_ise import CiscoClientISE
from nac_collector.cisco_client_catalystcenter import CiscoClientCATALYSTCENTER
from nac_collector.cisco_client_ndo import CiscoClientNDO
from nac_collector.cisco_client_sdwan import CiscoClientSDWAN
from nac_collector.constants import GIT_TMP, MAX_RETRIES, RETRY_AFTER
from nac_collector.github_repo_wrapper import GithubRepoWrapper

from . import options

logger = logging.getLogger(__name__)

error_handler = errorhandler.ErrorHandler()


def configure_logging(level: str) -> None:
    if level == "DEBUG":
        lev = logging.DEBUG
    elif level == "INFO":
        lev = logging.INFO
    elif level == "WARNING":
        lev = logging.WARNING
    elif level == "ERROR":
        lev = logging.ERROR
    else:
        lev = logging.CRITICAL
    logger = logging.getLogger()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(handler)
    logger.setLevel(lev)
    error_handler.reset()


@click.command(context_settings=dict(help_option_names=["-h", "--help"]))
@click.version_option(nac_collector.__version__)
@click.option(
    "-v",
    "--verbosity",
    metavar="LVL",
    is_eager=True,
    type=click.Choice(["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"]),
    help="Either CRITICAL, ERROR, WARNING, INFO or DEBUG",
    default="WARNING",
)
@options.solution
@options.username
@options.password
@options.url
@options.git_provider
@options.endpoints_file
@options.timeout
@options.output
def main(
    verbosity: str,
    solution: str,
    username: str,
    password: str,
    url: str,
    git_provider: bool,
    endpoints_file: str,
    timeout: int,
    output: str,
) -> None:
    """A CLI tool to collect various network configurations."""

    # Record the start time
    start_time = time.time()

    configure_logging(verbosity)

    if git_provider:
        wrapper = GithubRepoWrapper(
            repo_url=f"https://github.com/CiscoDevNet/terraform-provider-{solution.lower()}.git",
            clone_dir=GIT_TMP,
            solution=solution.lower(),
        )
        wrapper.get_definitions()
    
    basefile = f"endpoints_{solution.lower()}.yaml"
    if not os.path.isfile(basefile):
        basefile = os.path.join("endpoints", basefile) 

    endpoints_yaml_file = endpoints_file or basefile
    output_file = output or f"{solution.lower()}.json"

    if solution == "SDWAN":
        cisco_client = CiscoClientSDWAN
    elif solution == "ISE":
        cisco_client = CiscoClientISE
    elif solution == "NDO":
        cisco_client = CiscoClientNDO
    elif solution == "FMC":
        cisco_client = CiscoClientFMC
    elif solution == "CATALYSTCENTER":
        cisco_client = CiscoClientCATALYSTCENTER

    if cisco_client:
        client = cisco_client(
            username=username,
            password=password,
            base_url=url,
            max_retries=MAX_RETRIES,
            retry_after=RETRY_AFTER,
            timeout=timeout,
            ssl_verify=False,
        )

        # Authenticate
        if not client.authenticate():
            print("Authentication failed. Exiting...")
            return

        final_dict = client.get_from_endpoints(endpoints_yaml_file)
        client.write_to_json(final_dict, output_file)

    # Record the stop time
    stop_time = time.time()

    # Calculate the total execution time
    total_time = stop_time - start_time
    print(f"Total execution time: {total_time:.2f} seconds")

    exit()


if __name__ == "__main__":
    main()

def exit() -> None:
    if error_handler.fired:
        sys.exit(1)
    else:
        sys.exit(0)
