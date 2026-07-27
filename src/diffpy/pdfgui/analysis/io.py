"""Input helpers for text-based pair distribution function data."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np

from diffpy.pdfgui.analysis.models import PDFSeries

_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_METADATA_PATTERN = re.compile(rf"\b([A-Za-z][\w.-]*)\s*=\s*({_NUMBER})\b")
_SPLIT_PATTERN = re.compile(r"[\s,]+")


def load_pdf_data(
    filename: str | Path,
    *,
    observed_column: int = 1,
    calculated_column: int | None = None,
    sigma_column: int | None = None,
    name: str | None = None,
) -> PDFSeries:
    """Load a whitespace- or comma-separated PDF data file.

    Column indices are zero-based. Header and comment lines are ignored after
    extracting numeric ``key=value`` metadata. Once numeric data have started,
    malformed rows raise ``ValueError`` with the source line number.
    """

    path = Path(filename).expanduser().resolve()
    if observed_column < 0:
        raise ValueError("observed_column cannot be negative")
    for label, column in (("calculated_column", calculated_column), ("sigma_column", sigma_column)):
        if column is not None and column < 0:
            raise ValueError(f"{label} cannot be negative")

    required_columns = [0, observed_column]
    if calculated_column is not None:
        required_columns.append(calculated_column)
    if sigma_column is not None:
        required_columns.append(sigma_column)
    maximum_column = max(required_columns)

    metadata: dict[str, Any] = {}
    rows: list[list[float]] = []
    numeric_data_started = False
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            line = raw_line.strip()
            if not line:
                continue
            _update_metadata(metadata, line)
            if line.startswith(("#", ";", "//")):
                continue
            tokens = [token for token in _SPLIT_PATTERN.split(line) if token]
            if not tokens:
                continue
            try:
                values = [float(token) for token in tokens]
            except ValueError as error:
                if numeric_data_started:
                    raise ValueError(f"malformed numeric row at {path}:{line_number}") from error
                continue
            if len(values) <= maximum_column:
                if numeric_data_started:
                    raise ValueError(
                        f"row at {path}:{line_number} has {len(values)} column(s); "
                        f"column {maximum_column + 1} is required"
                    )
                continue
            numeric_data_started = True
            rows.append(values)

    if len(rows) < 3:
        raise ValueError(f"{path} does not contain at least three usable numeric rows")
    data = np.asarray([row[: maximum_column + 1] for row in rows], dtype=float)
    qmax = _case_insensitive_metadata(metadata, "qmax")
    return PDFSeries(
        name=name or path.stem,
        r=data[:, 0],
        observed=data[:, observed_column],
        calculated=data[:, calculated_column] if calculated_column is not None else None,
        sigma=data[:, sigma_column] if sigma_column is not None else None,
        metadata=metadata,
        qmax=float(qmax) if qmax is not None else None,
        source=str(path),
    )


def _update_metadata(metadata: dict[str, Any], line: str) -> None:
    for match in _METADATA_PATTERN.finditer(line):
        key = match.group(1)
        value = float(match.group(2))
        metadata[key] = value


def _case_insensitive_metadata(metadata: dict[str, Any], wanted: str) -> Any | None:
    wanted_lower = wanted.lower()
    for key, value in metadata.items():
        if key.lower() == wanted_lower:
            return value
    return None
