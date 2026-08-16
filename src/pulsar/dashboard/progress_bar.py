from rich.text import Text
from textual.color import Color, Gradient
from textual.widgets import ProgressBar

from .themes import active_theme

WIDTH_FOR_PERCENTAGE = 5


BarInfo = tuple[Text, int, Gradient] | tuple[Text, int]


def create_progress_bar(
    width: int = 0,
    gradient_colors: list[str] | None = None,
) -> BarInfo:
    """Creates a progress bar and returns info for the bar including the rich text
    object for bar, rich gradient object, and width for the bar

    Args:
        width: total width available
        gradient_colors: List of gradient colors from left to right
    """

    bar = Text()
    width_for_bar = max(0, width - WIDTH_FOR_PERCENTAGE)

    if not gradient_colors:
        return (bar, width_for_bar)

    color_stops = [
        ((i / ((len(gradient_colors) - 1) or 1)), color)
        for i, color in enumerate(gradient_colors)
        if color
    ]

    gradient = Gradient(*color_stops, quality=width_for_bar)

    return (bar, width_for_bar, gradient)


def update_progress_bar(
    bar_info: BarInfo,
    percentage: float = 0.0,
    character_to_use_for_cells: str = "■",
    unfilled_color: str = "rgb(30, 30, 30)",
) -> Text:
    """Updates progress bar and returns the rich text object for bar

    Args:
        bar_info: Information about the existing width, gradient and bar
        percentage: Float between 0.0 and 100.0 representing completion.
        character_to_use_for_cells: The string character used to fill the bar, MUST NOT
        CONTAIN SPACES.
        unfilled_color: Color for the unfilled cells
    """

    line = bar_info[0]
    width_for_bar = bar_info[1]

    percentage = max(0.0, min(100.0, percentage))
    filled_width = min(round((percentage / 100.0) * width_for_bar), width_for_bar)

    line.plain = ""

    unfilled_style = Color.parse(unfilled_color).css

    components: list[tuple[str, str]] = []

    if len(bar_info) == 2:
        color = (
            active_theme.error
            if percentage >= 80
            else active_theme.warning
            if percentage >= 50
            else active_theme.success
        )
        filled_style = Color.parse(color).css

        components.append((character_to_use_for_cells * filled_width, filled_style))
        unfilled_width = width_for_bar - filled_width
        components.append((character_to_use_for_cells * unfilled_width, unfilled_style))

    else:
        gradient = bar_info[2]
        for col in range(width_for_bar):
            if col < filled_width:
                # Calculate progress fraction across the total width
                fraction = col / max(1, width_for_bar - 1)
                cell_color = gradient.get_color(fraction).css
                components.append((character_to_use_for_cells, cell_color))
            else:
                components.append((character_to_use_for_cells, unfilled_style))

    components.append((f"{percentage:>4.0f}%", active_theme.primary))
    line.append_tokens(components)

    return line


def set_progress_bar_color(bar: ProgressBar, percentage: float):
    if percentage >= 80:
        bar.remove_class("med-usage")
        bar.add_class("high-usage")
    if percentage >= 50:
        bar.remove_class("high-usage")
        bar.add_class("med-usage")
    else:
        bar.remove_class("high-usage", "med-usage")
