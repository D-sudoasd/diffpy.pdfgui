"""Discovery of optional in-process and external PDF modeling engines."""

from __future__ import annotations

import importlib.metadata
import os
import shutil
import sys
from collections.abc import Callable, Mapping
from pathlib import Path

from diffpy.pdfgui.branding import APPLICATION_NAME, DISTRIBUTION_NAMES
from diffpy.pdfgui.modeling.models import BackendStatus

VersionGetter = Callable[[str], str]
WhichFunction = Callable[[str], str | None]

_MODELING_ENV_HINT = (
    "Create the conda-forge environment from environment-modeling.yml, then install "
    "the project with 'python -m pip install . --no-deps'."
)


def detect_backends(
    *,
    environ: Mapping[str, str] | None = None,
    which: WhichFunction = shutil.which,
    version_getter: VersionGetter = importlib.metadata.version,
    python_version: tuple[int, int] | None = None,
) -> tuple[BackendStatus, ...]:
    """Return the modeling backends visible in the current environment."""

    env = os.environ if environ is None else environ
    pyversion = python_version or (sys.version_info.major, sys.version_info.minor)
    statuses = [
        _pdfgui_status(version_getter),
        _package_status(
            backend_id="pdffit2",
            display_name="PDFfit2",
            distribution="diffpy.pdffit2",
            capabilities=("small_box_refinement", "crystalline_pdf", "pdf_simulation"),
            license_name="BSD-3-Clause",
            install_hint="conda install -c conda-forge diffpy.pdffit2",
            version_getter=version_getter,
        ),
        _package_status(
            backend_id="structure",
            display_name="diffpy.structure",
            distribution="diffpy.structure",
            capabilities=("structure_io", "symmetry", "coordinate_conversion"),
            license_name="BSD-3-Clause",
            install_hint="conda install -c conda-forge diffpy.structure",
            version_getter=version_getter,
        ),
        _version_gated_package_status(
            backend_id="srreal",
            display_name="diffpy.srreal",
            distribution="diffpy.srreal",
            capabilities=("pdf_simulation", "debye_pdf", "bond_valence", "pair_distances"),
            license_name="BSD-3-Clause",
            install_hint=_MODELING_ENV_HINT,
            version_getter=version_getter,
            python_version=pyversion,
            maximum_exclusive=(3, 14),
        ),
        _version_gated_package_status(
            backend_id="srfit",
            display_name="diffpy.srfit",
            distribution="diffpy.srfit",
            capabilities=(
                "custom_refinement",
                "multi_dataset_refinement",
                "constraints",
                "restraints",
            ),
            license_name="LicenseRef-diffpy (BSD-compatible)",
            install_hint=_MODELING_ENV_HINT,
            version_getter=version_getter,
            python_version=pyversion,
            maximum_exclusive=(3, 14),
        ),
        _version_gated_package_status(
            backend_id="diffpy-cmi",
            display_name="DiffPy-CMI",
            distribution="diffpy.cmi",
            capabilities=("complex_modeling", "multi_modal_refinement", "workflow_packs"),
            license_name="BSD-3-Clause",
            install_hint=_MODELING_ENV_HINT,
            version_getter=version_getter,
            python_version=pyversion,
            maximum_exclusive=(3, 14),
        ),
        _package_status(
            backend_id="diffpy-morph",
            display_name="diffpy.morph",
            distribution="diffpy.morph",
            capabilities=(
                "model_independent_comparison",
                "scale_stretch_smear",
                "series_screening",
            ),
            license_name="BSD-3-Clause",
            install_hint="conda install -c conda-forge diffpy.morph",
            version_getter=version_getter,
        ),
        _rmcprofile_status(env, which),
        _fullrmc_status(env, which, version_getter),
    ]
    return tuple(statuses)


def backend_map(statuses: tuple[BackendStatus, ...] | None = None) -> dict[str, BackendStatus]:
    """Return backend status objects indexed by stable backend identifier."""

    detected = detect_backends() if statuses is None else statuses
    return {status.backend_id: status for status in detected}


def _pdfgui_status(version_getter: VersionGetter) -> BackendStatus:
    version = next(
        (
            detected_version
            for distribution in DISTRIBUTION_NAMES
            if (detected_version := _safe_version(distribution, version_getter)) is not None
        ),
        "development",
    )
    return BackendStatus(
        backend_id="pdfgui",
        display_name=APPLICATION_NAME,
        state="available",
        version=version,
        capabilities=("small_box_refinement", "project_management", "sequential_refinement"),
        integration_mode="built-in",
        license_name="BSD-3-Clause",
        detail="Built-in graphical workflow using the PDFfit2 engine.",
    )


