import json
import logging
import signal
import sys
from logging.handlers import MemoryHandler, RotatingFileHandler
from pathlib import Path
from threading import Event
from types import FrameType
from typing import Any, cast

from .monitors import (
    all_collectors,
    collect_top_consumers,
    cpu_collector,
    memory_collector,
    thermal_collector,
)

LOG_FILE_LOGGER = "LOG_FILE_LOGGER"
LOG_FILE = Path("~/.pulsar/metrics.jsonl").expanduser()
LOG_FILES_MAX_SIZE = 5 * 1024 * 1024
MAX_LOG_FILE_COUNT = 30
INCIDENT_FILE_LOGGER = "INCIDENT_FILE_LOGGER"
INCIDENT_LOG_FILE = Path("~/.pulsar/incident_logs.jsonl").expanduser()
INTERVAL: float = 5
MEMORY_BUFFER_CAPACITY = 3
FLUSH_LEVEL = logging.ERROR
MINIMUM_INCIDENT_DURATIONS = {
    cpu_collector.name(): 5,
    memory_collector.name(): 5,
    thermal_collector.name(): 5,
}

metric_states = {"NORMAL": "NORMAL", "WARNING": "WARNING"}

# Track consecutive ticks above threshold
incident_state: dict[str, dict[str, Any]] = {
    cpu_collector.name(): {"current_state": metric_states["NORMAL"], "duration": 0.0},
    memory_collector.name(): {
        "current_state": metric_states["NORMAL"],
        "duration": 0.0,
    },
    thermal_collector.name(): {
        "current_state": metric_states["NORMAL"],
        "duration": 0.0,
    },
}


def evaluate_incidents(
    shutdown_event: Event,
    incident_logger: logging.Logger,
    metrics_data: dict[str, float],
    thresholds: dict[str, float],
    interval: float,
    top_consumer_list_count: int = 3,
):
    for metric_name, threshold in (
        thresholds | {thermal_collector.name(): thermal_collector.threshold}
    ).items():
        if metric_name not in metrics_data:
            continue

        current_value = metrics_data[metric_name]

        if not (current_value and (metric_name in incident_state)):
            continue

        if (
            (current_value >= threshold)
            and (
                incident_state[metric_name]["current_state"] != metric_states["WARNING"]
            )
        ) or (
            (current_value < threshold)
            and (
                incident_state[metric_name]["current_state"] != metric_states["NORMAL"]
            )
        ):
            incident_state[metric_name]["duration"] += interval

            if (
                incident_state[metric_name]["duration"]
                >= MINIMUM_INCIDENT_DURATIONS[metric_name]
            ):
                # Trigger the incident log
                incident_state[metric_name]["current_state"] = (
                    metric_states["WARNING"]
                    if current_value >= threshold
                    else (metric_states["NORMAL"])
                )

                top_consuming_processes = (
                    collect_top_consumers(
                        shutdown_event, metric_name, interval, top_consumer_list_count
                    )
                    if current_value >= threshold
                    else "N/A"
                )

                incident_logger.warning(
                    {
                        "triggered_metric": metric_name,
                        "new_status": incident_state[metric_name]["current_state"],
                        "breached_value": current_value,
                        "threshold_limit": threshold,
                        "top_processes": top_consuming_processes,
                    }
                )
                # Reset the counter so it doesn't log every single tick
                # while it remains above the threshold
                incident_state[metric_name]["duration"] = 0.0

        else:
            # If the metric drops back to normal, clear the duration counter
            incident_state[metric_name]["duration"] = 0.0


time_since_last_log = INTERVAL


class JSONLogFormatter(logging.Formatter):
    """Custom formatter to force the logging module to output strict JSON."""

    def __init__(self):
        super().__init__()
        # Define your mapping table (e.g., replace '°' with ' deg')
        self.replacement_map = str.maketrans({"°": " deg"})

    def format(self, record: logging.LogRecord) -> str:
        # The payload is passed via the 'msg' parameter when logging
        raw_payload: dict[str, Any] = cast(dict[str, Any], record.msg)

        payload = dict(raw_payload)

        payload["timestamp"] = self.formatTime(record, self.datefmt)
        return json.dumps(payload)


def setup_metric_logger(logger_name: str, file_path: Path) -> logging.Logger:
    file_path.parent.mkdir(parents=True, exist_ok=True)

    # 5 MB per file, max 3 historical backups (20 MB total footprint)
    file_handler = RotatingFileHandler(
        file_path, maxBytes=LOG_FILES_MAX_SIZE, backupCount=MAX_LOG_FILE_COUNT
    )
    file_handler.setFormatter(JSONLogFormatter())

    buffer_handler = MemoryHandler(
        capacity=MEMORY_BUFFER_CAPACITY, flushLevel=FLUSH_LEVEL, target=file_handler
    )

    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.addHandler(buffer_handler)

    # Prevent metrics from bubbling up to standard stdout
    logger.propagate = False
    return logger


shutdown_event = Event()


def graceful_shutdown(signum: int, frame: FrameType | None) -> None:
    """
    Called asynchronously by the Python signal handler.
    signum: The integer identifying the signal (e.g., 15 for SIGTERM).
    frame: The current execution stack frame when the signal arrived.
    """
    # Flips the event flag to True, instantly breaking any active .wait()
    shutdown_event.set()


def start_logging(
    interval: float = 5.0,
    threshold_cpu: float = 80.0,
    threshold_ram: float = 80.0,
    top_consumer_list_count: int = 3,
):
    """The hidden loop executed by the detached process."""

    # SIGTERM (15) is sent by `pulsar daemon stop`.
    # SIGINT (2) handles Ctrl+C if someone runs this attached for debugging.
    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)

    metric_logger = setup_metric_logger(LOG_FILE_LOGGER, LOG_FILE)
    incident_logger = setup_metric_logger(INCIDENT_FILE_LOGGER, INCIDENT_LOG_FILE)

    for collector in all_collectors:
        collector.prime()

    shutdown_event.wait(interval)

    while not shutdown_event.is_set():
        metric_info: dict[str, float] = {}
        log_record: dict[str, Any] = {}
        for collector in all_collectors:
            metric_info[collector.name()] = collector.collect_value()

            log_record[f"{collector.name()} {collector.unit()}"] = metric_info[
                collector.name()
            ]

        metric_logger.info(log_record)

        evaluate_incidents(
            shutdown_event,
            incident_logger,
            metric_info,
            {
                f"{cpu_collector.name()}": threshold_cpu,
                f"{memory_collector.name()}": threshold_ram,
            },
            interval,
            top_consumer_list_count,
        )

        # wait() blocks for 5 seconds OR until shutdown_event.set() is called.
        shutdown_event.wait(interval)

    # 2. Cleanup block
    # When shutdown_event is set, the loop exits here.
    # flush buffered writers or close database connections.
    sys.exit(0)
