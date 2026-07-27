"""Deterministic diagnostics for atomic pair distribution function data."""

from __future__ import annotations

from dataclasses import dataclass
from math import pi, sqrt

import numpy as np

from diffpy.pdfgui.analysis.models import (
    AnalysisConfig,
    DiagnosticFlag,
    PDFAnalysis,
    PDFSeries,
    Peak,
    ResidualMetrics,
    ResidualSegment,
)


@dataclass(slots=True)
class _PreparedSeries:
    r: np.ndarray
    observed: np.ndarray
    calculated: np.ndarray | None
    sigma: np.ndarray | None
    original_count: int
    rows_removed: int
    duplicate_points_merged: int
    calculated_rows_missing: int


def analyze_pdf_data(series: PDFSeries, config: AnalysisConfig | None = None) -> PDFAnalysis:
    """Analyze sampling, signal features, and optional fit residuals.

    The calculations are deterministic and do not assign structural meaning to
    detected peaks. Structural interpretation remains dependent on the
    experimental conditions and the fitted model.
    """

    cfg = config or AnalysisConfig()
    _validate_config(cfg)
    prepared = _prepare_series(series)
    r = prepared.r
    observed = prepared.observed
    spacing = np.diff(r)
    spacing_mean = float(np.mean(spacing))
    spacing_median = float(np.median(spacing))
    spacing_cv = float(np.std(spacing) / spacing_mean) if spacing_mean > 0.0 else 0.0
    gap_count = int(np.count_nonzero(spacing > cfg.gap_ratio_warning * spacing_median))

    flags: list[DiagnosticFlag] = []
    if prepared.rows_removed:
        flags.append(
            DiagnosticFlag(
                code="rows_removed",
                severity="warning",
                message=f"Removed {prepared.rows_removed} row(s) with non-finite r or observed values.",
            )
        )
    if prepared.duplicate_points_merged:
        flags.append(
            DiagnosticFlag(
                code="duplicate_r",
                severity="warning",
                message=(
                    f"Merged {prepared.duplicate_points_merged} duplicate r point(s) by averaging values "
                    "at equal r."
                ),
            )
        )
    if spacing_cv > cfg.sampling_cv_warning:
        flags.append(
            DiagnosticFlag(
                code="nonuniform_sampling",
                severity="warning",
                message=(
                    f"The r-step coefficient of variation is {spacing_cv:.3g}, above the configured "
                    f"threshold of {cfg.sampling_cv_warning:.3g}."
                ),
            )
        )
    if gap_count:
        flags.append(
            DiagnosticFlag(
                code="sampling_gaps",
                severity="warning",
                message=(
                    f"Detected {gap_count} r-step gap(s) larger than {cfg.gap_ratio_warning:.3g} times "
                    "the median step."
                ),
            )
        )

    qmax = _positive_float(series.qmax)
    if qmax is None:
        qmax = _metadata_qmax(series.metadata)
    nyquist_interval = pi / qmax if qmax is not None else None
    sampling_to_nyquist = spacing_median / nyquist_interval if nyquist_interval else None
    if sampling_to_nyquist is not None and sampling_to_nyquist > 1.05:
        flags.append(
            DiagnosticFlag(
                code="nyquist_undersampling",
                severity="warning",
                message=(
                    f"The median r-step is {sampling_to_nyquist:.3g} times pi/Qmax; values above 1 indicate "
                    "undersampling relative to the Qmax-limited Nyquist interval."
                ),
            )
        )

    observed_median = float(np.median(observed))
    observed_std = float(np.std(observed))
    noise_estimate = _difference_noise_estimate(observed)
    amplitude = float(np.max(np.abs(observed - observed_median)))
    amplitude_to_noise = amplitude / noise_estimate if noise_estimate > 0.0 else None
    peaks = _detect_peaks(r, observed, noise_estimate, observed_std, cfg)

    residual_metrics = None
    residual_segments: list[ResidualSegment] = []
    calculated_rows_used = None
    if prepared.calculated is not None:
        calc_mask = np.isfinite(prepared.calculated)
        calculated_rows_used = int(np.count_nonzero(calc_mask))
        if prepared.calculated_rows_missing:
            flags.append(
                DiagnosticFlag(
                    code="missing_calculated_values",
                    severity="warning",
                    message=(
                        f"Excluded {prepared.calculated_rows_missing} point(s) with non-finite calculated values "
                        "from residual diagnostics."
                    ),
                )
            )
        if calculated_rows_used >= 3:
            sigma = prepared.sigma[calc_mask] if prepared.sigma is not None else None
            residual_metrics, residual_segments, residual_flags = _analyze_residuals(
                r[calc_mask], observed[calc_mask], prepared.calculated[calc_mask], sigma, cfg
            )
            flags.extend(residual_flags)
        else:
            flags.append(
                DiagnosticFlag(
                    code="insufficient_calculated_values",
                    severity="warning",
                    message="At least three finite calculated values are required for residual diagnostics.",
                )
            )

    return PDFAnalysis(
        name=series.name,
        source=series.source,
        points_original=prepared.original_count,
        points_used=len(r),
        rows_removed=prepared.rows_removed,
        duplicate_points_merged=prepared.duplicate_points_merged,
        calculated_rows_used=calculated_rows_used,
        r_min=float(r[0]),
        r_max=float(r[-1]),
        spacing_median=spacing_median,
        spacing_min=float(np.min(spacing)),
        spacing_max=float(np.max(spacing)),
        spacing_cv=spacing_cv,
        gap_count=gap_count,
        nyquist_interval=nyquist_interval,
        sampling_to_nyquist_ratio=sampling_to_nyquist,
        observed_min=float(np.min(observed)),
        observed_max=float(np.max(observed)),
        observed_mean=float(np.mean(observed)),
        observed_std=observed_std,
        observed_rms=float(np.sqrt(np.mean(np.square(observed)))),
        difference_noise_estimate=noise_estimate,
        amplitude_to_noise=amplitude_to_noise,
        peaks=peaks,
        residual=residual_metrics,
        residual_segments=residual_segments,
        flags=flags,
        metadata=dict(series.metadata),
        config=cfg,
    )


