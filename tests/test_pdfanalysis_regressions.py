"""Regression tests found during the AI analysis pre-merge review."""

from __future__ import annotations

import json
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pytest

from diffpy.pdfgui.analysis.ai import (
    AIClientError,
    AISettings,
    OpenAICompatibleClient,
    _extract_response_text,
)
from diffpy.pdfgui.analysis.cli import main as cli_main
from diffpy.pdfgui.analysis.core import analyze_pdf_data
from diffpy.pdfgui.analysis.io import load_pdf_data
from diffpy.pdfgui.analysis.models import PDFSeries
from diffpy.pdfgui.analysis.report import analysis_to_json, build_ai_prompt


def test_non_object_ai_response_is_rejected_cleanly():
    assert _extract_response_text([]) == ""
    assert _extract_response_text("unexpected") == ""


def test_invalid_ai_timeout_and_endpoint_are_controlled(monkeypatch):
    monkeypatch.setenv("PDFGUI_AI_TIMEOUT", "nan")
    assert AISettings.from_environment().timeout == 60.0

    client = OpenAICompatibleClient(
        AISettings(endpoint="not-a-url", model="test-model", timeout=float("inf"))
    )
    with pytest.raises(AIClientError, match="absolute HTTP or HTTPS URL"):
        client.ask("diagnose")


def test_zero_mad_residual_outlier_is_detected():
    r = np.arange(20.0)
    observed = np.ones(20)
    calculated = observed.copy()
    calculated[10] = 0.0
    analysis = analyze_pdf_data(
        PDFSeries(name="sparse-outlier", r=r, observed=observed, calculated=calculated)
    )
    assert analysis.residual is not None
    assert analysis.residual.outlier_count == 1
    assert "residual_outliers" in {flag.code for flag in analysis.flags}


def test_metadata_serialization_and_ai_prompt_are_bounded():
    r = np.arange(5.0)
    analysis = analyze_pdf_data(
        PDFSeries(
            name="metadata",
            r=r,
            observed=np.sin(r),
            source="/private/lab/sample.gr",
            metadata={
                "array": np.arange(40),
                "filename": "/private/lab/model.cif",
                "nonfinite": np.nan,
                "object": Path("/private/lab/metadata.json"),
            },
        )
    )
    payload = json.loads(analysis_to_json(analysis))
    assert payload["metadata"]["array"] == list(range(40))
    assert payload["metadata"]["nonfinite"] is None

    prompt = build_ai_prompt(analysis, question="x" * 5000)
    assert "/private/lab/" not in prompt
    assert "sample.gr" in prompt
    assert "model.cif" in prompt
    assert "<truncated 8 item(s)>" in prompt
    assert len(prompt) < 20000


def test_loader_supports_fortran_exponents_and_rejects_duplicate_columns():
    with TemporaryDirectory() as directory:
        source = Path(directory) / "fortran.gr"
        source.write_text(
            "# qmax = 2.5D+1\n"
            "1.0D+0 2.0D+0 # first point\n"
            "2.0D+0 3.0D+0 ; second point\n"
            "3.0D+0 4.0D+0 // third point\n",
            encoding="utf-8",
        )
        series = load_pdf_data(source)
        assert series.qmax == 25.0
        assert np.allclose(series.observed, [2.0, 3.0, 4.0])
        with pytest.raises(ValueError, match="must be distinct"):
            load_pdf_data(source, observed_column=0)


def test_cli_reports_output_errors_and_avoids_name_collisions():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "single.gr"
        source.write_text("1 1\n2 2\n3 3\n", encoding="utf-8")
        output_directory = root / "existing"
        output_directory.mkdir()
        stderr = StringIO()
        with redirect_stderr(stderr):
            result = cli_main([str(source), "--output", str(output_directory)])
        assert result == 2
        assert "could not write output" in stderr.getvalue()

        first_directory = root / "first"
        second_directory = root / "second"
        first_directory.mkdir()
        second_directory.mkdir()
        first = first_directory / "sample.gr"
        second = second_directory / "sample.gr"
        first.write_text("1 1\n2 2\n3 3\n", encoding="utf-8")
        second.write_text("1 2\n2 3\n3 4\n", encoding="utf-8")
        output = root / "batch"
        result = cli_main([str(first), str(second), "--output", str(output), "--format", "json"])
        assert result == 0
        assert (output / "sample-analysis.json").is_file()
        assert (output / "sample-analysis-2.json").is_file()
