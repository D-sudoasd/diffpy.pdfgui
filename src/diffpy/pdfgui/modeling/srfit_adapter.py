"""Optional diffpy.srfit recipe construction and optimization helpers."""

from __future__ import annotations

import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


class SrFitUnavailableError(RuntimeError):
    """Raised when the optional SrFit modeling stack is unavailable."""


@dataclass(frozen=True, slots=True)
class SrFitRecipeConfig:
    """Configuration for a single-phase PDF refinement recipe."""

    periodic: bool = True
    scattering_type: str | None = None
    q_min: float | None = None
    q_max: float | None = None
    r_min: float | None = None
    r_max: float | None = 20.0
    r_step: float | None = None
    space_group: str | None = None
    refine_lattice: bool = True
    refine_adp: bool = True
    refine_positions: bool = False
    initial_scale: float = 1.0
    initial_qdamp: float = 0.01
    initial_qbroad: float = 0.0
    initial_delta2: float = 2.0


@dataclass(slots=True)
class SrFitRecipeBundle:
    """A configured recipe with stable metadata for export and inspection."""

    recipe: Any
    contribution_name: str
    structure_file: str
    data_file: str
    warnings: tuple[str, ...]


def build_single_phase_recipe(
    structure_file: str | Path,
    data_file: str | Path,
    config: SrFitRecipeConfig | None = None,
) -> SrFitRecipeBundle:
    """Build a single-phase crystalline or Debye PDF refinement recipe."""

    settings = config or SrFitRecipeConfig()
    _validate_config(settings)
    structure_path = _validated_file(structure_file, "structure")
    data_path = _validated_file(data_file, "PDF data")

    try:
        from diffpy.srfit.fitbase import FitContribution, FitRecipe, Profile
        from diffpy.srfit.pdf import DebyePDFGenerator, PDFGenerator, PDFParser
        from diffpy.structure import load_structure
    except ImportError as error:
        raise SrFitUnavailableError(
            "diffpy.structure, diffpy.srreal, and diffpy.srfit are required for this refinement"
        ) from error

    parser = PDFParser()
    parser.parseFile(str(data_path))
    profile = Profile()
    profile.loadParsedData(parser)
    calculation_range = {
        key: value
        for key, value in (
            ("xmin", settings.r_min),
            ("xmax", settings.r_max),
            ("dx", settings.r_step),
        )
        if value is not None
    }
    if calculation_range:
        profile.setCalculationRange(**calculation_range)

    generator_type = PDFGenerator if settings.periodic else DebyePDFGenerator
    generator = generator_type("G")
    structure = load_structure(str(structure_path))
    generator.setStructure(structure, periodic=settings.periodic)
    if settings.scattering_type is not None:
        generator.setScatteringType(settings.scattering_type)
    if settings.q_min is not None:
        generator.setQmin(settings.q_min)
    if settings.q_max is not None:
        generator.setQmax(settings.q_max)

    contribution_name = "pdf"
    contribution = FitContribution(contribution_name)
    contribution.addProfileGenerator(generator)
    set_profile = getattr(contribution, "set_profile", None)
    if set_profile is not None:
        set_profile(profile, xname="r")
    else:
        contribution.setProfile(profile, xname="r")

    recipe = FitRecipe()
    recipe.clearFitHooks()
    recipe.addContribution(contribution)
    recipe.addVar(generator.scale, settings.initial_scale, tag="scale")
    recipe.addVar(generator.qdamp, settings.initial_qdamp, tag="resolution")
    recipe.addVar(generator.qbroad, settings.initial_qbroad, tag="resolution")
    recipe.addVar(generator.delta2, settings.initial_delta2, tag="correlated_motion")

    warnings: list[str] = []
    if settings.space_group:
        try:
            from diffpy.srfit.structure import constrainAsSpaceGroup
        except ImportError as error:
            raise SrFitUnavailableError("diffpy.srfit structure constraints are unavailable") from error
        symmetry_parameters = constrainAsSpaceGroup(generator.phase, settings.space_group)
        if settings.refine_lattice:
            for parameter in symmetry_parameters.latpars:
                recipe.addVar(parameter, tag="lattice")
        if settings.refine_adp:
            for parameter in symmetry_parameters.adppars:
                recipe.addVar(parameter, tag="adp")
        if settings.refine_positions:
            for parameter in symmetry_parameters.xyzpars:
                recipe.addVar(parameter, tag="position")
    elif settings.refine_lattice or settings.refine_adp or settings.refine_positions:
        warnings.append(
            "Structural variables were not added because no explicit space group was supplied; "
            "only scale, resolution, and correlated-motion variables are free."
        )

    return SrFitRecipeBundle(
        recipe=recipe,
        contribution_name=contribution_name,
        structure_file=str(structure_path),
        data_file=str(data_path),
        warnings=tuple(warnings),
    )