def _validate_config(config: AnalysisConfig) -> None:
    if config.max_peaks < 1:
        raise ValueError("max_peaks must be at least 1")
    if config.smoothing_width < 0.0:
        raise ValueError("smoothing_width cannot be negative")
    if config.min_peak_distance < 0.0:
        raise ValueError("min_peak_distance cannot be negative")
    if config.segment_count < 1:
        raise ValueError("segment_count must be at least 1")
    if config.prominence_sigma < 0.0 or config.prominence_fraction < 0.0:
        raise ValueError("prominence thresholds cannot be negative")


def _prepare_series(series: PDFSeries) -> _PreparedSeries:
    r = np.asarray(series.r, dtype=float).reshape(-1)
    observed = np.asarray(series.observed, dtype=float).reshape(-1)
    if len(r) != len(observed):
        raise ValueError("r and observed arrays must have the same length")
    original_count = len(r)
    if original_count < 3:
        raise ValueError("at least three PDF data points are required")

    calculated = _optional_array(series.calculated, original_count, "calculated")
    sigma = _optional_array(series.sigma, original_count, "sigma")
    primary_mask = np.isfinite(r) & np.isfinite(observed)
    rows_removed = int(original_count - np.count_nonzero(primary_mask))
    r = r[primary_mask]
    observed = observed[primary_mask]
    if calculated is not None:
        calculated = calculated[primary_mask]
    if sigma is not None:
        sigma = sigma[primary_mask]
    if len(r) < 3:
        raise ValueError("fewer than three finite PDF data points remain after validation")

    order = np.argsort(r, kind="mergesort")
    r = r[order]
    observed = observed[order]
    if calculated is not None:
        calculated = calculated[order]
    if sigma is not None:
        sigma = sigma[order]

    unique_r, starts, counts = np.unique(r, return_index=True, return_counts=True)
    duplicate_points_merged = int(np.sum(counts - 1))
    if duplicate_points_merged:
        observed = np.add.reduceat(observed, starts) / counts
        if calculated is not None:
            calculated = _group_nanmean(calculated, starts, counts)
        if sigma is not None:
            sigma = _group_positive_median(sigma, starts, counts)
        r = unique_r

    if len(r) < 3 or np.any(np.diff(r) <= 0.0):
        raise ValueError("r values must contain at least three distinct increasing points")

    calculated_rows_missing = int(np.count_nonzero(~np.isfinite(calculated))) if calculated is not None else 0
    if sigma is not None:
        sigma = np.where(np.isfinite(sigma) & (sigma > 0.0), sigma, np.nan)
        if not np.any(np.isfinite(sigma)):
            sigma = None

    return _PreparedSeries(
        r=r,
        observed=observed,
        calculated=calculated,
        sigma=sigma,
        original_count=original_count,
        rows_removed=rows_removed,
        duplicate_points_merged=duplicate_points_merged,
        calculated_rows_missing=calculated_rows_missing,
    )


