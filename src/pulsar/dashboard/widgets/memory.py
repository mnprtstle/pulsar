import math
from typing import Any

import psutil
from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import Static

from ..helpers import WidgetQueryCache
from ..themes import ActiveTheme, active_theme

MemReading = tuple[
    int, int, int, int, int, int, int
]  # total,used,cached,free,avail,swap_used,swap_total
MEMORY_TEXT_PAD_WIDTH = 22


class MemoryWidget(WidgetQueryCache, Static):
    """Registers itself as the "memory" producer on the app's shared
    MetricsThread thread 1."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # int type atomic under GIL
        self.bar_width = 0
        # `_last` lives entirely on the background thread's side: it's
        # only ever read/written inside `_tick`. The main
        # thread never touches it after initialization.
        self._last: MemReading | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="ram-display")

    def on_mount(self) -> None:
        self.call_after_refresh(self._recompute_bar_width)
        self._metric_thread.prime(
            "memory",
            tick=self._tick,
            apply=self._apply,
            widget=self,
        )

    def on_resize(self) -> None:
        self.call_after_refresh(self._recompute_bar_width)

    def _recompute_bar_width(self) -> None:
        self.bar_width = max(0, self.size.width - MEMORY_TEXT_PAD_WIDTH)
        self._metric_thread.request_repaint()

    def _tick(self, redraw_only: bool = False) -> Text | None:
        # do not fetch metrics for redraw_only
        if self._last and redraw_only:
            current = self._last
        else:
            mem = psutil.virtual_memory()
            swap = psutil.swap_memory()
            current: MemReading = (
                mem.total,
                mem.used,
                getattr(mem, "cached", 0),
                mem.free,
                mem.available,
                swap.used,
                swap.total,
            )

            if redraw_only or (current != self._last):
                self._last = current
                return _build_memory_text(current, self.bar_width, active_theme)
            else:
                return None

    def _apply(self, text: Text) -> None:
        self._q("#ram-display", Static).update(text)


def _build_memory_text(reading: MemReading, bar_width: int, theme: ActiveTheme) -> Text:
    """Pure function, no widget access,
    just the reading + geometry + theme it was handed."""
    total_mem, used_mem, cached_mem, free_mem, avail_mem, swap_used, swap_total = (
        reading
    )

    if not total_mem:
        return Text("MEMORY\nMeasuring...")

    total_gib = total_mem / (1024**3)
    used_gib = used_mem / (1024**3)
    cached_gib = cached_mem / (1024**3)
    free_gib = free_mem / (1024**3)
    avail_gib = avail_mem / (1024**3)

    w_used = math.floor((used_mem / total_mem) * bar_width)
    w_cached = math.floor((cached_mem / total_mem) * bar_width)
    w_free = max(0, bar_width - w_used - w_cached)
    w_avail = math.floor((avail_mem / total_mem) * bar_width)

    used_bar = "▀" * w_used + " " * (bar_width - w_used)
    cached_bar = (
        (" " * w_used)
        + ("▪" * (min(w_cached, bar_width - w_used)))
        + (" " * max(0, bar_width - w_used - w_cached))
    )
    free_bar = (" " * (bar_width - w_free)) + ("╍" * w_free)
    avail_bar = " " * (bar_width - w_avail) + "━" * w_avail

    swap_used_gib = swap_used / (1024**3)
    swap_total_gib = swap_total / (1024**3)
    swap_mem_text = f"SWAP  {swap_used_gib:.1f} / {swap_total_gib:.1f} GiB"

    components: list[tuple[str, str | None]] = []
    components.append(("MEMORY", f"bold {theme.primary}"))
    components.append((f"       ({total_gib:>4.2f} GiB)\n", f"dim {theme.primary}"))
    components.append((f"{swap_mem_text}\n\n", f"dim {theme.primary}"))

    if bar_width:
        components.append(("▕", theme.primary))
        components.append((used_bar, theme.error))
        components.append((f"▏ Used  {used_gib:>5.1f} GiB\n", theme.primary))

        components.append(("▕", theme.primary))
        components.append((cached_bar, theme.warning))
        components.append((f"▏ Cached {cached_gib:>4.1f} GiB\n", theme.primary))

        components.append(("▕", theme.primary))
        components.append((free_bar, theme.success))
        components.append((f"▏ Free  {free_gib:>5.1f} GiB\n", theme.primary))

        components.append(("▕", theme.primary))
        components.append((avail_bar, f"bold {theme.success}"))
        components.append((f"▏ Avail {avail_gib:>5.1f} GiB", theme.primary))

    else:
        components.append((f"Used  {used_gib:>5.1f} GiB\n", theme.primary))
        components.append((f"Cached {cached_gib:>4.1f} GiB\n", theme.primary))
        components.append((f"Free  {free_gib:>5.1f} GiB\n", theme.primary))
        components.append((f"Avail {avail_gib:>5.1f} GiB", theme.primary))

    out = Text()
    out.append_tokens(components)
    return out
