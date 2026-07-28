"""Reporting and AI-prompt helpers for PDF diagnostics."""

from __future__ import annotations

import json
from typing import Any

from diffpy.pdfgui.branding import APPLICATION_NAME
from diffpy.pdfgui.analysis.models import PDFAnalysis

_MAX_AI_DEPTH = 5
_MAX_AI_ITEMS = 32
_MAX_AI_STRING = 500
_MAX_AI_QUESTION = 4000
_PATH_KEY_PARTS = ("path", "file", "folder", "directory", "source")


def analysis_to_markdown(analysis: PDFAnalysis) -> str:
    """Render an analysis result as a portable Markdown report."""

    lines = [
        f"# PDF analysis: {analysis.name}",
        "",
        "## Data and sampling",
        "",
        f"- Source: {_text(analysis.source)}",
        f"- Points: {analysis.points_used} used from {analysis.points_original}",
        f"- r range: {_number(analysis.r_min)} to {_number(analysis.r_max)} Å",
        f"- Median r step: {_number(analysis.spacing_median)} Å",
        f"- r-step range: {_number(analysis.spacing_min)} to {_number(analysis.spacing_max)} Å",
        f"- r-step coefficient of variation: {_number(analysis.spacing_cv)}",
        f"- Sampling gaps: {analysis.gap_count}",
    ]
    if analysis.nyquist_interval is not None:
        lines.extend(
            [
                f"- Qmax-limited Nyquist interval, pi/Qmax: {_number(analysis.nyquist_interval)} Å",
                f"- Median-step/Nyquist ratio: {_number(analysis.sampling_to_nyquist_ratio)}",
            ]
        )

    lines.extend(
        [
            "",
            "## Observed G(r)",
            "",
            f"- Minimum / maximum: {_number(analysis.observed_min)} / {_number(analysis.observed_max)}",
            f"- Mean / standard deviation: {_number(analysis.observed_mean)} / {_number(analysis.observed_std)}",
            f"- RMS amplitude: {_number(analysis.observed_rms)}",
            f"- Difference-based robust noise estimate: {_number(analysis.difference_noise_estimate)}",
            f"- Amplitude-to-noise proxy: {_number(analysis.amplitude_to_noise)}",
            "",
            "## Detected features",
            "",
        ]
    )
    if analysis.peaks:
        lines.extend(
            [
                "| r (Å) | Type | G(r) | Prominence | Width (Å) |",
                "| ---: | :--- | ---: | ---: | ---: |",
            ]
        )
        for peak in analysis.peaks:
            lines.append(
                "| "
                + " | ".join(
                    (
                        _number(peak.position),
                        peak.sign,
                        _number(peak.amplitude),
                        _number(peak.prominence),
                        _number(peak.width),
                    )
                )
                + " |"
            )
    else:
        lines.append("No features exceeded the configured prominence threshold.")

    lines.extend(["", "## Fit residuals", ""])
    if analysis.residual is None:
        lines.append("Calculated G(r) was not supplied; residual diagnostics were not computed.")
    else:
        residual = analysis.residual
        lines.extend(
            [
                f"- Points: {residual.count}",
                f"- RMSE: {_number(residual.rmse)}",
                f"- MAE: {_number(residual.mae)}",
                f"- Mean residual: {_number(residual.mean)}",
                f"- Maximum absolute residual: {_number(residual.max_abs)}",
                f"- Rw: {_number(residual.rw)}",
                f"- Weighted Rw: {_number(residual.weighted_rw)}",
                f"- Range-normalized RMSE: {_number(residual.range_normalized_rmse)}",
                f"- Lag-1 residual correlation: {_number(residual.lag1_correlation)}",
                f"- Durbin-Watson statistic: {_number(residual.durbin_watson)}",
                f"- Robust residual outliers: {residual.outlier_count}",
            ]
        )
        if analysis.residual_segments:
            lines.extend(
                [
                    "",
                    "| r interval (Å) | Points | RMSE | MAE | Mean residual |",
                    "| :--- | ---: | ---: | ---: | ---: |",
                ]
            )
            for index, segment in enumerate(analysis.residual_segments):
                label = f"{_number(segment.r_start)}–{_number(segment.r_end)}"
                if index == residual.worst_segment_index:
                    label += " (largest RMSE)"
                lines.append(
                    f"| {label} | {segment.count} | {_number(segment.rmse)} | "
                    f"{_number(segment.mae)} | {_number(segment.mean)} |"
                )

    lines.extend(["", "## Diagnostic flags", ""])
    if analysis.flags:
        for flag in analysis.flags:
            lines.append(f"- **{flag.severity.upper()} · {flag.code}:** {flag.message}")
    else:
        lines.append("No configured diagnostic threshold was exceeded.")

    if analysis.metadata:
        lines.extend(["", "## Metadata", "", "```json"])
        metadata = analysis.to_dict()["metadata"]
        lines.append(json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False))
        lines.append("```")

    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            (
                "Feature detection and residual statistics identify numerical patterns. Phase identity, "
                "coordination, bond assignment, defect chemistry, and model selection require the experimental "
                "context and an explicit structural model."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def build_ai_prompt(
    analysis: PDFAnalysis,
    *,
    question: str = "",
    language: str = "English",
) -> str:
    """Build a bounded prompt from computed diagnostics, without raw arrays."""

    payload = _bounded_ai_payload(analysis)
    safe_language = " ".join(str(language).split())[:80] or "English"
    prompt = f"""You are assisting with atomic pair distribution function (PDF) analysis.
Use only the supplied diagnostics and metadata. Separate numerical observations from structural hypotheses.
Do not assign phases, coordination environments, bond identities, or defect mechanisms unless the supplied metadata
or question provides an explicit structural basis. Treat detected positive and negative features as signal \
features,
not automatic atom-pair assignments. When discussing residuals, identify the relevant r interval and propose checks
that can be performed in {APPLICATION_NAME}. State which additional experimental or model information would be
required for any
stronger conclusion. Respond in {safe_language}.

Computed diagnostics:
```json
{json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)}
```
"""
    cleaned_question = question.strip()[:_MAX_AI_QUESTION]
    if cleaned_question:
        prompt += f"\nUser question:\n{cleaned_question}\n"
    else:
        prompt += (
            "\nTask:\nSummarize data quality, the main signal features, fit-residual behavior, and the next three "
            "model or data checks that are justified by these diagnostics.\n"
        )
    return prompt


def analysis_to_json(analysis: PDFAnalysis, *, indent: int = 2) -> str:
    """Serialize an analysis result to strict JSON."""

    return json.dumps(
        analysis.to_dict(),
        ensure_ascii=False,
        indent=indent,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def _bounded_ai_payload(analysis: PDFAnalysis) -> dict[str, Any]:
    payload = analysis.to_dict()
    source = payload.get("source")
    if source:
        payload["source"] = _local_path_basename(str(source))
    payload["metadata"] = _bounded_ai_value(payload.get("metadata", {}), depth=0)
    payload["request_scope"] = {
        "raw_arrays_included": False,
        "source_path_reduced_to_basename": True,
        "metadata_items_limited": _MAX_AI_ITEMS,
    }
    return payload


def _bounded_ai_value(value: Any, *, depth: int, key: str = "") -> Any:
    if depth >= _MAX_AI_DEPTH:
        return "<maximum depth reached>"
    lowered_key = key.lower()
    if isinstance(value, str):
        text = value
        if any(part in lowered_key for part in _PATH_KEY_PARTS) or _looks_like_local_path(text):
            text = _local_path_basename(text)
        if len(text) > _MAX_AI_STRING:
            return text[:_MAX_AI_STRING] + "…"
        return text
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda item: str(item[0]))
        bounded = {
            str(item_key): _bounded_ai_value(item_value, depth=depth + 1, key=str(item_key))
            for item_key, item_value in items[:_MAX_AI_ITEMS]
        }
        if len(items) > _MAX_AI_ITEMS:
            bounded["__truncated_items__"] = len(items) - _MAX_AI_ITEMS
        return bounded
    if isinstance(value, list):
        bounded_list = [
            _bounded_ai_value(item, depth=depth + 1, key=key) for item in value[:_MAX_AI_ITEMS]
        ]
        if len(value) > _MAX_AI_ITEMS:
            bounded_list.append(f"<truncated {len(value) - _MAX_AI_ITEMS} item(s)>")
        return bounded_list
    return value


def _looks_like_local_path(value: str) -> bool:
    if value.startswith(("/", "~/", "./", "../", "\\\\")):
        return True
    return len(value) >= 3 and value[1] == ":" and value[2] in ("/", "\\")


def _local_path_basename(value: str) -> str:
    normalized = value.replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1] or "<path>"


def _number(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.6g}"


def _text(value: str | None) -> str:
    return value if value else "not specified"