def _optional_array(values: np.ndarray | None, length: int, label: str) -> np.ndarray | None:
    if values is None:
        return None
    array = np.asarray(values, dtype=float).reshape(-1)
    if len(array) != length:
        raise ValueError(f"{label} and r arrays must have the same length")
    return array


def _group_nanmean(values: np.ndarray, starts: np.ndarray, counts: np.ndarray) -> np.ndarray:
    grouped = np.full(len(starts), np.nan, dtype=float)
    for index, (start, count) in enumerate(zip(starts, counts, strict=True)):
        chunk = values[start : start + count]
        finite = chunk[np.isfinite(chunk)]
        if finite.size:
            grouped[index] = float(np.mean(finite))
    return grouped


def _group_positive_median(values: np.ndarray, starts: np.ndarray, counts: np.ndarray) -> np.ndarray:
    grouped = np.full(len(starts), np.nan, dtype=float)
    for index, (start, count) in enumerate(zip(starts, counts, strict=True)):
        chunk = values[start : start + count]
        valid = chunk[np.isfinite(chunk) & (chunk > 0.0)]
        if valid.size:
            grouped[index] = float(np.median(valid))
    return grouped


def _difference_noise_estimate(values: np.ndarray) -> float:
    differences = np.diff(values)
    centered = differences - np.median(differences)
    mad = float(np.median(np.abs(centered)))
    estimate = 1.4826 * mad / sqrt(2.0)
    if estimate <= 0.0:
        estimate = float(np.std(differences) / sqrt(2.0))
    return max(0.0, estimate)


def _detect_peaks(
    r: np.ndarray,
    observed: np.ndarray,
    noise_estimate: float,
    observed_std: float,
    config: AnalysisConfig,
) -> list[Peak]:
    spacing = float(np.median(np.diff(r)))
    window = _odd_window(config.smoothing_width, spacing, len(observed))
    smooth = _moving_average(observed, window)
    positive = np.flatnonzero((smooth[1:-1] > smooth[:-2]) & (smooth[1:-1] >= smooth[2:])) + 1
    negative = np.flatnonzero((smooth[1:-1] < smooth[:-2]) & (smooth[1:-1] <= smooth[2:])) + 1
    candidates = np.concatenate((positive, negative))
    if not candidates.size:
        return []

    baseline_radius = max(window * 3, int(round(max(config.min_peak_distance, spacing) / spacing)))
    threshold = max(config.prominence_sigma * noise_estimate, config.prominence_fraction * observed_std)
    ranked: list[tuple[float, int, float, str]] = []
    for index in candidates:
        left = max(0, index - baseline_radius)
        right = min(len(smooth), index + baseline_radius + 1)
        neighborhood = np.concatenate((smooth[left:index], smooth[index + 1 : right]))
        if not neighborhood.size:
            continue
        baseline = float(np.median(neighborhood))
        signed_height = float(smooth[index] - baseline)
        prominence = abs(signed_height)
        if prominence < threshold:
            continue
        sign = "positive" if signed_height > 0.0 else "negative"
        ranked.append((prominence, int(index), baseline, sign))

    ranked.sort(key=lambda item: (-item[0], r[item[1]]))
    selected: list[Peak] = []
    selected_positions: list[float] = []
    for prominence, index, baseline, sign in ranked:
        position = float(r[index])
        if any(abs(position - other) < config.min_peak_distance for other in selected_positions):
            continue
        width = _half_height_width(r, smooth, index, baseline)
        selected.append(
            Peak(
                position=position,
                amplitude=float(observed[index]),
                prominence=float(prominence),
                width=width,
                sign=sign,
                index=index,
            )
        )
        selected_positions.append(position)
        if len(selected) >= config.max_peaks:
            break
    selected.sort(key=lambda peak: peak.position)
    return selected


