"""Deterministic and AI-assisted analysis of atomic PDF data."""

from diffpy.pdfgui.analysis import core as _core
from diffpy.pdfgui.analysis.io import load_pdf_data
from diffpy.pdfgui.analysis.models import AnalysisConfig, PDFAnalysis, PDFSeries
from diffpy.pdfgui.analysis.report import analysis_to_json, analysis_to_markdown, build_ai_prompt
from diffpy.pdfgui.analysis.residuals import analyze_pdf_data

# Keep direct imports from ``analysis.core`` on the corrected public path.
_core.analyze_pdf_data = analyze_pdf_data

__all__ = [
    "AnalysisConfig",
    "PDFAnalysis",
    "PDFSeries",
    "analysis_to_json",
    "analysis_to_markdown",
    "analyze_pdf_data",
    "build_ai_prompt",
    "load_pdf_data",
]
