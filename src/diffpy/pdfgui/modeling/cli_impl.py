"""Implementation of the unified atomic PDF modeling command-line interface."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from diffpy.pdfgui.modeling.models import ModelingRequest
from diffpy.pdfgui.modeling.morph_adapter import MorphConfig, compare_pdf_files
from diffpy.pdfgui.modeling.planner import build_modeling_ai_prompt, plan_modeling
from diffpy.pdfgui.modeling.registry import backend_map, detect_backends
from diffpy.pdfgui.modeling.runner import run_external_backend
from diffpy.pdfgui.modeling.srfit_adapter import (
    SrFitRecipeConfig,
    build_single_phase_recipe,
    optimize_recipe,
    save_refined_profile,
)
from diffpy.pdfgui.modeling.srreal_adapter import SrRealSimulationConfig, simulate_structure_pdf

_SAMPLE_KINDS = ("crystalline", "nanocrystalline", "disordered", "amorphous", "molecular")
_GOALS = (
    "auto",
    "small_box_refinement",
    "custom_refinement",
    "pdf_simulation",
    "series_comparison",
    "large_box_modeling",
)


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level parser and all modeling subcommands."""

    parser = argparse.ArgumentParser(
        prog="pdfgui-model",
        description="Inspect, plan, and run optional atomic PDF modeling backends.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="show installed and configured modeling engines")
    doctor.add_argument("--json", action="store_true", dest="as_json")
    doctor.add_argument("--output", type=Path)
    doctor.set_defaults(handler=_doctor)

    plan = subparsers.add_parser("plan", help="select a backend and produce a staged workflow")
    _add_request_arguments(plan)
    plan.add_argument("--json", action="store_true", dest="as_json")
    plan.add_argument("--ai-prompt", action="store_true")
    plan.add_argument("--question", default="")
    plan.add_argument("--language", default="English")
    plan.add_argument("--output", type=Path)
    plan.set_defaults(handler=_plan)

    simulate = subparsers.add_parser("simulate", help="simulate a PDF from a structure using SrReal")
    simulate.add_argument("structure", type=Path)
    simulate.add_argument("output", type=Path)
    simulate.add_argument("--mode", choices=("periodic", "debye"), default="periodic")
    simulate.add_argument("--stype", choices=("X", "N", "E"), default="X")
    simulate.add_argument("--qmin", type=float, default=0.0)
    simulate.add_argument("--qmax", type=float, default=25.0)
    simulate.add_argument("--rmin", type=float, default=0.0)
    simulate.add_argument("--rmax", type=float, default=30.0)
    simulate.add_argument("--rstep", type=float, default=0.01)
    simulate.add_argument("--qdamp", type=float, default=0.0)
    simulate.add_argument("--qbroad", type=float, default=0.0)
    simulate.add_argument("--scale", type=float, default=1.0)
    simulate.add_argument("--json-output", type=Path)
    simulate.set_defaults(handler=_simulate)

    srfit = subparsers.add_parser("srfit", help="run a single-phase SrFit PDF refinement")
    srfit.add_argument("structure", type=Path)
    srfit.add_argument("data", type=Path)
    srfit.add_argument("profile_output", type=Path)
    srfit.add_argument("--space-group")
    srfit.add_argument("--non-periodic", action="store_true")
    srfit.add_argument("--stype", choices=("X", "N", "E"))
    srfit.add_argument("--qmin", type=float)
    srfit.add_argument("--qmax", type=float)
    srfit.add_argument("--rmin", type=float)
    srfit.add_argument("--rmax", type=float, default=20.0)
    srfit.add_argument("--rstep", type=float)
    srfit.add_argument("--no-lattice", action="store_true")
    srfit.add_argument("--no-adp", action="store_true")
    srfit.add_argument("--refine-positions", action="store_true")
    srfit.add_argument("--initial-scale", type=float, default=1.0)
    srfit.add_argument("--initial-qdamp", type=float, default=0.01)
    srfit.add_argument("--initial-qbroad", type=float, default=0.0)
    srfit.add_argument("--initial-delta2", type=float, default=2.0)
    srfit.add_argument("--max-nfev", type=int, default=500)
    srfit.add_argument("--json-output", type=Path)
    srfit.set_defaults(handler=_srfit)

    morph = subparsers.add_parser("morph", help="compare two PDF files using diffpy.morph")
    morph.add_argument("source", type=Path)
    morph.add_argument("target", type=Path)
    morph.add_argument("output", type=Path)
    morph.add_argument("--scale", type=float, default=1.0)
    morph.add_argument("--stretch", type=float, default=0.0)
    morph.add_argument("--smear", type=float, default=0.0)
    morph.add_argument("--xmin", type=float)
    morph.add_argument("--xmax", type=float)
    morph.add_argument("--apply-only", action="store_true")
    morph.add_argument("--uncertainty", action="store_true")
    morph.add_argument("--pearson", action="store_true")
    morph.add_argument("--add-pearson", action="store_true")
    morph.add_argument("--tolerance", type=float, default=1e-8)
    morph.add_argument("--json-output", type=Path)
    morph.set_defaults(handler=_morph)

    external = subparsers.add_parser(
        "external",
        help="run a separately installed RMCProfile executable or fullrmc Python script",
    )
    external.add_argument("backend", choices=("rmcprofile", "fullrmc"))
    external.add_argument("--workdir", type=Path)
    external.add_argument("--timeout", type=float, default=3600.0)
    external.add_argument("--env", action="append", default=[], metavar="KEY=VALUE")
    external.add_argument("--json-output", type=Path)
    external.add_argument("arguments", nargs=argparse.REMAINDER)
    external.set_defaults(handler=_external)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute a modeling command and return a process status code."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (OSError, ValueError, RuntimeError) as error:
        print(f"pdfgui-model: {error}", file=sys.stderr)
        return 2


def _add_request_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sample-kind", choices=_SAMPLE_KINDS, default="crystalline")
    parser.add_argument("--goal", choices=_GOALS, default="auto")
    parser.add_argument("--structure", type=Path)
    parser.add_argument("--data", type=Path, action="append", default=[])
    parser.add_argument("--backend")
    parser.add_argument("--non-periodic", action="store_true")
    parser.add_argument("--custom-constraints", action="store_true")
    parser.add_argument("--metadata", action="append", default=[], metavar="KEY=VALUE")


def _doctor(args: argparse.Namespace) -> int:
    statuses = detect_backends()
    if args.as_json or args.output:
        payload = [status.to_dict() for status in statuses]
        _write_json(payload, args.output)
        return 0
    headers = ("Backend", "State", "Version", "Integration", "Capabilities")
    rows = [
        (
            status.display_name,
            status.state,
            status.version or "-",
            status.integration_mode,
            ", ".join(status.capabilities),
        )
        for status in statuses
    ]
    _print_table(headers, rows)
    for status in statuses:
        if not status.usable:
            print(f"\n{status.display_name}: {status.detail}")
            if status.install_hint:
                print(f"  {status.install_hint}")
    return 0


def _plan(args: argparse.Namespace) -> int:
    statuses = detect_backends()
    request = _request_from_args(args)
    plan = plan_modeling(request, statuses)
    if args.ai_prompt:
        text = build_modeling_ai_prompt(
            request,
            plan,
            statuses,
            question=args.question,
            language=args.language,
        )
        _write_text(text, args.output)
        return 0
    if args.as_json:
        _write_json(plan.to_dict(), args.output)
        return 0
    text = _plan_to_text(plan)
    _write_text(text, args.output)
    return 0


def _simulate(args: argparse.Namespace) -> int:
    result = simulate_structure_pdf(
        args.structure,
        args.output,
        SrRealSimulationConfig(
            mode=args.mode,
            scattering_type=args.stype,
            q_min=args.qmin,
            q_max=args.qmax,
            r_min=args.rmin,
            r_max=args.rmax,
            r_step=args.rstep,
            qdamp=args.qdamp,
            qbroad=args.qbroad,
            scale=args.scale,
        ),
    )
    _write_json(result.to_dict(), args.json_output)
    return 0


def _srfit(args: argparse.Namespace) -> int:
    bundle = build_single_phase_recipe(
        args.structure,
        args.data,
        SrFitRecipeConfig(
            periodic=not args.non_periodic,
            scattering_type=args.stype,
            q_min=args.qmin,
            q_max=args.qmax,
            r_min=args.rmin,
            r_max=args.rmax,
            r_step=args.rstep,
            space_group=args.space_group,
            refine_lattice=not args.no_lattice,
            refine_adp=not args.no_adp,
            refine_positions=args.refine_positions,
            initial_scale=args.initial_scale,
            initial_qdamp=args.initial_qdamp,
            initial_qbroad=args.initial_qbroad,
            initial_delta2=args.initial_delta2,
        ),
    )
    result = optimize_recipe(bundle, max_nfev=args.max_nfev)
    result["profile_output"] = save_refined_profile(bundle, args.profile_output)
    result["structure_file"] = bundle.structure_file
    result["data_file"] = bundle.data_file
    _write_json(result, args.json_output)
    return 0 if result["success"] else 1


def _morph(args: argparse.Namespace) -> int:
    result = compare_pdf_files(
        args.source,
        args.target,
        output_file=args.output,
        config=MorphConfig(
            scale=args.scale,
            stretch=args.stretch,
            smear_pdf=args.smear,
            x_min=args.xmin,
            x_max=args.xmax,
            apply_only=args.apply_only,
            uncertainty=args.uncertainty,
            pearson=args.pearson,
            add_pearson=args.add_pearson,
            tolerance=args.tolerance,
        ),
    )
    _write_json(result, args.json_output)
    return 0


def _external(args: argparse.Namespace) -> int:
    statuses = backend_map()
    status = statuses[args.backend]
    arguments = list(args.arguments)
    if arguments and arguments[0] == "--":
        arguments.pop(0)
    environment = _parse_key_values(args.env)
    result = run_external_backend(
        status,
        arguments,
        working_directory=args.workdir,
        timeout=args.timeout,
        extra_environment=environment,
    )
    payload = result.to_dict()
    if args.json_output:
        _write_json(payload, args.json_output)
    else:
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
    return 0 if result.succeeded else 1


def _request_from_args(args: argparse.Namespace) -> ModelingRequest:
    metadata = _parse_key_values(args.metadata, parse_json=True)
    return ModelingRequest(
        sample_kind=args.sample_kind,
        goal=args.goal,
        structure_file=str(args.structure.resolve()) if args.structure else None,
        data_files=tuple(str(path.resolve()) for path in args.data),
        preferred_backend=args.backend,
        periodic=not args.non_periodic,
        custom_constraints=args.custom_constraints,
        metadata=metadata,
    )


def _parse_key_values(values: list[str], *, parse_json: bool = False) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"expected KEY=VALUE, received {value!r}")
        key, raw = value.split("=", 1)
        key = key.strip()
        if not key:
            raise ValueError("KEY in KEY=VALUE cannot be empty")
        if key in parsed:
            raise ValueError(f"duplicate key: {key}")
        if parse_json:
            try:
                parsed[key] = json.loads(raw)
            except json.JSONDecodeError:
                parsed[key] = raw
        else:
            parsed[key] = raw
    return parsed


