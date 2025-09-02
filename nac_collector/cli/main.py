import logging
import sys
import time
import click
import errorhandler

import nac_collector
from nac_collector.cisco_client_fmc import CiscoClientFMC
from nac_collector.cisco_client_ise import CiscoClientISE
from nac_collector.cisco_client_catalystcenter import CiscoClientCATALYSTCENTER
from nac_collector.cisco_client_ndo import CiscoClientNDO
from nac_collector.cisco_client_ndfc import CiscoClientNDFC
from nac_collector.cisco_client_sdwan import CiscoClientSDWAN
from nac_collector.constants import GIT_TMP, MAX_RETRIES, RETRY_AFTER
from nac_collector.github_repo_wrapper import GithubRepoWrapper

from . import options

logger = logging.getLogger("main")

error_handler = errorhandler.ErrorHandler()


class ColoredFormatter(logging.Formatter):
    """Custom formatter to add colors to different log levels"""

    # ANSI color codes
    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Orange/Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
        "RESET": "\033[0m",  # Reset to default
    }

    def format(self, record):
        # Get the original formatted message
        original_format = super().format(record)

        # Add color to the levelname in the message
        levelname = record.levelname
        if levelname in self.COLORS:
            # Replace the levelname with colored version
            colored_levelname = (
                f"{self.COLORS[levelname]}{levelname}{self.COLORS['RESET']}"
            )
            # Replace levelname in the formatted message
            colored_format = original_format.replace(levelname, colored_levelname, 1)
            return colored_format

        return original_format


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

    # Use ColoredFormatter for colored output, but only if output is a terminal
    if sys.stdout.isatty():
        formatter = ColoredFormatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
    else:
        # Use plain formatter for non-terminal output (e.g., piped to file)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

    handler.setFormatter(formatter)
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
@options.output_dir
@options.endpoints
@options.no_ssl_verify
@options.domain
@options.fabric_name
def main(
    verbosity,
    solution,
    username,
    password,
    url,
    git_provider,
    endpoints_file,
    timeout,
    output,
    output_dir,
    endpoints,
    no_ssl_verify,
    domain,
    fabric_name,
):
    """A CLI tool to collect various network configurations."""

    # Record the start time
    start_time = time.time()

    configure_logging(verbosity)

    # Check for incompatible option combinations
    if git_provider and solution in ["NDO", "NDFC"]:
        logger.error(
            "--git-provider option is not supported with %s solution. This solution uses a different repository structure that is incompatible with the git provider functionality.",
            solution,
        )
        sys.exit(1)

    if git_provider:
        wrapper = GithubRepoWrapper(
            repo_url=f"https://github.com/CiscoDevNet/terraform-provider-{solution.lower()}.git",
            clone_dir=GIT_TMP,
            solution=solution.lower(),
        )
        wrapper.get_definitions()

    endpoints_yaml_file = endpoints_file or f"endpoints_{solution.lower()}.yaml"
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
    elif solution == "NDFC":
        cisco_client = CiscoClientNDFC

    if cisco_client:
        # Create client with appropriate parameters based on solution type
        if solution == "NDFC":
            client = cisco_client(
                username=username,
                password=password,
                base_url=url,
                max_retries=MAX_RETRIES,
                retry_after=RETRY_AFTER,
                timeout=timeout,
                ssl_verify=False,
                domain=domain,
                fabric_name=fabric_name,
            )
        else:
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
            logger.error("Authentication failed. Exiting...")
            return

        final_dict = client.get_from_endpoints(endpoints_yaml_file)
        client.write_to_json(final_dict, output_file)

    # Record the stop time
    stop_time = time.time()

    # Calculate the total execution time
    total_time = stop_time - start_time
    logger.info(f"Total execution time: {total_time:.2f} seconds")

    exit()


def exit() -> None:
    if error_handler.fired:
        sys.exit(1)
    else:
        sys.exit(0)
