"""Unit tests for deterministic pair distribution function diagnostics."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from diffpy.pdfgui.analysis.ai import _extract_response_text
from diffpy.pdfgui.analysis.core import analyze_pdf_data
from diffpy.pdfgui.analysis.io import load_pdf_data
from diffpy.pdfgui.analysis.models import AnalysisConfig, PDFSeries
from diffpy.pdfgui.analysis.report import analysis_to_json, analysis_to_markdown, build_ai_prompt


class TestPDFAnalysis(unittest.TestCase):
    def test_detects_positive_and_negative_features(self):
        r = np.linspace(1.0, 7.0, 1201)
        observed = 3.0 * np.exp(-0.5 * ((r - 2.4) / 0.045) ** 2)
        observed -= 2.0 * np.exp(-0.5 * ((r - 4.1) / 0.060) ** 2)
        observed += 1.4 * np.exp(-0.5 * ((r - 5.6) / 0.050) ** 2)
        analysis = analyze_pdf_data(
            PDFSeries(name="synthetic", r=r, observed=observed),
            AnalysisConfig(max_peaks=6, smoothing_width=0.025, min_peak_distance=0.25),
        )
        positive_positions = [peak.position for peak in analysis.peaks if peak.sign == "positive"]
        negative_positions = [peak.position for peak in analysis.peaks if peak.sign == "negative"]
        self.assertTrue(any(abs(position - 2.4) < 0.03 for position in positive_positions))
        self.assertTrue(any(abs(position - 5.6) < 0.03 for position in positive_positions))
        self.assertTrue(any(abs(position - 4.1) < 0.03 for position in negative_positions))

    def test_residual_metrics(self):
        r = np.arange(1.0, 6.0)
        observed = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        calculated = observed + np.array([0.1, -0.1, 0.1, -0.1, 0.1])
        sigma = np.full_like(observed, 0.2)
        analysis = analyze_pdf_data(
            PDFSeries(name="fit", r=r, observed=observed, calculated=calculated, sigma=sigma)
        )
        self.assertIsNotNone(analysis.residual)
        residual = analysis.residual
        assert residual is not None
        self.assertAlmostEqual(0.1, residual.rmse)
        self.assertAlmostEqual(0.1, residual.mae)
        expected_rw = np.sqrt(0.05 / np.sum(observed**2))
        self.assertAlmostEqual(expected_rw, residual.rw)
        self.assertAlmostEqual(expected_rw, residual.weighted_rw)

    def test_sampling_flags_and_duplicate_merge(self):
        r = np.array([0.0, 0.2, 0.4, 0.4, 1.2, 1.4, 1.6])
        observed = np.sin(r)
        analysis = analyze_pdf_data(PDFSeries(name="sampling", r=r, observed=observed, qmax=25.0))
        codes = {flag.code for flag in analysis.flags}
        self.assertIn("duplicate_r", codes)
        self.assertIn("nonuniform_sampling", codes)
        self.assertIn("sampling_gaps", codes)
        self.assertIn("nyquist_undersampling", codes)
        self.assertEqual(1, analysis.duplicate_points_merged)

    def test_file_loader_and_reports(self):
        content = """# qmax = 24.0
# temperature = 300
r, Gobs, Gcalc, sigma
1.0, 1.0, 0.9, 0.1
1.1, 1.5, 1.4, 0.1, 99.0
1.2, 0.8, 0.7, 0.1
1.3, 0.2, 0.3, 0.1
"""
        with TemporaryDirectory() as directory:
            filename = Path(directory) / "sample.csv"
            filename.write_text(content, encoding="utf-8")
            series = load_pdf_data(filename, observed_column=1, calculated_column=2, sigma_column=3)
        self.assertEqual(24.0, series.qmax)
        self.assertEqual(300.0, series.metadata["temperature"])
        analysis = analyze_pdf_data(series)
        markdown = analysis_to_markdown(analysis)
        prompt = build_ai_prompt(
            analysis, question="Which r interval has the largest residual?", language="English"
        )
        serialized = json.loads(analysis_to_json(analysis))
        self.assertIn("Fit residuals", markdown)
        self.assertIn("Which r interval", prompt)
        self.assertEqual("sample", serialized["name"])

    def test_openai_compatible_response_text(self):
        payload = {"choices": [{"message": {"content": [{"type": "text", "text": "result"}]}}]}
        self.assertEqual("result", _extract_response_text(payload))


if __name__ == "__main__":
    unittest.main()
