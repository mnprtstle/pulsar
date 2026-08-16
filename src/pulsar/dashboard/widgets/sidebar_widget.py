import os
import platform
import subprocess
import time
from typing import Any

import psutil
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from ..constants import (
    BAR_WIDTH,
    DISK_CAP_UPDATE_INTERVAL,
    LOAD_AVG_UPDATE_INTERVAL,
    THERMALS_UPDATE_INTERVAL,
)
from ..helpers import WidgetQueryCache
from ..themes import ActiveTheme, active_theme

Partition = tuple[str, int, float]  # mountpoint, total bytes, percent used

DISK_CAP_PAD = 10


def get_load_style(load: float, core_count: int, theme: ActiveTheme) -> str:
    return (
        f"bold {theme.background} on {theme.error}"
        if load > (0.9 * core_count)
        else f"bold {theme.warning}"
        if load > (0.65 * core_count)
        else theme.success
    ) or ""


def build_load_avg_text(
    load1: float | None,
    load5: float | None,
    load15: float | None,
    core_count: int,
    theme: ActiveTheme,
) -> Text:
    components: list[tuple[str, str]] = []
    if load1 is None:
        components.append((" Not available on this OS\n\n", f"dim {theme.primary}"))
    else:
        components.append(
            (f" 1m  {load1:>5.2f}\n", get_load_style(load1, core_count, theme))
        )
        if load5 is not None:
            components.append(
                (f" 5m  {load5:>5.2f}\n", get_load_style(load5, core_count, theme))
            )
        if load15 is not None:
            components.append(
                (
                    f" 15m {load15:>5.2f}\n\n",
                    f"dim {get_load_style(load15, core_count, theme)}",
                )
            )

    uptime_seconds = time.time() - psutil.boot_time()
    days, rem = divmod(uptime_seconds, 86400)
    hours, minutes = divmod(rem, 3600)
    components.append(
        (f"Uptime: {int(days)}d {int(hours)}h {int(minutes // 60)}m\n", theme.accent)
    )

    out = Text()
    out.append_tokens(components)
    return out


def get_temp_style(temp: float, high: float | None, theme: ActiveTheme) -> str:
    max_temp = (0.90 * high) if high else 80
    return (
        f"bold {theme.background} on {theme.error}"
        if temp >= max_temp
        else f"bold {theme.warning}"
        if temp > (0.80 * max_temp)
        else theme.success
    ) or ""


def build_thermals_text(temps: dict[str, list[Any]] | None, theme: ActiveTheme) -> Text:
    components: list[tuple[str, str]] = []
    if temps is None:
        components.append((" Sensors not supported.", f"dim {theme.error}"))
    elif not temps:
        components.append((" No sensor data found.", f"dim {theme.primary}"))
    else:
        for name, entries in temps.items():
            for entry in entries:
                label = entry.label or name
                temp = entry.current
                high = entry.high
                components.append((f" {label[:8]:<8} ", theme.primary))
                components.append((f"{temp}°C\n", get_temp_style(temp, high, theme)))

    out = Text()
    out.append_tokens(components)
    return out


def build_disk_cap_text(
    partitions: list[Partition], bar_width: int, theme: ActiveTheme
) -> Text:
    components: list[tuple[str, str]] = []
    for mp, total, percent in partitions:
        total_gib_str = f"({(total / (1024**3)):.2f} GiB)"
        w_used = round((percent / 100.0) * bar_width)
        bar = "▄" * w_used + " " * (bar_width - w_used)

        components.append((f"\n   {mp[:5].ljust(5)}   ", theme.primary))
        components.append((f"{total_gib_str:>12}\n▕", f"dim {theme.primary}"))

        color = (
            theme.error
            if percent > 85
            else theme.warning
            if percent > 60
            else theme.success
        )
        components.append((bar, color))
        components.append((f"▏ {percent:>4.1f}%\n", f"dim {theme.primary}"))

    out = Text()
    out.append_tokens(components)
    return out


def format_bytes(bytes_val: float) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_val < 1024.0:
            return f"{bytes_val:>5.1f} {unit}/s"
        bytes_val /= 1024.0
    return f"{bytes_val:>5.1f} TB/s"


def get_log_blocks(bytes_per_sec: float, base_rate: float) -> str:
    if bytes_per_sec < base_rate:
        active = 0
    elif bytes_per_sec < (base_rate * 10):
        active = 1
    elif bytes_per_sec < (base_rate * 100):
        active = 2
    elif bytes_per_sec < (base_rate * 1_000):
        active = 3
    elif bytes_per_sec < (base_rate * 10_000):
        active = 4
    elif bytes_per_sec < (base_rate * 100_000):
        active = 5
    else:
        active = 6
    blocks = ("▰ " * active) + ("▱ " * (6 - active))
    return blocks.strip()


