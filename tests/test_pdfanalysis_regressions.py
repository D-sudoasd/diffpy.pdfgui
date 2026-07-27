"""Regression tests found during the AI analysis pre-merge review."""

from __future__ import annotations

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
from diffpy.pdfgui.analysis.models import PDFSeries


def test_non_object_ai_response_is_rejected_cleanly():
    assert _extract_response_text([]) == ""
    assert _extract_response_text("unexpected") == ""


def test_invalid_ai_timeout_and_endpoint_are_controlled(monkeypatch):
    monkeypatch.setenv("PDFGUI_AI_TIMEOUT", "nan")
    assert AISettings.from_environment().timeout == 60.0

    client = OpenAICompatibleClient(
        AISettings(endpoint="not-a-url", model="test-model", timeout=float("inf"))
    )
    with pytest.raises(AIClientError, match="AI endpoint is invalid"):
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
