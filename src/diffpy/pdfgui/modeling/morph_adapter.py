"""Optional diffpy.morph adapter for model-independent PDF comparison."""

from __future__ import annotations

import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


class MorphUnavailableError(RuntimeError):
    """Raised when the optional diffpy.morph package is unavailable."""


@dataclass(frozen=True, slots=True)
class MorphConfig:
    """Configuration for scale, stretch, and PDF-smearing comparison."""

    scale: float = 1.0
    stretch: float = 0.0
    smear_pdf: float = 0.0
    x_min: float | None = None
    x_max: float | None = None
    apply_only: bool = False
    uncertainty: bool = False
    pearson: bool = False
    add_pearson: bool = False
    tolerance: float = 1e-8


def compare_pdf_files(
    source_file: str | Path,
    target_file: str | Path,
    *,
    output_file: str | Path | None = None,
    config: MorphConfig | None = None,
) -> dict[str, Any]:
    """Compare two PDF files with diffpy.morph and optionally save the morphed table."""

    settings = config or MorphConfig()
    _validate_config(settings)
    source_path = _validated_file(source_file, "source")
    target_path = _validated_file(target_file, "target")
    try:
        from diffpy.morph.morphpy import morph
    except ImportError as error:
        raise MorphUnavailableError("diffpy.morph is required for model-independent PDF comparison") from error

    options: dict[str, Any] = {
        "scale": settings.scale,
        "stretch": settings.stretch,
        "smear_pdf": settings.smear_pdf,
        "apply": settings.apply_only,
        "uncertainty": settings.uncertainty,
        "pearson": settings.pearson,
        "addpearson": settings.add_pearson,
        "tolerance": settings.tolerance,
    }
    if settings.x_min is not None:
        options["xmin"] = settings.x_min
    if settings.x_max is not None:
        options["xmax"] = settings.x_max
    morph_info, morph_table = morph(str(source_path), str(target_path), **options)
    table = np.asarray(morph_table, dtype=float)
    if table.ndim != 2 or table.shape[1] != 2 or table.shape[0] < 2:
        raise RuntimeError("diffpy.morph returned an invalid two-column table")
    if not np.all(np.isfinite(table)):
        raise RuntimeError("diffpy.morph returned non-finite values")

    saved_output = None
    if output_file is not None:
        saved_output = _atomic_save_table(output_file, table)
    return {
        "backend_id": "diffpy-morph",
        "source_file": str(source_path),
        "target_file": str(target_path),
        "output_file": saved_output,
        "points": int(table.shape[0]),
        "x_min": float(table[0, 0]),
        "x_max": float(table[-1, 0]),
        "morph_info": _to_builtin(morph_info),
    }


def _atomic_save_table(output_file: str | Path, table: np.ndarray) -> str:
    target = Path(output_file).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=target.name + ".",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_name = stream.name
            np.savetxt(stream, table, header="r(A) Gmorphed(r)")
        os.replace(temporary_name, target)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return str(target)


def _to_builtin(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _to_builtin(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_builtin(item) for item in value]
    if isinstance(value, np.ndarray):
        return _to_builtin(value.tolist())
    if isinstance(value, np.generic):
        return _to_builtin(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _validated_file(value: str | Path, label: str) -> Path:
    try:
        path = Path(value).expanduser().resolve(strict=True)
    except OSError as error:
        raise ValueError(f"{label} PDF file does not exist: {value}") from error
    if not path.is_file():
        raise ValueError(f"{label} PDF path is not a file: {path}")
    return path


def _validate_config(config: MorphConfig) -> None:
    numeric = {
        "scale": config.scale,
        "stretch": config.stretch,
        "smear_pdf": config.smear_pdf,
        "tolerance": config.tolerance,
    }
    for name, value in numeric.items():
        if not math.isfinite(float(value)):
            raise ValueError(f"{name} must be finite")
    if config.scale == 0:
        raise ValueError("scale cannot be zero")
    if config.stretch <= -1:
        raise ValueError("stretch must be greater than -1")
    if config.tolerance <= 0:
        raise ValueError("tolerance must be positive")
    for name, value in (("x_min", config.x_min), ("x_max", config.x_max)):
        if value is not None and not math.isfinite(float(value)):
            raise ValueError(f"{name} must be finite")
    if config.x_min is not None and config.x_max is not None and config.x_max <= config.x_min:
        raise ValueError("x_max must be greater than x_min")