def build_disk_io_text(
    read_bps: float | None, write_bps: float, theme: ActiveTheme
) -> Text:
    components: list[tuple[str, str]] = []
    if read_bps is None:
        components.append(
            ("\nDisk transfer speeds inaccessible", f"dim {theme.primary}")
        )
    else:
        components.append((" Read  [", theme.primary))
        components.append((get_log_blocks(read_bps, 10_000), theme.success or ""))
        components.append((" ]", theme.primary))
        components.append((f" {format_bytes(read_bps)}\n", theme.primary))
        components.append((" Write [", theme.primary))
        components.append((get_log_blocks(write_bps, 10_000), theme.error or ""))
        components.append((" ]", theme.primary))
        components.append((f" {format_bytes(write_bps)}\n", theme.primary))
    out = Text()
    out.append_tokens(components)
    return out


def build_net_io_text(down_bps: float, up_bps: float, theme: ActiveTheme) -> Text:
    components: list[tuple[str, str]] = [
        (" Down  [", theme.primary),
        (get_log_blocks(down_bps, 1000), theme.success or ""),
        (" ]", theme.primary),
        (f" {format_bytes(down_bps)}\n", theme.primary),
        (" Up    [", theme.primary),
        (get_log_blocks(up_bps, 1000), theme.error or ""),
        (" ]", theme.primary),
        (f" {format_bytes(up_bps)}\n", theme.primary),
    ]
    out = Text()
    out.append_tokens(components)
    return out


def get_init_system() -> str:
    try:
        return (
            subprocess.check_output(["ps", "-p", "1", "-o", "comm="]).decode().strip()
        )
    except Exception:
        return "Unknown"


def build_system_info_text() -> Text:
    components: list[tuple[str, str | None]] = [
        (f"OS    {platform.system()} {platform.release()}\n", None),
        (f"Init  {get_init_system()}\n", None),
    ]
    out = Text()
    out.append_tokens(components)
    return out


class SidebarMetricWidget(WidgetQueryCache, Static):
    body_id: str = ""

    def display_metric(self, text: Text) -> None:
        self._q(f"#{self.body_id}", Static).update(text)


class LoadAvgWidget(SidebarMetricWidget):
    body_id = "load-avg-body"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._last: tuple[float, float, float] | None = None
        self._core_count: int = 0

    def compose(self) -> ComposeResult:
        yield Static("LOAD AVERAGE", classes="widget-title")
        yield Static(id="load-avg-body")

    def on_mount(self) -> None:

        self._metric_thread.prime(
            "load_avg",
            tick=self._tick,
            apply=self.display_metric,
            interval=LOAD_AVG_UPDATE_INTERVAL,
            widget=self,
        )

    def _tick(self, redraw_only: bool = False) -> Text | None:
        if redraw_only and self._last is not None:
            load1, load5, load15 = self._last
        else:
            try:
                load1, load5, load15 = os.getloadavg()
                self._last = (load1, load5, load15)
            except AttributeError:
                load1 = load5 = load15 = None
                self._last = None

            if (not redraw_only) and ((load1, load5, load15) == self._last):
                return None

        if self._core_count:
            core_count = self._core_count
        else:
            self._core_count = psutil.cpu_count() or 1
            core_count = self._core_count

        return build_load_avg_text(load1, load5, load15, core_count, active_theme)


class ThermalsWidget(SidebarMetricWidget):
    body_id = "thermals-body"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._last: dict[str, list[Any]] | None = None
        self._supported = hasattr(psutil, "sensors_temperatures")

    def compose(self) -> ComposeResult:
        yield Static("THERMALS", classes="widget-title")
        yield Static(id="thermals-body")

    def on_mount(self) -> None:
        self._metric_thread.prime(
            "thermals",
            tick=self._tick,
            apply=self.display_metric,
            interval=THERMALS_UPDATE_INTERVAL,
            widget=self,
        )

    def _tick(self, redraw_only: bool = False) -> Text | None:
        if not self._supported:
            return build_thermals_text(None, active_theme)

        if redraw_only and self._last is not None:
            temps = self._last
        else:
            temps = psutil.sensors_temperatures()
            if (not redraw_only) and (temps == self._last):
                return None
            self._last = temps
        return build_thermals_text(temps, active_theme)


class DiskCapWidget(SidebarMetricWidget):
    body_id = "disk-cap-body"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Written only on the main thread (mount/resize), read only on
        # the background thread inside `_tick` - plain int, atomic.
        self.bar_width = BAR_WIDTH
        self._last: list[Partition] | None = None

    def compose(self) -> ComposeResult:
        yield Static("DISK CAPACITY", classes="widget-title")
        yield Static(id="disk-cap-body")

    def on_mount(self) -> None:
        self.call_after_refresh(self._initialize)

    def _initialize(self) -> None:
        self._recompute_bar_width()
        self._metric_thread.prime(
            "disk_cap",
            tick=self._tick,
            apply=self.display_metric,
            interval=DISK_CAP_UPDATE_INTERVAL,
            widget=self,
        )

    def on_resize(self) -> None:
        self.call_after_refresh(self._on_resize)

    def _on_resize(self) -> None:
        self._recompute_bar_width()
        self._metric_thread.request_repaint()

    def _recompute_bar_width(self) -> None:
        width = self.size.width
        self.bar_width = (width - DISK_CAP_PAD) if width else BAR_WIDTH

    def _tick(self, redraw_only: bool = False) -> Text | None:
        if redraw_only and self._last is not None:
            partitions = self._last
        else:
            partitions_raw = [
                p
                for p in psutil.disk_partitions(all=False)
                if p.mountpoint in ("/", "/home")
            ]

            partitions: list[Partition] = []
            for p in partitions_raw:
                try:
                    usage = psutil.disk_usage(p.mountpoint)
                except PermissionError:
                    continue
                partitions.append((p.mountpoint, usage.total, usage.percent))
            if (not redraw_only) and (partitions == self._last):
                return None
            self._last = partitions
        return build_disk_cap_text(partitions, self.bar_width, active_theme)


