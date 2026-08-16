import getpass
from typing import Any

import psutil
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Click
from textual.geometry import Size
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Input, Static

from ..helpers import WidgetQueryCache
from ..themes import ActiveTheme, active_theme

RawProcessMetrics = tuple[int, str, str, str, str, int, int, float]
# ProcessWidget.tick result: (sorted+filtered pid list, changed-strip dict)
ProcessReading = tuple[list[str], dict[str, "Strip"]]

COLUMNS = [
    ("PID", "pid", 7, "right"),
    ("Program", "name", 20, "left"),
    ("Command", "cmd", 0, "left"),
    ("User", "user", 10, "left"),
    ("St", "state", 2, "left"),
    ("Thr", "threads", 5, "right"),
    ("Mem", "mem", 8, "right"),
    ("CPU %", "cpu", 8, "right"),
]

SORT_INDEX = {"pid": 0, "user": 3, "mem": 6, "cpu": 7}
STATE_MAP = {
    "running": "R",
    "sleeping": "S",
    "zombie": "Z",
    "idle": "I",
    "stopped": "T",
    "disk-sleep": "D",
}
MIN_CMD_COL_WIDTH = 20
PADDING_RIGHT = 2
MEM_MAX = 2.0 * (1024**3)
MEM_WARN = MEM_MAX * 0.8
CPU_MAX = 80.0
CPU_WARN = 64.0


_STYLE_CACHE: dict[str, Style] = {}


def get_style(spec: str | None) -> Style:
    if not spec:
        return Style(color="white")
    style = _STYLE_CACHE.get(spec)
    if style is None:
        style = Style.parse(spec)
        _STYLE_CACHE[spec] = style
    return style


def format_mem(bytes_val: float) -> str:
    for suffix in ["", "k", "M", "G", "T"]:
        if bytes_val < 1024:
            return f"{bytes_val:.1f}{suffix}" if suffix else f"{bytes_val}"
        bytes_val /= 1024
    return f"{bytes_val:.1f}P"


def build_strip(
    raw: RawProcessMetrics,
    current_user: str,
    theme: ActiveTheme,
    cmd_segment_width: int = 0,
) -> Strip:
    pid, name, cmd, user, state, threads, mem_val, cpu_val = raw

    if cpu_val >= CPU_MAX or mem_val >= MEM_MAX:
        row_style = get_style(f"{theme.error} on {theme.background}")
    elif cpu_val >= CPU_WARN or mem_val >= MEM_WARN:
        row_style = get_style(f"{theme.warning} on {theme.background}")
    else:
        row_style = get_style(f"{theme.success} on {theme.background}")

    user_style = get_style(
        f"{theme.primary} on {theme.background}"
        if user == current_user
        else f"dim {theme.primary} on {theme.background}"
    )
    reg_style = get_style(f"{theme.primary} on {theme.background}")
    cmd_str = cmd[:cmd_segment_width] if cmd_segment_width >= MIN_CMD_COL_WIDTH else ""
    cmd_seg_to_print = f"{cmd_str.ljust(cmd_segment_width)} "

    cells = [
        (f"{pid:>7} ", reg_style),
        (f"{name[:20]:<20} ", row_style),
        (cmd_seg_to_print, reg_style),
        (f"{user[:10]:<10} ", user_style),
        (f"{state:<2} ", reg_style),
        (f"{threads:>5} ", row_style),
        (f"{format_mem(mem_val):>8} ", row_style),
        (f"{cpu_val:>7.1f} {' ' * PADDING_RIGHT}", row_style),
    ]
    return Strip([Segment(text, style) for text, style in cells])


LEGEND_ITEMS: list[tuple[str, str]] = [
    ("j/↓ k/↑", "Move"),
    ("^u/^d", "Page"),
    ("x/del", "Kill"),
    ("/", "Filter"),
    ("esc", "Clear"),
    ("q", "Quit"),
]


def build_legend_text(theme: ActiveTheme) -> Text:
    key_style = f"bold {theme.accent}"
    label_style = f"dim {theme.primary}"
    sep_style = f"dim {theme.panel}"

    out = Text()
    components: list[tuple[str, str]] = []
    for i, (keys, label) in enumerate(LEGEND_ITEMS):
        if i:
            components.append(("  │  ", sep_style))
        components.append((f" {keys} ", key_style))
        components.append((label, label_style))
    out.append_tokens(components)
    return out


