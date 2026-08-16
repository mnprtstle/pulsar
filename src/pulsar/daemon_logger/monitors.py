import time
from threading import Event
from typing import Protocol, TypedDict

import psutil

TOP_PROCESSES_LIMIT: int = 3
FALLBACK_THERMAL_THRESHOLD_VALUE: float = 130.0


class MetricCollector(Protocol):
    def name(self) -> str: ...
    def unit(self) -> str: ...
    def prime(self) -> None: ...
    def collect_value(self) -> float: ...
    def __str__(self) -> str: ...


class LoggingData(TypedDict):
    ram_percent: float
    ram_available_gb: float


all_collectors: list[MetricCollector] = []


class CpuCollector:
    def name(self) -> str:
        return "CPU"

    def unit(self) -> str:
        return "%"

    def prime(self) -> None:
        self.collect_value()

    def collect_value(self) -> float:
        return psutil.cpu_percent()

    def __str__(self) -> str:
        return f"<MetricCollector: {self.name()}>"


cpu_collector = CpuCollector()

all_collectors.append(cpu_collector)


class MemoryCollector:
    def name(self) -> str:
        return "Memory"

    def unit(self) -> str:
        return "%"

    def prime(self) -> None:
        pass

    def collect_value(self) -> float:
        return psutil.virtual_memory().percent

    def collect_logging_data(self) -> LoggingData:
        memory = psutil.virtual_memory()
        return {
            "ram_percent": memory.percent,
            "ram_available_gb": round(memory.available / (1024**3), 2),
        }

    def __str__(self) -> str:
        return f"<MetricCollector: {self.name()}>"


memory_collector = MemoryCollector()

all_collectors.append(memory_collector)


class DiskUsageCollector:
    def name(self) -> str:
        return "Disk"

    def unit(self) -> str:
        return "%"

    def prime(self) -> None:
        pass

    def collect_value(self) -> float:
        disk = psutil.disk_usage("/")
        return disk.percent

    def __str__(self) -> str:
        return f"<MetricCollector: {self.name()}>"


disk_usage_collector = DiskUsageCollector()

all_collectors.append(disk_usage_collector)


class NetworkIOCollector:
    def __init__(self) -> None:
        self._last_bytes = 0
        self._last_time = 0.0

    def name(self) -> str:
        return "Network I/O"

    def unit(self) -> str:
        return "MB/s"

    def prime(self) -> None:
        net = psutil.net_io_counters()
        self._last_bytes = net.bytes_sent + net.bytes_recv
        self._last_time = time.monotonic()

    def collect_value(self) -> float:
        net = psutil.net_io_counters()
        current_time = time.monotonic()

        time_delta = current_time - self._last_time
        if time_delta <= 0:
            return 0.0

        current_bytes = net.bytes_sent + net.bytes_recv
        bytes_delta = current_bytes - self._last_bytes

        self._last_bytes = current_bytes
        self._last_time = current_time

        # Convert bytes/sec to Megabytes/sec
        return round((bytes_delta / time_delta) / (1024 * 1024), 2)

    def __str__(self) -> str:
        return f"<MetricCollector: {self.name()}>"


network_io_collector = NetworkIOCollector()

all_collectors.append(network_io_collector)


class DiskIOCollector:
    def __init__(self) -> None:
        self._last_bytes = 0
        self._last_time = 0.0

    def name(self) -> str:
        return "Disk I/O"

    def unit(self) -> str:
        return "MB/s"

    def prime(self) -> None:
        disk = psutil.disk_io_counters()
        if disk:
            self._last_bytes = disk.read_bytes + disk.write_bytes
        self._last_time = time.monotonic()

    def collect_value(self) -> float:
        disk = psutil.disk_io_counters()
        if not disk:
            return 0.0  # Handles environments where disk counters are inaccessible

        current_time = time.monotonic()
        time_delta = current_time - self._last_time

        if time_delta <= 0:
            return 0.0

        current_bytes = disk.read_bytes + disk.write_bytes
        bytes_delta = current_bytes - self._last_bytes

        self._last_bytes = current_bytes
        self._last_time = current_time

        return round((bytes_delta / time_delta) / (1024 * 1024), 2)

    def __str__(self) -> str:
        return f"<MetricCollector: {self.name()}>"


disk_io_collector = DiskIOCollector()

all_collectors.append(disk_io_collector)


class ThermalCollector:
    def __init__(self) -> None:
        self._sensor_key: str | None = None
        # Cache the threshold so we don't recalculate it constantly
        self.threshold: float = FALLBACK_THERMAL_THRESHOLD_VALUE

    def name(self) -> str:
        return "CPU Temp"

    def unit(self) -> str:
        return "deg C"

    def prime(self) -> None:
        temps = psutil.sensors_temperatures()
        if not temps:
            return

        for key in ["coretemp", "k10temp", "acpitz", "cpu_thermal"]:
            if key in temps:
                self._sensor_key = key
                break

        if not self._sensor_key and temps:
            self._sensor_key = list(temps.keys())[0] or ""

        # Extract hardware's native high threshold
        sensor_entries = temps[self._sensor_key] if self._sensor_key else []
        valid_highs = [entry.high for entry in sensor_entries if entry.high is not None]
        if valid_highs:
            # Average the high thresholds (usually they are identical across cores)
            self.threshold = sum(valid_highs) / len(valid_highs)

    def collect_value(self) -> float:
        if not self._sensor_key:
            return 0.0

        temps = psutil.sensors_temperatures()
        sensor_entries = temps.get(self._sensor_key, []) if self._sensor_key else []

        if not sensor_entries:
            return 0.0

        total_temp = sum(entry.current for entry in sensor_entries)
        return round(total_temp / len(sensor_entries), 1)

    def __str__(self) -> str:
        return f"<MetricCollector: {self.name()}>"


thermal_collector = ThermalCollector()

all_collectors.append(thermal_collector)


def collect_top_consumers(
    shutdown_event: Event,
    collector_name: str = "CPU",
    interval: float = 1.0,
    consumer_count: int = 3,
) -> list[dict[str, str | float]] | None:
    for _proc in psutil.process_iter(attrs=["cpu_percent"], ad_value=None):
        pass
        # Wait a moment for CPU cycles to accumulate
    shutdown_event.wait(interval)

    if shutdown_event.is_set():
        return []

    cpu_count: int = psutil.cpu_count() or 1

    process_dicts_list: list[dict[str, str | float]] = []
    for proc in psutil.process_iter(
        attrs=["pid", "name", "cpu_percent", "memory_percent"], ad_value=None
    ):
        try:
            # Fetch the calculated percentage of cpu time per core
            # for all threads combined
            # Second call calculates the delta since the first call
            cpu_percent_by_one_core: float = proc.info.get("cpu_percent", 0.0)

            # Normalize for multi-core systems (keeps it 0-100% max)
            cpu: float = cpu_percent_by_one_core / cpu_count

            memory_percent = float(proc.info.get("memory_percent", 0.0))

            # Convert bytes to Megabytes
            process_dicts_list.append(
                {
                    "pid": proc.info.get("pid", "Unknown"),
                    "name": proc.info.get("name", "Unknown"),
                    "cpu_percent": round(cpu, 2),
                    "memory_percent": round(memory_percent, 2),
                }
            )

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    sorting_field = "memory_percent" if (collector_name == "Memory") else "cpu_percent"

    # Sort descending by CPU usage
    sorted_consumers = sorted(
        process_dicts_list,
        key=lambda x: x[sorting_field],
        reverse=True,
    )
    return sorted_consumers[:consumer_count]