class DiskIOWidget(SidebarMetricWidget):
    body_id = "disk-io-body"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._prev_counters: Any = None
        self._prev_time = 0.0
        self._last: tuple[float, float] | None = None  # cached (read_bps, write_bps)

    def compose(self) -> ComposeResult:
        yield Static("DISK I/O", classes="widget-title")
        yield Static(id="disk-io-body")

    def on_mount(self) -> None:
        self._metric_thread.prime(
            "disk_io", tick=self._tick, apply=self.display_metric, widget=self
        )

    def _tick(self, redraw_only: bool = False) -> Text | None:
        if redraw_only and self._last is not None:
            read_bps, write_bps = self._last
            return build_disk_io_text(read_bps, write_bps, active_theme)

        now = time.monotonic()
        current = psutil.disk_io_counters()
        if self._prev_counters is None:
            # Priming call - establish a baseline, nothing to show yet.
            self._prev_counters = current
            self._prev_time = now
            return None

        time_delta = now - self._prev_time
        if current and time_delta > 0:
            read_bps = (
                current.read_bytes - self._prev_counters.read_bytes
            ) / time_delta
            write_bps = (
                current.write_bytes - self._prev_counters.write_bytes
            ) / time_delta
        else:
            read_bps = write_bps = 0.0

        self._prev_counters = current
        self._prev_time = now
        current_reading = (read_bps, write_bps)

        if (not redraw_only) and (self._last == current_reading):
            return None

        self._last = current_reading
        return build_disk_io_text(read_bps, write_bps, active_theme)


class NetIOWidget(SidebarMetricWidget):
    body_id = "net-io-body"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._prev_counters: Any = None
        self._prev_time = 0.0
        self._last: tuple[float, float] | None = None

    def compose(self) -> ComposeResult:
        yield Static("NETWORK I/0", classes="widget-title")
        yield Static(id="net-io-body")

    def on_mount(self) -> None:
        self._metric_thread.prime(
            "net_io", tick=self._tick, apply=self.display_metric, widget=self
        )

    def _tick(self, redraw_only: bool = False) -> Text | None:
        if redraw_only and self._last is not None:
            down_bps, up_bps = self._last
            return build_net_io_text(down_bps, up_bps, active_theme)

        now = time.monotonic()
        current = psutil.net_io_counters()
        if self._prev_counters is None:
            self._prev_counters = current
            self._prev_time = now
            return None

        time_delta = now - self._prev_time
        if time_delta > 0:
            down_bps = (
                current.bytes_recv - self._prev_counters.bytes_recv
            ) / time_delta
            up_bps = (current.bytes_sent - self._prev_counters.bytes_sent) / time_delta
        else:
            down_bps = up_bps = 0.0

        self._prev_counters = current
        self._prev_time = now
        current_reading = (down_bps, up_bps)

        if (not redraw_only) and (self._last == current_reading):
            return None

        self._last = current_reading
        return build_net_io_text(down_bps, up_bps, active_theme)


class SystemInfoWidget(SidebarMetricWidget):
    body_id = "system-info-body"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._done = False

    def compose(self) -> ComposeResult:
        yield Static("SYSTEM", classes="widget-title")
        yield Static(id="system-info-body")

    def on_mount(self) -> None:
        self._metric_thread.prime(
            "system_info", tick=self._tick, apply=self.display_metric, widget=self
        )

    def _tick(self, _: bool = False) -> Text | None:
        # Static content (OS/init system don't change at runtime) with
        if self._done:
            return None
        self._done = True
        return build_system_info_text()


class SidebarWidget(WidgetQueryCache, VerticalScroll):
    """Pure layout container- each child primes itself onto
    metric_thread independently in its own on_mount."""

    def compose(self) -> ComposeResult:
        yield SystemInfoWidget(id="system-info", classes="sidebar-widget")
        yield LoadAvgWidget(id="load-avg", classes="sidebar-widget")
        yield ThermalsWidget(id="thermals", classes="sidebar-widget")
        yield DiskCapWidget(id="disk-cap", classes="sidebar-widget")
        yield DiskIOWidget(id="disk-io", classes="sidebar-widget")
        yield NetIOWidget(id="net-io", classes="sidebar-widget")