def _package_status(
    *,
    backend_id: str,
    display_name: str,
    distribution: str,
    capabilities: tuple[str, ...],
    license_name: str,
    install_hint: str,
    version_getter: VersionGetter,
) -> BackendStatus:
    version = _safe_version(distribution, version_getter)
    if version is None:
        return BackendStatus(
            backend_id=backend_id,
            display_name=display_name,
            state="missing",
            version=None,
            capabilities=capabilities,
            integration_mode="in-process",
            license_name=license_name,
            detail=f"Python distribution {distribution!r} is not installed.",
            install_hint=install_hint,
        )
    return BackendStatus(
        backend_id=backend_id,
        display_name=display_name,
        state="available",
        version=version,
        capabilities=capabilities,
        integration_mode="in-process",
        license_name=license_name,
        detail=f"Python distribution {distribution!r} is available.",
        install_hint=install_hint,
    )


def _version_gated_package_status(
    *,
    backend_id: str,
    display_name: str,
    distribution: str,
    capabilities: tuple[str, ...],
    license_name: str,
    install_hint: str,
    version_getter: VersionGetter,
    python_version: tuple[int, int],
    maximum_exclusive: tuple[int, int],
) -> BackendStatus:
    if python_version >= maximum_exclusive:
        maximum_text = ".".join(str(part) for part in maximum_exclusive)
        return BackendStatus(
            backend_id=backend_id,
            display_name=display_name,
            state="unsupported",
            version=_safe_version(distribution, version_getter),
            capabilities=capabilities,
            integration_mode="in-process",
            license_name=license_name,
            detail=(
                f"The published package metadata requires Python earlier than {maximum_text}; "
                f"the current interpreter is {python_version[0]}.{python_version[1]}."
            ),
            install_hint=install_hint,
        )
    return _package_status(
        backend_id=backend_id,
        display_name=display_name,
        distribution=distribution,
        capabilities=capabilities,
        license_name=license_name,
        install_hint=install_hint,
        version_getter=version_getter,
    )


def _rmcprofile_status(env: Mapping[str, str], which: WhichFunction) -> BackendStatus:
    configured = env.get("PDFGUI_RMCPROFILE_EXECUTABLE", "").strip()
    executable = _resolve_command(configured, which) if configured else None
    if executable is None:
        for candidate in ("rmcprofile", "rmcprofile7", "rmcprofile.exe", "rmcprofile7.exe"):
            executable = _resolve_command(candidate, which)
            if executable:
                break
    if executable:
        return BackendStatus(
            backend_id="rmcprofile",
            display_name="RMCProfile",
            state="external",
            version=None,
            capabilities=("large_box_rmc", "disordered_modeling", "multi_data_rmc"),
            integration_mode="external-process",
            license_name="External distribution terms",
            detail="An RMCProfile executable is configured and will be invoked without shell expansion.",
            install_hint="Set PDFGUI_RMCPROFILE_EXECUTABLE to the installed executable.",
            executable=executable,
        )
    return BackendStatus(
        backend_id="rmcprofile",
        display_name="RMCProfile",
        state="missing",
        version=None,
        capabilities=("large_box_rmc", "disordered_modeling", "multi_data_rmc"),
        integration_mode="external-process",
        license_name="External distribution terms",
        detail="No RMCProfile executable was found. RMCProfile is not bundled with this repository.",
        install_hint="Install RMCProfile separately and set PDFGUI_RMCPROFILE_EXECUTABLE.",
    )


def _fullrmc_status(
    env: Mapping[str, str],
    which: WhichFunction,
    version_getter: VersionGetter,
) -> BackendStatus:
    configured_python = env.get("PDFGUI_FULLRMC_PYTHON", "").strip()
    python_executable = _resolve_command(configured_python, which) if configured_python else None
    version = _safe_version("fullrmc", version_getter)
    if python_executable is None and version is not None:
        python_executable = sys.executable
    if python_executable:
        return BackendStatus(
            backend_id="fullrmc",
            display_name="fullrmc",
            state="external",
            version=version,
            capabilities=("large_box_rmc", "disordered_modeling", "custom_constraints"),
            integration_mode="external-python-process",
            license_name="AGPL-3.0-only",
            detail="A separate Python interpreter is configured for fullrmc scripts.",
            install_hint="Set PDFGUI_FULLRMC_PYTHON to the interpreter of the fullrmc environment.",
            python_executable=python_executable,
        )
    return BackendStatus(
        backend_id="fullrmc",
        display_name="fullrmc",
        state="missing",
        version=version,
        capabilities=("large_box_rmc", "disordered_modeling", "custom_constraints"),
        integration_mode="external-python-process",
        license_name="AGPL-3.0-only",
        detail="No separate fullrmc Python environment is configured; fullrmc is not bundled.",
        install_hint="Create a dedicated fullrmc environment and set PDFGUI_FULLRMC_PYTHON.",
    )


def _safe_version(distribution: str, version_getter: VersionGetter) -> str | None:
    try:
        return version_getter(distribution)
    except importlib.metadata.PackageNotFoundError:
        return None
    except Exception:
        return None


def _resolve_command(value: str, which: WhichFunction) -> str | None:
    if not value:
        return None
    expanded = Path(value).expanduser()
    if expanded.is_absolute() or expanded.parent != Path("."):
        try:
            resolved = expanded.resolve(strict=True)
        except OSError:
            return None
        return str(resolved) if resolved.is_file() and os.access(resolved, os.X_OK) else None
    return which(value)
