from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Horizontal, HorizontalGroup, Vertical
from textual.theme import Theme

from .helpers import WidgetQueryCache
from .metrics_thread import MetricsThread
from .themes import extra_themes, sync_active_theme
from .widgets.cpu import CpuWidget
from .widgets.memory import MemoryWidget
from .widgets.process_widget import ProcessTable, ProcessWidget
from .widgets.sidebar_widget import SidebarWidget
from .widgets.top_bar import TopBar

DEFAULT_UPDATE_INTERVAL = 2.0


class DashboardApp(WidgetQueryCache, App[None]):
    """The main root component for the TUI."""

    def __init__(
        self,
        update_interval: float = DEFAULT_UPDATE_INTERVAL,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.update_interval = update_interval
        self.metric_thread = MetricsThread(self, "metric-thread", self.update_interval)
        self.metric_thread.expect(
            "cpu",
            "memory",
            "process",
            "battery",
            "load_avg",
            "thermals",
            "disk_cap",
            "disk_io",
            "net_io",
            "system_info",
        )
        self.metric_thread.start()

    CSS_PATH = "styles.tcss"

    BINDINGS = [
        ("q,Q", "quit", "Quit"),
        ("j,J,down", "process_cursor_down", "Down"),
        ("k,K,up", "process_cursor_up", "Up"),
        ("ctrl+d,ctrl+D", "process_page_down", "Page Down"),
        ("ctrl+u,ctrl+U", "process_page_up", "Page Up"),
        ("x,X,delete", "process_kill", "Kill"),
        ("/", "process_focus_filter", "Filter"),
        ("escape", "process_clear_filter", "Clear Filter"),
        ("p,P", "sort_by_pid", "Sort by PID"),
        ("u,U", "sort_by_user", "Sort by User"),
        ("m,M", "sort_by_mem", "Sort by Memory"),
        ("c,C", "sort_by_cpu", "Sort by CPU"),
        ("+", "increase_update_interval", "Increase update interval"),
        ("-", "decrease_update_interval", "Decrease update interval"),
    ]

    def compose(self) -> ComposeResult:
        yield TopBar(id="top-bar")
        with Horizontal(id="main-layout"):
            yield SidebarWidget(id="sidebar")
            with Vertical(id="right-half"):
                with HorizontalGroup(id="right-top"):
                    yield CpuWidget(id="cpu")
                    yield MemoryWidget(id="mem")
                yield ProcessWidget(id="proc")

    def on_mount(self) -> None:
        self._remove_unsafe_themes()
        for theme in extra_themes:
            self.register_theme(theme)
        self.theme = "default_dark"
        sync_active_theme(self)
        self.theme_changed_signal.subscribe(self, self._on_theme_changed)

    def _remove_unsafe_themes(self) -> None:
        self.unregister_theme("ansi-dark")
        self.unregister_theme("ansi-light")

    def _on_theme_changed(self, _: Theme) -> None:
        sync_active_theme(self)
        # these two need an explicit
        # rebuild before a repaint will show anything different.
        self._q("#cpu", CpuWidget).rebuild_theme_colors()
        self._q("#top-bar", TopBar).rebuild_theme_colors()
        # Process table cursor style + header/legend text aren't part
        # of any producer's tick - they're plain widget state
        self._q("#proc", ProcessWidget).rebuild_theme_colors()
        self.metric_thread.request_repaint()

    def exit(self, *args: Any, **kwargs: Any) -> None:
        # Covers every quit path (q, Ctrl+C, programmatic exit) since
        # they all route through App.exit(). Each MetricsThread's
        # underlying worker is cancelled and woken immediately rather
        # than left to notice on its own next cycle.
        self.metric_thread.stop()
        super().exit(*args, **kwargs)

    # --- events & actions ---
    def action_process_cursor_down(self) -> None:
        self._q("#proc", ProcessWidget)._q("#process-table", ProcessTable).cursor_down()

    def action_process_cursor_up(self) -> None:
        self._q("#proc", ProcessWidget)._q("#process-table", ProcessTable).cursor_up()

    def action_process_page_down(self) -> None:
        self._q("#proc", ProcessWidget)._q("#process-table", ProcessTable).page_down()

    def action_process_page_up(self) -> None:
        self._q("#proc", ProcessWidget)._q("#process-table", ProcessTable).page_up()

    def action_process_kill(self) -> None:
        self._q("#proc", ProcessWidget).action_kill_process()

    def action_process_focus_filter(self) -> None:
        self._q("#proc", ProcessWidget).action_focus_filter()

    def action_process_clear_filter(self) -> None:
        self._q("#proc", ProcessWidget).action_clear_filter()

    def action_sort_by_pid(self) -> None:
        self._q("#proc", ProcessWidget).set_sort("pid")

    def action_sort_by_user(self) -> None:
        self._q("#proc", ProcessWidget).set_sort("user")

    def action_sort_by_mem(self) -> None:
        self._q("#proc", ProcessWidget).set_sort("mem")

    def action_sort_by_cpu(self) -> None:
        self._q("#proc", ProcessWidget).set_sort("cpu")

    def action_increase_update_interval(self) -> None:
        self.update_interval = min(self.update_interval + 0.5, 10.0)
        self.metric_thread.set_interval(self.update_interval)
        self._q("#top-bar", TopBar).update_int_disp()

    def action_decrease_update_interval(self) -> None:
        self.update_interval = max(self.update_interval - 0.5, 0.5)
        self.metric_thread.set_interval(self.update_interval)
        self._q("#top-bar", TopBar).update_int_disp()


if __name__ == "__main__":
    dashboard_app = DashboardApp(update_interval=DEFAULT_UPDATE_INTERVAL)
    dashboard_app.run()
