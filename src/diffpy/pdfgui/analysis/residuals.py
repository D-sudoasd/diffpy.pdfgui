"""Residual-analysis compatibility helpers."""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from diffpy.pdfgui.analysis import core as _core
from diffpy.pdfgui.analysis.models import AnalysisConfig, DiagnosticFlag, PDFAnalysis, PDFSeries

_BASE_ANALYZE_PDF_DATA = _core.analyze_pdf_data


def analyze_pdf_data(series: PDFSeries, config: AnalysisConfig | None = None) -> PDFAnalysis:
    """Run the core analysis and supplement zero-dispersion outlier detection."""

    cfg = config or AnalysisConfig()
    analysis = _BASE_ANALYZE_PDF_DATA(series, cfg)
    if analysis.residual is None or analysis.residual.outlier_count:
        return analysis

    prepared = _core._prepare_series(series)
    if prepared.calculated is None:
        return analysis
    calculated_mask = np.isfinite(prepared.calculated)
    if np.count_nonzero(calculated_mask) < 3:
        return analysis

    residual = prepared.observed[calculated_mask] - prepared.calculated[calculated_mask]
    median = float(np.median(residual))
    deviations = np.abs(residual - median)
    if float(np.median(deviations)) > 0.0:
        return analysis

    tolerance = 16.0 * np.finfo(float).eps * max(1.0, float(np.max(np.abs(residual))))
    outlier_count = int(np.count_nonzero(deviations > tolerance))
    if not outlier_count:
        return analysis

    analysis.residual = replace(analysis.residual, outlier_count=outlier_count)
    if not any(flag.code == "residual_outliers" for flag in analysis.flags):
        analysis.flags.append(
            DiagnosticFlag(
                code="residual_outliers",
                severity="warning",
                message=(
                    f"Detected {outlier_count} residual point(s) different from an otherwise "
                    "zero-dispersion residual baseline."
                ),
            )
        )
    return analysis
