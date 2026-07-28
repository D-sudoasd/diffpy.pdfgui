"""Implementation of deterministic PDF modeling workflow planning."""

from __future__ import annotations

import json
import math
from typing import Any

from diffpy.pdfgui.modeling.models import BackendStatus, ModelingPlan, ModelingRequest
from diffpy.pdfgui.modeling.registry import backend_map, detect_backends

_SAMPLE_KINDS = {
    "crystalline",
    "nanocrystalline",
    "disordered",
    "amorphous",
    "molecular",
}
_GOALS = {
    "auto",
    "small_box_refinement",
    "custom_refinement",
    "pdf_simulation",
    "series_comparison",
    "large_box_modeling",
}
_PATH_KEY_PARTS = ("path", "file", "source", "directory", "executable")


def plan_modeling(
    request: ModelingRequest,
    statuses: tuple[BackendStatus, ...] | None = None,
) -> ModelingPlan:
    """Select a backend and build a reproducible staged workflow."""

    _validate_request(request)
    detected = detect_backends() if statuses is None else statuses
    available = backend_map(detected)
    selected_id, rationale = _select_backend(request, available)
    status = available.get(selected_id) or _unknown_status(selected_id)
    required_inputs = _required_inputs(selected_id)
    steps = _steps(selected_id, request)
    warnings = list(_warnings(selected_id, status, request))
    alternatives = _alternatives(selected_id, request, available)
    if request.structure_file is None and any(
        phrase in item.lower()
        for item in required_inputs
        for phrase in ("structure", "configuration")
    ):
        warnings.append("A structure model or starting configuration has not been supplied.")
    if not request.data_files and any("data" in item.lower() for item in required_inputs):
        warnings.append("Experimental PDF data have not been supplied.")
    return ModelingPlan(
        selected_backend=selected_id,
        title=_title(selected_id, request),
        rationale=tuple(rationale),
        required_inputs=required_inputs,
        steps=steps,
        warnings=tuple(warnings),
        alternatives=alternatives,
        backend_status=status,
    )


def build_modeling_ai_prompt(
    request: ModelingRequest,
    plan: ModelingPlan,
    statuses: tuple[BackendStatus, ...],
    *,
    diagnostic_summary: dict[str, Any] | None = None,
    question: str = "",
    language: str = "English",
) -> str:
    """Build a bounded explanation prompt without transferring raw PDF arrays."""

    payload = _bounded(
        {
            "request": request.to_dict(),
            "plan": plan.to_dict(),
            "backend_status": [status.to_dict() for status in statuses],
            "diagnostic_summary": diagnostic_summary or {},
            "data_boundary": {
                "raw_pdf_arrays_included": False,
                "structure_contents_included": False,
                "local_paths_reduced_to_basename": True,
            },
        }
    )
    safe_language = " ".join(str(language).split())[:80] or "English"
    prompt = (
        "You are assisting with atomic pair distribution function modeling.\n"
        "The deterministic planner has already selected a backend. Explain the plan, identify "
        "missing inputs, and propose staged checks. Keep numerical observations separate from "
        "structural hypotheses. Do not claim that a phase, defect, atom pair, or disorder mechanism "
        "is established without explicit model or experimental support. Do not recommend an "
        "unavailable backend without also giving the installation or external-executable requirement. "
        f"Respond in {safe_language}.\n\n"
        "Workflow context:\n"
        "```json\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)}\n"
        "```\n"
    )
    cleaned_question = str(question).strip()[:4000]
    if cleaned_question:
        prompt += f"\nUser question:\n{cleaned_question}\n"
    else:
        prompt += "\nTask:\nExplain the selected workflow and the first three checks to perform.\n"
    return prompt