def optimize_recipe(bundle: SrFitRecipeBundle, *, max_nfev: int = 500) -> dict[str, Any]:
    """Optimize a configured SrFit recipe with bounded SciPy least squares."""

    if max_nfev < 1 or max_nfev > 1_000_000:
        raise ValueError("max_nfev must be between 1 and 1000000")
    try:
        from scipy.optimize import least_squares
    except ImportError as error:
        raise SrFitUnavailableError("SciPy is required to optimize an SrFit recipe") from error

    recipe = bundle.recipe
    initial = np.asarray(recipe.getValues(), dtype=float)
    names = tuple(str(name) for name in recipe.getNames())
    if initial.size == 0:
        raise ValueError("the SrFit recipe contains no free variables")
    lower, upper = recipe.getBounds2()
    lower_array = np.asarray(lower, dtype=float)
    upper_array = np.asarray(upper, dtype=float)
    result = least_squares(
        recipe.residual,
        initial,
        bounds=(lower_array, upper_array),
        max_nfev=max_nfev,
    )
    recipe.residual(result.x)
    final_values = np.asarray(recipe.getValues(), dtype=float)
    variables = {
        name: float(value)
        for name, value in zip(names, final_values, strict=True)
    }
    return {
        "success": bool(result.success),
        "status": int(result.status),
        "message": str(result.message),
        "nfev": int(result.nfev),
        "cost": float(result.cost),
        "optimality": float(result.optimality),
        "variables": variables,
        "warnings": list(bundle.warnings),
    }


def save_refined_profile(bundle: SrFitRecipeBundle, output_file: str | Path) -> str:
    """Atomically save r, observed, calculated, residual, and uncertainty columns."""

    target = Path(output_file).expanduser().resolve()
    protected_inputs = {
        Path(bundle.structure_file).expanduser().resolve(),
        Path(bundle.data_file).expanduser().resolve(),
    }
    if target in protected_inputs:
        raise ValueError("refined profile output cannot overwrite a structure or PDF input file")

    contribution = getattr(bundle.recipe, bundle.contribution_name)
    profile = contribution.profile
    r_values = np.asarray(profile.x, dtype=float)
    observed = np.asarray(profile.y, dtype=float)
    calculated = np.asarray(profile.ycalc, dtype=float)
    if r_values.ndim != 1 or observed.shape != r_values.shape or calculated.shape != r_values.shape:
        raise RuntimeError("SrFit profile arrays are incomplete or incompatible")
    uncertainty = np.asarray(getattr(profile, "dy", np.full_like(r_values, np.nan)), dtype=float)
    if uncertainty.shape != r_values.shape:
        uncertainty = np.full_like(r_values, np.nan)
    table = np.column_stack((r_values, observed, calculated, observed - calculated, uncertainty))

    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target.parent,
            prefix=target.name + ".",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_name = stream.name
            np.savetxt(stream, table, header="r(A) Gobs Gcalc Gdiff sigma")
        os.replace(temporary_name, target)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)
    return str(target)


def _validated_file(value: str | Path, label: str) -> Path:
    try:
        path = Path(value).expanduser().resolve(strict=True)
    except OSError as error:
        raise ValueError(f"{label} file does not exist: {value}") from error
    if not path.is_file():
        raise ValueError(f"{label} path is not a file: {path}")
    return path


def _validate_config(config: SrFitRecipeConfig) -> None:
    if config.scattering_type not in {None, "X", "N", "E"}:
        raise ValueError("scattering_type must be X, N, E, or None")
    optional_numeric = {
        "q_min": config.q_min,
        "q_max": config.q_max,
        "r_min": config.r_min,
        "r_max": config.r_max,
        "r_step": config.r_step,
    }
    for name, value in optional_numeric.items():
        if value is not None and not math.isfinite(float(value)):
            raise ValueError(f"{name} must be finite")
    if config.q_min is not None and config.q_min < 0:
        raise ValueError("q_min cannot be negative")
    if config.q_max is not None and config.q_max <= 0:
        raise ValueError("q_max must be positive")
    if config.q_min is not None and config.q_max is not None and config.q_max <= config.q_min:
        raise ValueError("q_max must be greater than q_min")
    if config.r_min is not None and config.r_min < 0:
        raise ValueError("r_min cannot be negative")
    if config.r_max is not None and config.r_max <= 0:
        raise ValueError("r_max must be positive")
    if config.r_min is not None and config.r_max is not None and config.r_max <= config.r_min:
        raise ValueError("r_max must be greater than r_min")
    if config.r_step is not None and config.r_step <= 0:
        raise ValueError("r_step must be positive")
    initial_values = {
        "initial_scale": config.initial_scale,
        "initial_qdamp": config.initial_qdamp,
        "initial_qbroad": config.initial_qbroad,
        "initial_delta2": config.initial_delta2,
    }
    for name, value in initial_values.items():
        if not math.isfinite(float(value)):
            raise ValueError(f"{name} must be finite")
    if config.initial_qdamp < 0 or config.initial_qbroad < 0:
        raise ValueError("initial qdamp and qbroad cannot be negative")