def _plan_to_text(plan: Any) -> str:
    lines = [
        f"# {plan.title}",
        "",
        f"Selected backend: {plan.backend_status.display_name} ({plan.backend_status.state})",
        f"Runnable now: {'yes' if plan.runnable else 'no'}",
        "",
        "## Rationale",
    ]
    lines.extend(f"- {item}" for item in plan.rationale)
    lines.extend(["", "## Required inputs"])
    lines.extend(f"- {item}" for item in plan.required_inputs)
    lines.extend(["", "## Steps"])
    lines.extend(f"{index}. {item}" for index, item in enumerate(plan.steps, start=1))
    if plan.warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {item}" for item in plan.warnings)
    if plan.alternatives:
        lines.extend(["", "## Available alternatives", "- " + ", ".join(plan.alternatives)])
    return "\n".join(lines) + "\n"


def _write_json(payload: Any, output: Path | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    _write_text(text, output)


def _write_text(text: str, output: Path | None) -> None:
    if output is None:
        print(text, end="" if text.endswith("\n") else "\n")
        return
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def _print_table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> None:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = min(48, max(widths[index], len(value)))
    format_text = "  ".join(f"{{:<{width}}}" for width in widths)
    print(format_text.format(*headers))
    print(format_text.format(*(width * "-" for width in widths)))
    for row in rows:
        clipped = tuple(
            value
            if len(value) <= widths[index]
            else value[: widths[index] - 1] + "…"
            for index, value in enumerate(row)
        )
        print(format_text.format(*clipped))


if __name__ == "__main__":
    raise SystemExit(main())
