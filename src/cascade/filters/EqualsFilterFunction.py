import os

from cascade.filters.FilterFunction import FilterFunction
from cascade.utils import Utils


class EqualsFilterFunction(FilterFunction):
    """Keep contexts whose selected value exactly matches an expected value."""

    def __init__(
        self,
        key,
        expected,
        normalize_path=False,
        return_value_if_not_exists=False,
    ):
        super().__init__()
        self.key = key
        self.expected = expected
        self.normalize_path = normalize_path
        self.return_value_if_not_exists = return_value_if_not_exists

    def filter(self, context) -> bool:
        value = Utils.get_value_from_context(self.key, context, lambda _: None)
        if value is None:
            return self.return_value_if_not_exists

        expected = self.expected
        if self.normalize_path:
            value = self._normalize_path(value)
            expected = self._normalize_path(expected)

        return value == expected

    @staticmethod
    def _normalize_path(value):
        normalized = os.path.normpath(str(value).replace("\\", "/"))
        if normalized.startswith("./"):
            normalized = normalized[2:]
        return normalized.replace("\\", "/")