class ProcessHeader(WidgetQueryCache, Static):
    def __init__(self, controller: "ProcessWidget", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.controller = controller
        self.columns: list[tuple[str, str, int, str]] = COLUMNS

    def refresh_labels(
        self, columns: list[tuple[str, str, int, str]] | None = None
    ) -> None:
        if not columns:
            columns = self.columns
        else:
            self.columns = columns

        columns = list(columns)
        if columns[2][2] < MIN_CMD_COL_WIDTH:
            columns[2] = ("", columns[2][1], columns[2][2], "left")

        components: list[tuple[str, str]] = []
        for label, key, width, align in columns:
            text = label
            if key in SORT_INDEX:
                text = label[1:]
                if key == self.controller.sort_key:
                    text += " \u2193" if self.controller.sort_reverse else " \u2191"
                highlighted_char = label[0]
                highlighted_str = (
                    highlighted_char.rjust(width - len(text))
                    if align == "right"
                    else highlighted_char
                )
                components.append((highlighted_str, f"bold {active_theme.accent}"))
                text = text.ljust(width - 1) if align == "left" else text
            else:
                text = text.rjust(width) if align == "right" else text.ljust(width)
            components.append((f"{text} ", f"bold {active_theme.primary}"))

        out = Text()
        out.append_tokens(components)
        self.update(out)

    def on_click(self, event: Click) -> None:
        pos = 0
        for _label, key, width, _align in self.columns:
            end = pos + width
            if pos <= event.x <= end:
                if key in SORT_INDEX:
                    self.controller.set_sort(key)
                return
            pos = end + 1


class ProcessTable(ScrollView, can_focus=True):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.pids: list[str] = []
        self.cmd_segment_width = 0
        self.columns = list(COLUMNS)
        self.columns[2] = ("Command", "cmd", self.cmd_segment_width, "left")
        self.row_width = sum(w + 1 for _l, _k, w, _a in self.columns)
        self.virtual_size = Size(self.row_width, 0)
        self._strip_cache: dict[str, Strip] = {}
        self.cursor_row = 0
        self._cursor_style = f"bold {active_theme.background} on {active_theme.accent}"

    def update_row_width(self, cmd_segment_width: int) -> None:
        self.cmd_segment_width = cmd_segment_width
        self.columns[2] = ("Command", "cmd", self.cmd_segment_width, "left")
        self.row_width = sum(w + 1 for _l, _k, w, _a in self.columns)
        self.virtual_size = Size(self.row_width, len(self.pids))

    def rebuild_theme_colors(self) -> None:
        self._cursor_style = f"bold {active_theme.background} on {active_theme.accent}"

    def set_data(self, pids: list[str], strips: dict[str, Strip] | None = None) -> None:
        if strips:
            self._strip_cache = strips
        self.pids = pids
        self.virtual_size = Size(self.row_width, len(self.pids))
        if self.cursor_row >= len(pids):
            self.cursor_row = max(0, len(pids) - 1)
        self.refresh()

    def render_line(self, y: int) -> Strip:
        idx = self.scroll_offset.y + y
        if idx >= len(self.pids):
            return Strip.blank(
                self.size.width,
                get_style(f"{active_theme.background} on {active_theme.background}"),
            )
        pid = self.pids[idx]
        strip = self._strip_cache.get(
            pid,
            Strip.blank(
                self.row_width,
                get_style(f"{active_theme.background} on {active_theme.background}"),
            ),
        )
        if idx == self.cursor_row:
            strip = self._override_segment_styles(strip, get_style(self._cursor_style))
        return strip.crop(0, self.size.width)

    def process_updated_content(
        self,
        sorted_pids: list[str],
        new_strips: dict[str, Strip],
        current_cache: dict[str, RawProcessMetrics],
    ) -> None:
        old_strip_cache = self._strip_cache
        new_strip_cache = {
            pid: strip for pid, strip in old_strip_cache.items() if pid in current_cache
        }
        new_strip_cache.update(new_strips)
        self.set_data(sorted_pids, new_strip_cache)

    def _override_segment_styles(self, strip: Strip, override_styles: Style) -> Strip:
        return Strip([Segment(strip.text, override_styles)], strip.cell_length)

    def remove_process_row(self, pid_str: str) -> None:
        new_pids = [p for p in self.pids if p != pid_str]
        strips = dict(self._strip_cache)
        strips.pop(pid_str, None)
        self.set_data(new_pids, strips)

    def cursor_down(self) -> None:
        if not self.pids:
            return
        old_row = self.cursor_row
        self.cursor_row = min(self.cursor_row + 1, len(self.pids) - 1)
        if old_row == self.cursor_row:
            return
        if self._scroll_cursor_visible():
            return
        self.refresh_lines(old_row, 1)
        self.refresh_lines(self.cursor_row, 1)

    def cursor_up(self) -> None:
        if not self.pids:
            return
        old_row = self.cursor_row
        self.cursor_row = max(self.cursor_row - 1, 0)
        if old_row == self.cursor_row:
            return
        if self._scroll_cursor_visible():
            return
        self.refresh_lines(old_row, 1)
        self.refresh_lines(self.cursor_row, 1)

    def page_down(self) -> None:
        if self.pids:
            step = max(1, self.size.height - 1)
            self.cursor_row = min(self.cursor_row + step, len(self.pids) - 1)
            self._scroll_cursor_visible()
            self.refresh()

    def page_up(self) -> None:
        if self.pids:
            step = max(1, self.size.height - 1)
            self.cursor_row = max(self.cursor_row - step, 0)
            self._scroll_cursor_visible()
            self.refresh()

    def _scroll_cursor_visible(self) -> bool:
        top = self.scroll_offset.y
        height = self.size.height or 1
        if self.cursor_row < top:
            self.scroll_to(y=self.cursor_row, animate=False)
            return True
        elif self.cursor_row >= top + height:
            self.scroll_to(y=self.cursor_row - height + 1, animate=False)
            return True
        return False


class ProcessWidget(WidgetQueryCache, Static):
    """Registers itself as the "process" producer on metric_thread.

    `_tick` (background thread) does the full `process_iter()` scan
    and diff on a normal cycle, or - on a redraw-only cycle (resize,
    theme change) - skips psutil entirely and rebuilds every strip
    from the cached readings.
    `self._cache` is written only inside `_tick` (background thread,
    always as a full reassignment, never mutated in place) and read
    from the main thread for instant sort/filter and by
    `action_kill_process` - a plain dict-reference read while it's
    being reassigned is safe under the GIL
    """

    PROC_ATTRS = [
        "pid",
        "name",
        "cmdline",
        "username",
        "status",
        "num_threads",
        "memory_info",
        "cpu_percent",
    ]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.current_user = getpass.getuser()
        self.filter_text = ""
        self.sort_key = "cpu"
        self.sort_reverse = True
        self.cmd_segment_width = 0
        self.columns = list(COLUMNS)
        self.columns[2] = ("Command", "cmd", self.cmd_segment_width, "left")
        self._table: ProcessTable | None = None
        self._cpu_count = psutil.cpu_count() or 1
        self._cache: dict[str, RawProcessMetrics] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="process-container"):
            yield ProcessHeader(self, id="process-header")
            yield ProcessTable(id="process-table")
            yield Input(
                placeholder=(
                    "Filter by Name, Command, or PID"
                    " (Press Enter to apply, Esc to clear)"
                ),
                id="process-filter",
            )
            yield Static(id="process-legend")

    def on_mount(self) -> None:
        self._q("#process-filter", Input).display = False
        self._q("#process-legend", Static).update(build_legend_text(active_theme))
        self.call_after_refresh(self._initialize_widget_operation)

    def _initialize_widget_operation(self) -> None:
        self.resize_cmd_segment(first_call=True)
        self._metric_thread.prime(
            "process", tick=self._tick, apply=self._apply, widget=self
        )

    def on_resize(self) -> None:
        self.call_after_refresh(self.resize_cmd_segment)

    def resize_cmd_segment(self, first_call: bool = False) -> None:
        total_table_width = self.size.width
        new_command_segment_width = max(
            0,
            total_table_width
            - sum(w + 1 for _l, _k, w, _a in COLUMNS)
            - PADDING_RIGHT
            - 1,
        )
        self.cmd_segment_width = new_command_segment_width
        self.columns[2] = ("Command", "cmd", self.cmd_segment_width, "left")
        self.row_width = sum(w + 1 for _l, _k, w, _a in self.columns) + PADDING_RIGHT
        self._q("#process-header", ProcessHeader).refresh_labels(self.columns)

        self._q("#process-table", ProcessTable).update_row_width(
            new_command_segment_width
        )

        if not first_call:
            self._metric_thread.request_repaint()

    def rebuild_theme_colors(self) -> None:
        self._q("#process-table", ProcessTable).rebuild_theme_colors()
        self._q("#process-header", ProcessHeader).refresh_labels(self.columns)
        self._q("#process-legend", Static).update(build_legend_text(active_theme))

    def _tick(self, redraw_only: bool = False) -> ProcessReading:
        theme = active_theme
        cmd_segment_width = self.cmd_segment_width

        if redraw_only:
            current_cache = self._cache
            strips = {
                pid: build_strip(raw, self.current_user, theme, cmd_segment_width)
                for pid, raw in current_cache.items()
            }

        else:
            current_cache: dict[str, RawProcessMetrics] = {}
            strips: dict[str, Strip] = {}
            for p in psutil.process_iter(self.PROC_ATTRS):
                try:
                    pid = p.info["pid"]
                    pid_str = str(pid)
                    name = p.info["name"] or ""
                    cmdline = p.info["cmdline"]
                    cmd = (
                        " ".join(cmdline)[: (cmd_segment_width - 1)] if cmdline else ""
                    )
                    user = p.info["username"] or "unknown"
                    mem_info = p.info["memory_info"]
                    mem_val = mem_info.rss if mem_info else 0
                    if mem_val == 0:
                        continue
                    cpu_val = (p.info["cpu_percent"] / self._cpu_count) or 0.0
                    state_val = STATE_MAP.get(p.info["status"], "?")
                    threads_val = p.info["num_threads"] or 0
                except (
                    psutil.NoSuchProcess,
                    psutil.AccessDenied,
                    psutil.ZombieProcess,
                    KeyError,
                ):
                    continue

                raw: RawProcessMetrics = (
                    pid,
                    name,
                    cmd,
                    user,
                    state_val,
                    threads_val,
                    mem_val,
                    cpu_val,
                )
                current_cache[pid_str] = raw

                old = self._cache.get(pid_str)
                if old is None or old != raw:
                    strips[pid_str] = build_strip(
                        raw, self.current_user, theme, cmd_segment_width
                    )

            self._cache = current_cache  # single reassignment - see class docstring

        filt = self.filter_text
        if filt:
            filtered_pids = [
                k
                for k in current_cache
                if filt in current_cache[k][1].lower()
                or filt in current_cache[k][2].lower()
                or filt in k
            ]
        else:
            filtered_pids = list(current_cache.keys())

        sort_idx = SORT_INDEX[self.sort_key]
        filtered_sorted_pids = sorted(
            filtered_pids,
            key=lambda k: current_cache[k][sort_idx],
            reverse=self.sort_reverse,
        )

        return (filtered_sorted_pids, strips)

    def _apply(self, reading: ProcessReading) -> None:
        filtered_sorted_pids, strips = reading
        queried_one = self._q("#process-table", ProcessTable)
        queried_one.process_updated_content(filtered_sorted_pids, strips, self._cache)

    # --- sort / filter: instant, synchronous, off the shared cache ------
    def set_sort(self, key: str) -> None:
        if self.sort_key == key:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_key = key
            self.sort_reverse = True
        self._q("#process-header", ProcessHeader).refresh_labels()
        self._resort_from_cache()

    def _resort_from_cache(self) -> None:
        sort_idx = SORT_INDEX[self.sort_key]
        cache = self._cache
        sorted_pids = sorted(
            cache.keys(), key=lambda k: cache[k][sort_idx], reverse=self.sort_reverse
        )
        self._q("#process-table", ProcessTable).set_data(sorted_pids)

    def get_table(self) -> ProcessTable:
        if self._table is None:
            self._table = self._q("#process-table", ProcessTable)
        return self._table

    def _refilter_from_cache(self) -> None:
        filt = self.filter_text
        cache = self._cache
        if filt:
            keys = [
                k
                for k, v in cache.items()
                if filt in v[1].lower() or filt in v[2].lower() or filt in k
            ]
        else:
            keys = list(cache.keys())
        sort_idx = SORT_INDEX[self.sort_key]
        keys.sort(key=lambda k: cache[k][sort_idx], reverse=self.sort_reverse)
        self._q("#process-table", ProcessTable).set_data(keys)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.filter_text = event.value.lower()
        inp = self._q("#process-filter", Input)
        inp.display = False
        self._q("#process-table", ProcessTable).focus()
        self._refilter_from_cache()

    def action_clear_filter(self) -> None:
        inp = self._q("#process-filter", Input)
        self.filter_text = ""
        inp.value = ""
        inp.display = False
        self._q("#process-table", ProcessTable).focus()
        self._refilter_from_cache()

    def action_focus_filter(self) -> None:
        inp = self._q("#process-filter", Input)
        inp.display = True
        inp.focus()

    def action_kill_process(self) -> None:
        table = self._q("#process-table", ProcessTable)
        if not table.pids:
            self.notify("No process selected", severity="error")
            return
        pid_str = table.pids[table.cursor_row]
        try:
            psutil.Process(int(pid_str)).terminate()
            self.notify(f"Sent SIGTERM to PID {pid_str}", severity="warning")
            # Reassign rather than `.pop()` in place - the background
            # thread may be mid-iteration over the current `_cache`
            # object during a redraw; a same-object mutation from here
            # could corrupt that iteration, a fresh dict can't.
            self._cache = {k: v for k, v in self._cache.items() if k != pid_str}
            table.remove_process_row(pid_str)
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            self.notify("Failed to kill process", severity="error")