def _odd_window(width: float, spacing: float, point_count: int) -> int:
    if width <= 0.0 or spacing <= 0.0:
        return 1
    window = max(1, int(round(width / spacing)))
    if window % 2 == 0:
        window += 1
    maximum = point_count if point_count % 2 == 1 else point_count - 1
    return max(1, min(window, maximum))


def _moving_average(values: np.ndarray, window: int) -> np.ndarray:
    if window <= 1:
        return values.copy()
    pad = window // 2
    padded = np.pad(values, pad_width=pad, mode="reflect")
    kernel = np.full(window, 1.0 / window)
    return np.convolve(padded, kernel, mode="valid")


def _half_height_width(r: np.ndarray, values: np.ndarray, index: int, baseline: float) -> float | None:
    signed_height = float(values[index] - baseline)
    if signed_height == 0.0:
        return None
    half_level = baseline + 0.5 * signed_height
    positive = signed_height > 0.0

    left_index = None
    for cursor in range(index - 1, -1, -1):
        crossed = values[cursor] <= half_level if positive else values[cursor] >= half_level
        if crossed:
            left_index = cursor
            break
    right_index = None
    for cursor in range(index + 1, len(values)):
        crossed = values[cursor] <= half_level if positive else values[cursor] >= half_level
        if crossed:
            right_index = cursor
            break
    if left_index is None or right_index is None:
        return None

    left_r = _interpolated_crossing(
        float(r[left_index]),
        float(values[left_index]),
        float(r[left_index + 1]),
        float(values[left_index + 1]),
        half_level,
    )
    right_r = _interpolated_crossing(
        float(r[right_index - 1]),
        float(values[right_index - 1]),
        float(r[right_index]),
        float(values[right_index]),
        half_level,
    )
    width = right_r - left_r
    return float(width) if width > 0.0 else None


def _interpolated_crossing(x0: float, y0: float, x1: float, y1: float, level: float) -> float:
    if y1 == y0:
        return 0.5 * (x0 + x1)
    fraction = (level - y0) / (y1 - y0)
    fraction = min(1.0, max(0.0, fraction))
    return x0 + fraction * (x1 - x0)