def _select_backend(
    request: ModelingRequest,
    statuses: dict[str, BackendStatus],
) -> tuple[str, list[str]]:
    if request.preferred_backend:
        selected = request.preferred_backend
        return selected, [f"The user explicitly selected {selected}."]

    if request.goal == "series_comparison":
        return "diffpy-morph", [
            "The goal is model-independent comparison of related one-dimensional PDF data."
        ]
    if request.goal == "pdf_simulation":
        return "srreal", ["The goal is direct PDF simulation from an explicit structure model."]
    if request.goal == "large_box_modeling" or request.sample_kind in {
        "disordered",
        "amorphous",
    }:
        selected = _first_usable(("rmcprofile", "fullrmc"), statuses) or "rmcprofile"
        return selected, ["The sample description requires an atomistic large-box disorder model."]
    if (
        request.goal == "custom_refinement"
        or request.custom_constraints
        or len(request.data_files) > 1
    ):
        selected = _first_usable(("diffpy-cmi", "srfit"), statuses) or "diffpy-cmi"
        return selected, [
            "The request includes custom constraints, multiple data sets, or a complex refinement objective."
        ]
    if request.goal == "small_box_refinement":
        return "pdfgui", [
            "The goal is conventional small-box PDF refinement with a crystal structure model."
        ]
    if request.sample_kind == "nanocrystalline":
        return "pdfgui", [
            "A staged small-box fit is the lowest-complexity starting point for a nanocrystalline sample.",
            "Persistent correlated residuals can trigger a later SrFit or large-box workflow.",
        ]
    if request.sample_kind == "molecular" and not request.periodic:
        return "srreal", [
            "A non-periodic molecular model is suited to Debye PDF simulation before refinement."
        ]
    return "pdfgui", [
        "A crystalline sample with one PDF data set is suited to the built-in small-box workflow."
    ]


def _required_inputs(backend_id: str) -> tuple[str, ...]:
    requirements = {
        "pdfgui": (
            "structure model",
            "experimental PDF data",
            "scattering type and Q range",
        ),
        "pdffit2": ("PDFFIT or DISCUS structure model", "experimental PDF data"),
        "srreal": ("structure model", "scattering type and calculation range"),
        "srfit": (
            "structure model",
            "experimental PDF data",
            "explicit variables and constraints",
        ),
        "diffpy-cmi": (
            "structure model",
            "one or more experimental data sets",
            "workflow or recipe definition",
        ),
        "diffpy-morph": ("two or more comparable one-dimensional PDF data sets",),
        "rmcprofile": (
            "starting atomistic configuration",
            "RMCProfile control and data files",
        ),
        "fullrmc": (
            "starting atomistic configuration",
            "reviewed fullrmc Python driver script",
        ),
    }
    return requirements.get(backend_id, ("backend-specific inputs",))


def _steps(backend_id: str, request: ModelingRequest) -> tuple[str, ...]:
    if backend_id in {"pdfgui", "pdffit2"}:
        return (
            (
                "Load the structure and PDF data, then verify scattering type, Qmax, r range, "
                "and uncertainty columns."
            ),
            (
                "Refine scale and instrumental terms before lattice, displacement, occupancy, "
                "or finite-size parameters."
            ),
            (
                "Inspect Rw, residual autocorrelation, parameter bounds, and physically implausible "
                "parameter movement."
            ),
            "Escalate to a custom or large-box model only when reproducible residual structure remains.",
        )
    if backend_id == "srreal":
        mode = "periodic PDFCalculator" if request.periodic else "DebyePDFCalculator"
        return (
            f"Load the structure with diffpy.structure and calculate a baseline using {mode}.",
            "Match scattering type, Qmin, Qmax, r step, qdamp, and qbroad to the experiment.",
            "Compare the simulated curve with the observed PDF and retain the calculation manifest.",
            "Use the result to define a PDFgui or SrFit refinement when fitting is required.",
        )
    if backend_id in {"srfit", "diffpy-cmi"}:
        return (
            (
                "Create a version-controlled recipe with explicit parsers, generators, variables, "
                "constraints, and restraints."
            ),
            (
                "Fit scale and resolution terms first, then release structural variables in "
                "physically justified groups."
            ),
            "Use bounds or restraints for underdetermined variables and compare multiple starting values.",
            "Save optimized values, uncertainty estimates, calculated curves, and residual diagnostics.",
        )
    if backend_id == "diffpy-morph":
        return (
            (
                "Choose a target and comparison PDF collected on compatible grids and over a shared "
                "r interval."
            ),
            "Optimize only justified scale, stretch, and broadening corrections.",
            "Inspect the corrected difference curve and parameter uncertainty before structural assignment.",
            "Send data sets with unexplained differences to small-box or complex-model refinement.",
        )
    if backend_id in {"rmcprofile", "fullrmc"}:
        return (
            "Prepare a large starting configuration and document composition, density, cell, and boundaries.",
            "Define data weights and physically justified distance, coordination, or molecular constraints.",
            "Run the external engine in a separate directory and preserve its input and output manifest.",
            "Validate independent seeds and test final configurations against data not used in the fit.",
        )
    return ("Consult the backend documentation and prepare a version-controlled input manifest.",)


