from typing import Any, TypeVar, cast

from textual.widget import Widget

from .metrics_thread import MetricsThread

T = TypeVar("T", bound=Widget)


class WidgetQueryCache:
    """Mixin that memoizes `query_one` lookups per instance.
    Also has getters for _metric_thread and _update_interval,
    simply because casting is needed everywhere self.app is accessed"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._query_cache: dict[str, Widget] = {}

    def _q(self, selector: str, node_type: type[T]) -> T:
        widget = self._query_cache.get(selector)
        if widget is None:
            widget = cast(Any, self).query_one(selector, node_type)
            self._query_cache[selector] = widget
        return cast(T, widget)

    @property
    def _metric_thread(self) -> MetricsThread:
        return cast(Any, self).app.metric_thread

    @property
    def _update_interval(self) -> float:
        return cast(Any, self).app.update_interval
