import logging
import time
from enum import Enum
from typing import Annotated

import typer
from rich.console import Console
from rich.logging import RichHandler

import nac_collector
from nac_collector.constants import MAX_RETRIES, RETRY_AFTER, TIMEOUT
from nac_collector.controller.base import CiscoClientController
from nac_collector.controller.catalystcenter import CiscoClientCATALYSTCENTER
from nac_collector.controller.fmc import CiscoClientFMC
from nac_collector.controller.ise import CiscoClientISE
from nac_collector.controller.meraki import CiscoClientMERAKI
from nac_collector.controller.ndo import CiscoClientNDO
from nac_collector.controller.sdwan import CiscoClientSDWAN
from nac_collector.device.iosxe import CiscoClientIOSXE
from nac_collector.device.iosxr import CiscoClientIOSXR
from nac_collector.device.nxos import CiscoClientNXOS
from nac_collector.device_inventory import load_devices_from_file
from nac_collector.endpoint_resolver import EndpointResolver

console = Console()
logger = logging.getLogger("main")
error_occurred = False


class LogLevel(str, Enum):
    """Supported log levels."""

    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    DEBUG = "DEBUG"


class ErrorTrackingHandler(logging.Handler):
    """Custom handler to track if errors occurred."""

    def emit(self, record: logging.LogRecord) -> None:
        """Set error flag if error or critical log is emitted."""
        global error_occurred
        if record.levelno >= logging.ERROR:
            error_occurred = True


class Solution(str, Enum):
    """Supported solutions."""

    SDWAN = "SDWAN"
    ISE = "ISE"
    NDO = "NDO"
    FMC = "FMC"
    CATALYSTCENTER = "CATALYSTCENTER"
    MERAKI = "MERAKI"
    IOSXE = "IOSXE"
    IOSXR = "IOSXR"
    NXOS = "NXOS"


def configure_logging(level: LogLevel) -> None:
    """Configure logging with Rich handler."""
    global error_occurred
    error_occurred = False  # Reset error flag

    level_map = {
        LogLevel.DEBUG: logging.DEBUG,
        LogLevel.INFO: logging.INFO,
        LogLevel.WARNING: logging.WARNING,
        LogLevel.ERROR: logging.ERROR,
        LogLevel.CRITICAL: logging.CRITICAL,
    }

    root_logger = logging.getLogger()
    # Clear existing handlers
    root_logger.handlers.clear()

    # Add Rich handler
    handler = RichHandler(console=console, show_time=True, show_path=False)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger.addHandler(handler)

    # Add error tracking handler
    error_tracker = ErrorTrackingHandler()
    error_tracker.setLevel(logging.ERROR)
    root_logger.addHandler(error_tracker)

    root_logger.setLevel(level_map[level])


def version_callback(value: bool) -> None:
    """Show version and exit."""
    if value:
        console.print(f"nac-collector version: {nac_collector.__version__}")
        raise typer.Exit()


