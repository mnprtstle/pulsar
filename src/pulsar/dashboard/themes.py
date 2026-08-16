from dataclasses import dataclass
from typing import Any

from textual.app import App
from textual.theme import Theme


@dataclass(frozen=True, slots=True)
class _ThemeSnapshot:
    primary: str = "#000000"
    secondary: str = "#000000"
    accent: str = "#000000"
    success: str = "#000000"
    warning: str = "#000000"
    error: str = "#000000"
    background: str = "#000000"
    surface: str = "#000000"
    panel: str = "#000000"


class ActiveTheme:
    """Thread-safe theme handle.

    `_publish` swaps the *entire* snapshot in one attribute
    assignment - atomic under the GIL - so a reader always sees either
    the fully-old or fully-new theme, never a mix."""

    __slots__ = ("_snapshot",)

    def __init__(self) -> None:
        self._snapshot = _ThemeSnapshot()

    def __getattr__(self, name: str) -> str:
        return getattr(self._snapshot, name)

    def publish(self, snapshot: _ThemeSnapshot) -> None:
        self._snapshot = snapshot


active_theme = ActiveTheme()


def sync_active_theme(app: App[Any]) -> None:
    """Builds a new theme snapshot and publishes it in one
    atomic swap."""
    t = app.current_theme
    snapshot = _ThemeSnapshot(
        primary=t.primary,
        secondary=t.secondary or "#000000",
        accent=t.accent or "#000000",
        success=t.success or "#000000",
        warning=t.warning or "#000000",
        error=t.error or "#000000",
        background=t.background or "#000000",
        surface=t.surface or "#000000",
        panel=t.panel or "#000000",
    )
    active_theme.publish(snapshot)


default_dark_theme = Theme(
    name="default_dark",
    primary="#94A3B8",
    secondary="#4E4E52",
    accent="#A78BFA",
    foreground="#C1C1C4",
    background="#000000",
    surface="#1A1A1D",
    panel="#2D2D30",
    success="#16A34A",
    warning="#EA580C",
    error="#DC2626",
    dark=True,
    variables={
        "block-cursor-text-style": "none",
        "footer-key-foreground": "#A78BFA",
        "input-selection-background": "#A78BFA 25%",
        "scrollbar-color": "#353538",
        "scrollbar-color-hover": "#4E4E52",
    },
)


batman_theme = Theme(
    name="batman",
    primary="#8A8FCB",
    secondary="#6B7280",
    accent="#F9A603",
    foreground="#D4D4D8",
    background="#000000",
    surface="#151518",
    panel="#1C1C21",
    success="#30CFA0",
    warning="#FF8C00",
    error="#DC2626",
    dark=True,
    variables={
        "block-cursor-text-style": "none",
        "footer-key-foreground": "#F4C430",
        "input-selection-background": "#F4C430 35%",
        "scrollbar-color": "#3A3F4B",
        "scrollbar-color-hover": "#F4C430",
    },
)


cyberpunk_theme = Theme(
    name="cyberpunk",
    primary="#FF007A",
    secondary="#00F0FF",
    accent="#FFD600",
    foreground="#E8D9FF",
    background="#070F20",
    surface="#0F101F",
    panel="#16192B",
    success="#00FF41",
    error="#FF3333",
    warning="#FF8800",
    dark=True,
    variables={
        "block-cursor-text-style": "none",
        "footer-key-foreground": "#FF2E9A",
        "input-selection-background": "#3DC7FF 30%",
        "scrollbar-color": "#2C1E45",
        "scrollbar-color-hover": "#FF2E9A",
    },
)

monochrome_theme = Theme(
    name="monochrome",
    primary="#B0B0B0",
    secondary="#808080",
    accent="#FFFFFF",
    foreground="#D4D4D4",
    background="#0E0E0E",
    surface="#161616",
    panel="#242424",
    success="#9E9E9E",
    warning="#D4D4D4",
    error="#FFFFFF",
    dark=True,
    variables={
        "block-cursor-text-style": "none",
        "footer-key-foreground": "#FFFFFF",
        "input-selection-background": "#FFFFFF 25%",
        "scrollbar-color": "#242424",
        "scrollbar-color-hover": "#B0B0B0",
    },
)

hacker_theme = Theme(
    name="hacker",
    primary="#00A832",
    secondary="#008F29",
    accent="#2CE210",
    foreground="#99DD99",
    background="#000000",
    surface="#030A03",
    panel="#081A08",
    success="#00B738",
    warning="#9ACD32",
    error="#FF3131",
    dark=True,
    variables={
        "block-cursor-text-style": "none",
        "footer-key-foreground": "#2CE210",
        "input-selection-background": "#00C738 30%",
        "scrollbar-color": "#081A08",
        "scrollbar-color-hover": "#00C738",
    },
)


the_batman_red_theme = Theme(
    name="the_batman_red",
    primary="#D32F2F",
    secondary="#6B7280",
    accent="#FF3333",
    foreground="#D4D4D8",
    background="#000000",
    surface="#000000",
    panel="#1C1C21",
    success="#30CFA0",
    warning="#FF8C00",
    error="#DC2626",
    dark=True,
    variables={
        "block-cursor-text-style": "none",
        "footer-key-foreground": "#D32F2F",
        "input-selection-background": "#D32F2F 35%",
        "scrollbar-color": "#3A3F4B",
        "scrollbar-color-hover": "#FF3333",
    },
)


extra_themes = (
    default_dark_theme,
    batman_theme,
    cyberpunk_theme,
    monochrome_theme,
    hacker_theme,
    the_batman_red_theme,
)