def _analyze_residuals(
    r: np.ndarray,
    observed: np.ndarray,
    calculated: np.ndarray,
    sigma: np.ndarray | None,
    config: AnalysisConfig,
) -> tuple[ResidualMetrics, list[ResidualSegment], list[DiagnosticFlag]]:
    residual = observed - calculated
    rmse = float(np.sqrt(np.mean(np.square(residual))))
    mae = float(np.mean(np.abs(residual)))
    mean = float(np.mean(residual))
    max_abs = float(np.max(np.abs(residual)))
    denominator = float(np.sum(np.square(observed)))
    rw = float(np.sqrt(np.sum(np.square(residual)) / denominator)) if denominator > 0.0 else None
    observed_range = float(np.ptp(observed))
    range_normalized_rmse = rmse / observed_range if observed_range > 0.0 else None

    weighted_rw = None
    if sigma is not None:
        weighted_mask = np.isfinite(sigma) & (sigma > 0.0)
        if np.count_nonzero(weighted_mask) >= 3:
            weighted_residual = residual[weighted_mask] / sigma[weighted_mask]
            weighted_observed = observed[weighted_mask] / sigma[weighted_mask]
            weighted_denominator = float(np.sum(np.square(weighted_observed)))
            if weighted_denominator > 0.0:
                weighted_rw = float(np.sqrt(np.sum(np.square(weighted_residual)) / weighted_denominator))

    lag1_correlation = None
    if len(residual) >= 3 and np.std(residual[:-1]) > 0.0 and np.std(residual[1:]) > 0.0:
        lag1_correlation = float(np.corrcoef(residual[:-1], residual[1:])[0, 1])
    residual_energy = float(np.sum(np.square(residual)))
    durbin_watson = (
        float(np.sum(np.square(np.diff(residual))) / residual_energy) if residual_energy > 0.0 else None
    )

    median = float(np.median(residual))
    mad = float(np.median(np.abs(residual - median)))
    if mad > 0.0:
        robust_z = 0.6744897501960817 * (residual - median) / mad
        outlier_count = int(np.count_nonzero(np.abs(robust_z) > config.residual_outlier_z))
    else:
        outlier_count = 0

    segments = _residual_segments(r, residual, config.segment_count)
    worst_segment_index = int(np.argmax([segment.rmse for segment in segments])) if segments else None
    flags: list[DiagnosticFlag] = []
    if lag1_correlation is not None and abs(lag1_correlation) > config.residual_correlation_warning:
        flags.append(
            DiagnosticFlag(
                code="residual_autocorrelation",
                severity="warning",
                message=(
                    f"Residual lag-1 correlation is {lag1_correlation:.3g}; inspect systematic model or "
                    "data mismatch."
                ),
            )
        )
    if outlier_count:
        flags.append(
            DiagnosticFlag(
                code="residual_outliers",
                severity="warning",
                message=(
                    f"Detected {outlier_count} residual point(s) above the configured robust-z threshold of "
                    f"{config.residual_outlier_z:.3g}."
                ),
            )
        )
    if rmse > 0.0 and abs(mean) / rmse > config.residual_bias_fraction_warning:
        flags.append(
            DiagnosticFlag(
                code="residual_bias",
                severity="warning",
                message=(
                    f"The absolute mean residual is {abs(mean) / rmse:.3g} times the RMSE, "
                    "indicating a net offset."
                ),
            )
        )

    metrics = ResidualMetrics(
        count=len(residual),
        rmse=rmse,
        mae=mae,
        mean=mean,
        max_abs=max_abs,
        rw=rw,
        weighted_rw=weighted_rw,
        range_normalized_rmse=range_normalized_rmse,
        lag1_correlation=lag1_correlation,
        durbin_watson=durbin_watson,
        outlier_count=outlier_count,
        worst_segment_index=worst_segment_index,
    )
    return metrics, segments, flags


def _residual_segments(r: np.ndarray, residual: np.ndarray, count: int) -> list[ResidualSegment]:
    effective_count = min(count, max(1, len(r) // 10))
    edges = np.linspace(float(r[0]), float(r[-1]), effective_count + 1)
    segments: list[ResidualSegment] = []
    for index in range(effective_count):
        if index == effective_count - 1:
            mask = (r >= edges[index]) & (r <= edges[index + 1])
        else:
            mask = (r >= edges[index]) & (r < edges[index + 1])
        if not np.any(mask):
            continue
        values = residual[mask]
        segments.append(
            ResidualSegment(
                r_start=float(edges[index]),
                r_end=float(edges[index + 1]),
                count=int(np.count_nonzero(mask)),
                rmse=float(np.sqrt(np.mean(np.square(values)))),
                mae=float(np.mean(np.abs(values))),
                mean=float(np.mean(values)),
            )
        )
    return segments


def _positive_float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) and number > 0.0 else None


def _metadata_qmax(metadata: dict[str, object]) -> float | None:
    for key, value in metadata.items():
        if str(key).lower() == "qmax":
            return _positive_float(value)
    return None