def _warnings(
    backend_id: str,
    status: BackendStatus,
    request: ModelingRequest,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if not status.usable:
        warnings.append(status.detail)
        if status.install_hint:
            warnings.append(status.install_hint)
    if backend_id == "fullrmc":
        warnings.append(
            "fullrmc remains process-separated because its distribution uses the AGPL-3.0 license."
        )
    if backend_id == "rmcprofile":
        warnings.append(
            "RMCProfile is treated as a separately installed executable and is not redistributed."
        )
    if backend_id in {"rmcprofile", "fullrmc"} and request.sample_kind == "crystalline":
        warnings.append(
            "A large-box model adds many degrees of freedom; justify it with data and residual evidence."
        )
    if (
        backend_id in {"srfit", "diffpy-cmi"}
        and not request.custom_constraints
        and len(request.data_files) <= 1
    ):
        warnings.append(
            "Document why the custom workflow is needed beyond the built-in PDFgui refinement."
        )
    return tuple(warnings)


def _alternatives(
    selected_id: str,
    request: ModelingRequest,
    statuses: dict[str, BackendStatus],
) -> tuple[str, ...]:
    if selected_id in {"rmcprofile", "fullrmc"}:
        candidates = ("rmcprofile", "fullrmc", "diffpy-cmi", "pdfgui")
    elif selected_id in {"srfit", "diffpy-cmi"}:
        candidates = ("diffpy-cmi", "srfit", "pdfgui", "srreal")
    elif selected_id == "diffpy-morph":
        candidates = ("diffpy-morph", "pdfgui", "diffpy-cmi")
    elif request.sample_kind == "nanocrystalline":
        candidates = ("pdfgui", "diffpy-cmi", "srfit", "rmcprofile", "fullrmc")
    else:
        candidates = ("pdfgui", "srreal", "diffpy-cmi", "srfit")
    return tuple(
        candidate
        for candidate in candidates
        if candidate != selected_id
        and candidate in statuses
        and statuses[candidate].usable
    )


def _first_usable(
    candidates: tuple[str, ...],
    statuses: dict[str, BackendStatus],
) -> str | None:
    for candidate in candidates:
        status = statuses.get(candidate)
        if status is not None and status.usable:
            return candidate
    return None


def _title(backend_id: str, request: ModelingRequest) -> str:
    return f"{backend_id} workflow for {request.sample_kind} PDF modeling"


def _validate_request(request: ModelingRequest) -> None:
    if request.sample_kind not in _SAMPLE_KINDS:
        raise ValueError(f"unsupported sample kind: {request.sample_kind}")
    if request.goal not in _GOALS:
        raise ValueError(f"unsupported modeling goal: {request.goal}")
    if request.preferred_backend is not None and not request.preferred_backend.strip():
        raise ValueError("preferred_backend cannot be empty")


def _unknown_status(backend_id: str) -> BackendStatus:
    return BackendStatus(
        backend_id=backend_id,
        display_name=backend_id,
        state="missing",
        version=None,
        capabilities=(),
        integration_mode="unknown",
        license_name="unknown",
        detail=f"No registered backend has identifier {backend_id!r}.",
    )


def _bounded(value: Any, *, depth: int = 0, key: str = "") -> Any:
    if depth >= 5:
        return "<maximum depth reached>"
    if isinstance(value, dict):
        items = sorted(value.items(), key=lambda item: str(item[0]))
        bounded = {
            str(item_key): _bounded(
                item_value,
                depth=depth + 1,
                key=str(item_key),
            )
            for item_key, item_value in items[:32]
        }
        if len(items) > 32:
            bounded["__truncated_items__"] = len(items) - 32
        return bounded
    if isinstance(value, (list, tuple, set, frozenset)):
        sequence = list(value)
        bounded_items = [
            _bounded(item, depth=depth + 1, key=key) for item in sequence[:32]
        ]
        if len(sequence) > 32:
            bounded_items.append(f"<truncated {len(sequence) - 32} item(s)>")
        return bounded_items
    if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
        try:
            return _bounded(value.tolist(), depth=depth, key=key)
        except Exception:
            pass
    if isinstance(value, str):
        text = value
        lowered = key.lower()
        if _looks_like_path(text) or any(part in lowered for part in _PATH_KEY_PARTS):
            text = _basename(text)
        return text[:500] + ("…" if len(text) > 500 else "")
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if value is None or isinstance(value, (bool, int)):
        return value
    return str(value)[:500]


def _looks_like_path(value: str) -> bool:
    if value.startswith(("/", "~/", "./", "../", "\\\\")):
        return True
    return len(value) >= 3 and value[1] == ":" and value[2] in ("/", "\\")


def _basename(value: str) -> str:
    normalized = value.replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1] or "<path>"
