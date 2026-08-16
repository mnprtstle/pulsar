from typing import Any

import psutil
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import HorizontalGroup, VerticalScroll
from textual.widgets import Label, Static

from ..helpers import WidgetQueryCache
from ..progress_bar import BarInfo, create_progress_bar, update_progress_bar
from ..themes import active_theme

# CpuWidget.tick result:
# (cpu_percent, main_bar_text, {core_index: (core_val, core_bar_text)})
CpuReading = tuple[float, Text, dict[int, tuple[float, Text]]]


class CpuWidget(WidgetQueryCache, Static):
    """Registers itself as the "cpu" producer on metric_thread."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Geometry - written only on the main thread (mount/resize),
        # read only on the background thread inside `_tick`. Plain
        # attribute swaps, atomic under the GIL, no lock needed.
        self.main_bar_info: BarInfo | None = None
        self.core_bar_info: list[BarInfo] = []
        # Reading cache - lives entirely on the background thread's
        # side, only ever touched inside `_tick`.
        self.core_count = 0
        self._cpu_percent = 0.0
        self._core_vals: list[float] = []

    def compose(self) -> ComposeResult:
        with HorizontalGroup(id="cpu-main"):
            yield Label("CPU", id="cpu-main-label")
            yield Static(id="cpu-main-bar")
        with VerticalScroll(id="core-scroll"):
            yield Static(id="core-grid")

    def on_mount(self) -> None:
        self.core_count = psutil.cpu_count() or 0
        self._core_vals = [0.0] * self.core_count

        core_grid = self._q("#core-grid", Static)
        for i in range(self.core_count):
            core_grid.mount(
                HorizontalGroup(
                    Label(f"C{i:<2}", id=f"label-{i}"),
                    Static(id=f"core-{i}", classes="core-bar"),
                    classes="core-info",
                ),
            )

        self.call_after_refresh(self._initialize_geometry)

    def _initialize_geometry(self) -> None:
        self.reset_gradient_bar()
        self.reset_core_bars()
        self._metric_thread.prime(
            "cpu", tick=self._tick, apply=self._apply, widget=self
        )

    def on_resize(self) -> None:
        self.call_after_refresh(self.reset_bars)

    def reset_gradient_bar(self) -> None:
        main_bar = self._q("#cpu-main-bar", Static)
        self.main_bar_info = create_progress_bar(
            width=main_bar.size.width,
            gradient_colors=[
                active_theme.success,
                active_theme.warning,
                active_theme.error,
            ],
        )

    def reset_core_bars(self) -> None:
        core_bar_width = self._q("#core-0", Static).size.width
        self.core_bar_info = [
            create_progress_bar(width=core_bar_width) for _ in range(self.core_count)
        ]

    def reset_bars(self) -> None:
        self.reset_gradient_bar()
        self.reset_core_bars()
        self._metric_thread.request_repaint()

    def rebuild_theme_colors(self) -> None:
        """main_bar_info's gradient is baked
        with theme colors and needs an explicit rebuild"""
        self.reset_gradient_bar()
        self._metric_thread.request_repaint()

    def _tick(self, redraw_only: bool = False) -> CpuReading | None:
        if self.main_bar_info is None or not self.core_bar_info:
            return None  # not sized yet

        prev_core_vals = self._core_vals  # snapshot before refresh, for diffing
        if not redraw_only:
            self._cpu_percent = psutil.cpu_percent(interval=None)
            self._core_vals = psutil.cpu_percent(interval=None, percpu=True)[
                : self.core_count
            ]

        main_bar_text = update_progress_bar(
            percentage=self._cpu_percent,
            bar_info=self.main_bar_info,
            unfilled_color=active_theme.panel,
        )

        core_bar_updates: dict[int, tuple[float, Text]] = {}
        for i, core_val in enumerate(self._core_vals):
            if redraw_only or prev_core_vals[i] != core_val:
                core_bar_updates[i] = (
                    core_val,
                    update_progress_bar(
                        percentage=core_val,
                        bar_info=self.core_bar_info[i],
                        character_to_use_for_cells="━",
                        unfilled_color=active_theme.panel,
                    ),
                )

        return (self._cpu_percent, main_bar_text, core_bar_updates)

    def _apply(self, reading: CpuReading) -> None:
        _cpu_percent, main_bar_text, core_bar_updates = reading
        self._q("#cpu-main-bar", Static).update(main_bar_text)
        for i, (_core_val, bar_text) in core_bar_updates.items():
            self._q(f"#core-{i}", Static).update(bar_text)
