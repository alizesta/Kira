"""Size a table/list to its rows so an empty one does not leave a big blank box."""
from __future__ import annotations


def fit_height(view, rows: int, row_height: int = 36, header: int = 34, min_rows: int = 1, max_height: int = 330) -> None:
    extra = header if hasattr(view, "horizontalHeader") else 0
    height = extra + row_height * max(min_rows, rows) + 6
    height = min(height, max_height)
    view.setMinimumHeight(height)
    view.setMaximumHeight(height)
