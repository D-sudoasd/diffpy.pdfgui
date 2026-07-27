"""Command-line interface for pair distribution function diagnostics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from diffpy.pdfgui.analysis.core import analyze_pdf_data
from diffpy.pdfgui.analysis.io import load_pdf_data
from diffpy.pdfgui.analysis.models import AnalysisConfig
from diffpy.pdfgui.analysis.report import analysis_to_json, analysis_to_markdown, build_ai_prompt


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser."""

    parser = argparse.ArgumentParser(
        prog="pdfgui-analyze",
        description="Analyze atomic pair distribution function data and optional fit residuals.",
    )
    parser.add_argument("files", nargs="+", type=Path, help="PDF data file(s) to analyze")
    parser.add_argument(
        "--observed-column",
        type=_positive_column,
        default=2,
        metavar="N",
        help="1-based observed G(r) column (default: 2)",
    )
    parser.add_argument(
        "--calculated-column",
        type=_positive_column,
        metavar="N",
        help="1-based calculated G(r) column for residual diagnostics",
    )
    parser.add_argument(
        "--sigma-column",
        type=_positive_column,
        metavar="N",
        help="1-based positive uncertainty column for weighted Rw",
    )
    parser.add_argument("--max-peaks", type=int, default=12, help="maximum detected features to report")
    parser.add_argument(
        "--smoothing-width",
        type=float,
        default=0.05,
        metavar="ANGSTROM",
        help="moving-average width used for feature detection (default: 0.05)",
    )
    parser.add_argument(
        "--min-peak-distance",
        type=float,
        default=0.15,
        metavar="ANGSTROM",
        help="minimum separation between reported features (default: 0.15)",
    )
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument(
        "--output",
        type=Path,
        help="output file for one input, or output directory for multiple inputs",
    )
    parser.add_argument(
        "--include-ai-prompt",
        action="store_true",
        help="append a bounded AI interpretation prompt to Markdown output",
    )
    parser.add_argument("--question", default="", help="question included in the generated AI prompt")
    parser.add_argument("--language", default="English", help="requested AI response language")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""

    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_peaks < 1:
        parser.error("--max-peaks must be at least 1")
    if args.smoothing_width < 0.0:
        parser.error("--smoothing-width cannot be negative")
    if args.min_peak_distance < 0.0:
        parser.error("--min-peak-distance cannot be negative")
    if args.include_ai_prompt and args.format != "markdown":
        parser.error("--include-ai-prompt is available only with --format markdown")

    config = AnalysisConfig(
        max_peaks=args.max_peaks,
        smoothing_width=args.smoothing_width,
        min_peak_distance=args.min_peak_distance,
    )
    rendered: list[tuple[Path, str]] = []
    for filename in args.files:
        try:
            series = load_pdf_data(
                filename,
                observed_column=args.observed_column - 1,
                calculated_column=(args.calculated_column - 1 if args.calculated_column else None),
                sigma_column=(args.sigma_column - 1 if args.sigma_column else None),
            )
            analysis = analyze_pdf_data(series, config)
        except (OSError, ValueError) as error:
            print(f"pdfgui-analyze: {filename}: {error}", file=sys.stderr)
            return 2
        text = analysis_to_json(analysis) if args.format == "json" else analysis_to_markdown(analysis)
        if args.include_ai_prompt and args.format == "markdown":
            prompt = build_ai_prompt(analysis, question=args.question, language=args.language)
            text += "\n## AI interpretation prompt\n\n```text\n" + prompt + "```\n"
        rendered.append((filename, text))

    if args.output is None:
        if args.format == "json" and len(rendered) > 1:
            payload = [json.loads(text) for _, text in rendered]
            print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        for index, (filename, text) in enumerate(rendered):
            if len(rendered) > 1:
                if index:
                    print("\n---\n")
                print(f"<!-- {filename} -->")
            print(text, end="" if text.endswith("\n") else "\n")
        return 0

    try:
        if len(rendered) == 1:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered[0][1], encoding="utf-8")
            return 0

        args.output.mkdir(parents=True, exist_ok=True)
        extension = ".json" if args.format == "json" else ".md"
        used_names: dict[str, int] = {}
        for filename, text in rendered:
            base_name = f"{filename.stem}-analysis"
            occurrence = used_names.get(base_name, 0) + 1
            used_names[base_name] = occurrence
            suffix = "" if occurrence == 1 else f"-{occurrence}"
            target = args.output / f"{base_name}{suffix}{extension}"
            target.write_text(text, encoding="utf-8")
    except OSError as error:
        print(f"pdfgui-analyze: could not write output: {error}", file=sys.stderr)
        return 2
    return 0


def _positive_column(value: str) -> int:
    column = int(value)
    if column < 1:
        raise argparse.ArgumentTypeError("column numbers are 1-based and must be positive")
    return column


if __name__ == "__main__":
    raise SystemExit(main())
