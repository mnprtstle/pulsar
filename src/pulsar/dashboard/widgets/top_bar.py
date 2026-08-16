from datetime import datetime
from typing import Any

import psutil
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import HorizontalGroup
from textual.widgets import Label, Static

from ..constants import BAT_INTERVAL
from ..helpers import WidgetQueryCache
from ..progress_bar import BarInfo, create_progress_bar, update_progress_bar
from ..themes import active_theme

# TopBar.battery tick result: (bar_text or None, stat_str)
BatteryReading = tuple[Text | None, str]


class TopBar(WidgetQueryCache, HorizontalGroup):
    """Custom header that manages its own time and battery state"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.bar_info: BarInfo | None = None
        # Cache read/written entirely on the background thread's side
        self._last_percent: int | None = None
        self._last_stat_str = ""

    def compose(self) -> ComposeResult:
        yield Label(id="time-label")
        yield Label("BAT ", id="bat-label")
        yield Label(id="bat-bar")
        yield Label(id="bat-stat")
        yield Label(id="update-int")

    def on_mount(self) -> None:
        self.rebuild_theme_colors()
        self.update_time()
        self.update_int_disp()
        self.current_timer = self.set_interval(1.0, self.update_time)
        self._metric_thread.prime(
            "battery",
            tick=self._tick,
            apply=self._apply,
            interval=BAT_INTERVAL,
            widget=self,
        )

    def rebuild_theme_colors(self) -> None:
        self.bar_info = create_progress_bar(
            width=20,
            gradient_colors=[
                active_theme.error,
                active_theme.warning,
                active_theme.success,
            ],
        )
        self.update_int_disp()

    def update_time(self) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self._q("#time-label", Static).update(now)

    def update_int_disp(self) -> None:
        out = Text()
        components: list[tuple[str, str]] = [
            (" - ", f"bold {active_theme.accent}"),
        ]
        components.append(
            (
                f"({(self._update_interval * 1000):>4.0f}ms)",
                f"dim {active_theme.primary}",
            )
        )
        components.append((" + ", f"bold {active_theme.accent}"))
        out.append_tokens(components)
        self._q("#update-int", Label).update(out)

    def _tick(self, redraw_only: bool = False) -> BatteryReading | None:
        if self.bar_info is None:
            return None

        if redraw_only and self._last_percent is not None:
            bar_text = update_progress_bar(
                percentage=self._last_percent,
                bar_info=self.bar_info,
                unfilled_color=active_theme.panel,
            )
            return (bar_text, self._last_stat_str)

        batt = psutil.sensors_battery()
        if not batt:
            bat_stat_str = "🔋 Desktop / No Battery"
            changed = bat_stat_str != self._last_stat_str
            self._last_stat_str = bat_stat_str
            return (None, bat_stat_str) if changed else None

        percent = round(batt.percent)
        if batt.power_plugged:
            bat_stat_str = " (AC)"
        else:
            mins, _ = divmod(batt.secsleft, 60)
            hours, mins = divmod(mins, 60)
            bat_stat_str = f" ({hours}h {mins}m left)"

        percent_changed = percent != self._last_percent
        stat_changed = bat_stat_str != self._last_stat_str
        if not percent_changed and not stat_changed:
            return None

        self._last_percent = percent
        self._last_stat_str = bat_stat_str
        bar_text = (
            update_progress_bar(
                percentage=percent,
                bar_info=self.bar_info,
                unfilled_color=active_theme.panel,
            )
            if percent_changed
            else None
        )
        return (bar_text, bat_stat_str)

    def _apply(self, reading: BatteryReading) -> None:
        bar_text, stat_str = reading
        if bar_text is not None:
            self._q("#bat-bar", Label).update(bar_text)
        self._q("#bat-stat", Label).update(stat_str)
