import os
import signal
import subprocess
import sys
from pathlib import Path
from threading import Event

import click

# from pulsar.daemon_logger.logger import start_logging
# from pulsar.dashboard.dashboard import DashboardApp
from pulsar import DashboardApp, start_logging

PID_FILE = Path("~/.pulsar/daemon.pid").expanduser()


@click.group(invoke_without_command=True)
@click.option(
    "--interval",
    type=click.FloatRange(1, 5),
    default=2.0,
    help="Dashboard refresh interval in seconds.",
)
@click.pass_context
def main(ctx: click.Context, interval: float) -> None:
    """Pulsar: a System monitoring tool"""
    # If no subcommand was passed, launch dashboard directly
    if ctx.invoked_subcommand is None:
        dashboard_app = DashboardApp(update_interval=interval)
        dashboard_app.run()


@main.group()
def daemon() -> None:
    """Manage the Pulsar background logging daemon."""


@daemon.command()
@click.option(
    "--interval",
    type=click.FloatRange(1, 30),
    default=5.0,
    help="Interval in seconds at which to take metrics",
)
@click.option(
    "--threshold-cpu",
    "threshold_cpu",  # Click can take second argument for the decorated function name,
    type=click.FloatRange(5, 100),
    default=80.0,
    hidden=True,
)
@click.option(
    "--threshold-ram",  # if second argument is absent, it will infer it from option
    type=click.FloatRange(5, 100),
    default=80.0,
    hidden=True,
)
@click.option(
    "--top-p",
    type=click.IntRange(1, 8),
    default=3,
    hidden=True,
)
def start(
    interval: float, threshold_cpu: float, threshold_ram: float, top_p: int
) -> None:
    """Start the background metrics logger."""
    if PID_FILE.exists():
        # Check if the process is actually still running
        pid = int(PID_FILE.read_text().strip())
        try:
            os.kill(pid, 0)  # Signal 0 doesn't kill, just checks access/existence
            click.echo(f"Logging daemon already running (PID: {pid}).")
            return
        except OSError:
            # Process died but didn't clean up the PID file
            PID_FILE.unlink()

    # sys.executable ensures the daemon uses the exact same virtual environment
    # The 'run-worker' command (defined below) will run another python process
    cmd = [
        sys.executable,
        "-m",
        "pulsar.cli",
        "run-worker",
        "--interval",
        str(interval),
        "--threshold_cpu",
        str(threshold_cpu),
        "--threshold_ram",
        str(threshold_ram),
        "--top_p",
        str(top_p),
    ]

    # Detach from terminal: route I/O to DEVNULL and start a new session (setsid)
    process = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(process.pid))
    click.echo(f"Daemon started securely in background (PID: {process.pid}).")


@daemon.command()
def stop() -> None:
    """Stop the background metrics logger."""
    if not PID_FILE.exists():
        click.echo("Logging daemon is not running.")
        return

    pid = int(PID_FILE.read_text().strip())
    try:
        # SIGTERM (15) asks the process to terminate gracefully
        os.kill(pid, signal.SIGTERM)
        click.echo(f"Sent SIGTERM to daemon (PID: {pid}).")
    except ProcessLookupError:
        click.echo("Logging daemon was not running.")
    finally:
        PID_FILE.unlink(missing_ok=True)


shutdown_event = Event()


@main.command()
@click.option(
    "--interval",
    type=click.FloatRange(1, 30),
    default=2.0,
    hidden=True,
)
@click.option(
    "--threshold_cpu",
    type=click.FloatRange(5, 100),
    default=80.0,
    hidden=True,
)
@click.option(
    "--threshold_ram",
    type=click.FloatRange(5, 100),
    default=80.0,
    hidden=True,
)
@click.option(
    "--top_p",
    type=click.IntRange(1, 8),
    default=3,
    hidden=True,
)
def run_worker(
    interval: float = 5.0,
    threshold_cpu: float = 80.0,
    threshold_ram: float = 80.0,
    top_p: int = 3,
) -> None:
    """call start_logging that logs metrics"""
    start_logging(
        threshold_cpu=threshold_cpu,
        threshold_ram=threshold_ram,
        interval=interval,
        top_consumer_list_count=top_p,
    )


if __name__ == "__main__":
    main()