def main(
    solution: Annotated[
        Solution,
        typer.Option(
            "-s",
            "--solution",
            help="Choose a solution",
        ),
    ],
    username: Annotated[
        str | None,
        typer.Option(
            "-u",
            "--username",
            envvar="NAC_USERNAME",
            help="Username for authentication",
        ),
    ] = None,
    password: Annotated[
        str | None,
        typer.Option(
            "-p",
            "--password",
            envvar="NAC_PASSWORD",
            help="Password for authentication",
        ),
    ] = None,
    url: Annotated[
        str | None,
        typer.Option(
            "--url",
            envvar="NAC_URL",
            help="Base URL for the service",
        ),
    ] = None,
    verbosity: Annotated[
        LogLevel,
        typer.Option("-v", "--verbosity", help="Log level"),
    ] = LogLevel.WARNING,
    fetch_latest: Annotated[
        bool,
        typer.Option(
            "-f",
            "--fetch-latest",
            help="Fetch the latest endpoint definitions from upstream sources",
        ),
    ] = False,
    endpoints_file: Annotated[
        str | None,
        typer.Option("-e", "--endpoints-file", help="Path to the endpoints YAML file"),
    ] = None,
    timeout: Annotated[
        int,
        typer.Option("-t", "--timeout", help="Request timeout in seconds"),
    ] = TIMEOUT,
    output: Annotated[
        str | None,
        typer.Option("-o", "--output", help="Path to the output ZIP archive"),
    ] = None,
    devices_file: Annotated[
        str | None,
        typer.Option(
            "-d",
            "--devices-file",
            help="Path to devices inventory YAML file (for device-based solutions)",
        ),
    ] = None,
    version: Annotated[
        bool | None,
        typer.Option(
            "--version", callback=version_callback, help="Show version and exit"
        ),
    ] = None,
) -> None:
    """A CLI tool to collect various network configurations."""

    # Record the start time
    start_time = time.time()

    configure_logging(verbosity)

    # Define device-based solutions
    DEVICE_BASED_SOLUTIONS = [Solution.IOSXE, Solution.IOSXR, Solution.NXOS]

    # Check for incompatible option combinations
    if fetch_latest and solution == Solution.NDO:
        console.print(
            "[red]--fetch-latest option is not supported with NDO solution. The NDO solution uses a different repository structure that is incompatible with fetching from upstream.[/red]"
        )
        raise typer.Exit(1)

    output_file = output or "nac-collector.zip"

    # Handle device-based solutions
    if solution in DEVICE_BASED_SOLUTIONS:
        # Validate devices file is provided
        if not devices_file:
            console.print(
                f"[red]--devices-file is required for {solution.value} solution[/red]"
            )
            raise typer.Exit(1)

        # Load devices
        devices = load_devices_from_file(devices_file)
        if not devices:
            console.print(
                "[red]Failed to load devices from file or no devices found[/red]"
            )
            raise typer.Exit(1)

        # Device-based solutions don't need endpoints file
        if endpoints_file:
            console.print(
                f"[yellow]Warning: --endpoints-file is ignored for {solution.value} "
                f"(device-based solutions use built-in endpoints)[/yellow]"
            )

        # Create appropriate client based on solution
        if solution == Solution.IOSXE:
            iosxe_client = CiscoClientIOSXE(
                devices=devices,
                default_username=username or "",
                default_password=password or "",
                max_retries=MAX_RETRIES,
                retry_after=RETRY_AFTER,
                timeout=timeout,
                ssl_verify=False,
            )
            # Collect from all devices and write to archive
            iosxe_client.collect_and_write_to_archive(output_file)
        elif solution == Solution.IOSXR:
            iosxr_client = CiscoClientIOSXR(
                devices=devices,
                default_username=username or "",
                default_password=password or "",
                max_retries=MAX_RETRIES,
                retry_after=RETRY_AFTER,
                timeout=timeout,
                ssl_verify=False,
            )
            # Collect from all devices and write to archive
            iosxr_client.collect_and_write_to_archive(output_file)
        elif solution == Solution.NXOS:
            nxos_client = CiscoClientNXOS(
                devices=devices,
                default_username=username or "",
                default_password=password or "",
                max_retries=MAX_RETRIES,
                retry_after=RETRY_AFTER,
                timeout=timeout,
                ssl_verify=False,
            )
            # Collect from all devices and write to archive
            nxos_client.collect_and_write_to_archive(output_file)

    # Handle existing controller-based solutions
    else:
        # Resolve endpoint data using centralized resolver
        endpoints_data = EndpointResolver.resolve_endpoint_data(
            solution=solution.value.lower(),
            explicit_file=endpoints_file,
            use_git_provider=fetch_latest,
        )

        if endpoints_data is None:
            console.print(
                f"[red]No endpoint data found for solution: {solution.value}[/red]"
            )
            console.print("[yellow]Available options:[/yellow]")
            console.print("1. Use --endpoints-file to specify a custom file")
            console.print("2. Use --fetch-latest to fetch from upstream sources")
            console.print("3. Ensure packaged resources are available")
            raise typer.Exit(1)

        cisco_client_class: type[CiscoClientController] | None = None
        if solution == Solution.SDWAN:
            cisco_client_class = CiscoClientSDWAN
        elif solution == Solution.ISE:
            cisco_client_class = CiscoClientISE
        elif solution == Solution.NDO:
            cisco_client_class = CiscoClientNDO
        elif solution == Solution.FMC:
            cisco_client_class = CiscoClientFMC
        elif solution == Solution.CATALYSTCENTER:
            cisco_client_class = CiscoClientCATALYSTCENTER
        elif solution == Solution.MERAKI:
            cisco_client_class = CiscoClientMERAKI

        # Validate required credentials for controller-based solutions
        if not username:
            console.print(
                "[red]Username is required for controller-based solutions[/red]"
            )
            raise typer.Exit(1)
        if not password:
            console.print(
                "[red]Password is required for controller-based solutions[/red]"
            )
            raise typer.Exit(1)
        if not url:
            console.print("[red]URL is required for controller-based solutions[/red]")
            raise typer.Exit(1)

        if cisco_client_class:
            client = cisco_client_class(
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
                console.print("[red]Authentication failed. Exiting...[/red]")
                raise typer.Exit(1)

            # Use resolved endpoint data
            final_dict = client.get_from_endpoints_data(endpoints_data)
            client.write_to_archive(final_dict, output_file, solution.value.lower())

    # Record the stop time
    stop_time = time.time()

    # Calculate the total execution time
    total_time = stop_time - start_time
    logger.info(f"Total execution time: {total_time:.2f} seconds")

    exit_app()


def exit_app() -> None:
    """Exit the application with appropriate exit code."""
    global error_occurred
    if error_occurred:
        raise typer.Exit(1)
    else:
        raise typer.Exit(0)


def app() -> None:
    """Run the application."""
    typer.run(main)


if __name__ == "__main__":
    app()
