"""Data models for unified PDF modeling backends and workflow plans."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class BackendStatus:
    """Availability and integration metadata for one modeling backend."""

    backend_id: str
    display_name: str
    state: str
    version: str | None
    capabilities: tuple[str, ...]
    integration_mode: str
    license_name: str
    detail: str
    install_hint: str | None = None
    executable: str | None = None
    python_executable: str | None = None

    @property
    def usable(self) -> bool:
        """Return whether the backend can be invoked in the current environment."""

        return self.state in {"available", "external"}

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ModelingRequest:
    """Inputs used to select and configure a PDF modeling workflow."""

    sample_kind: str = "crystalline"
    goal: str = "auto"
    structure_file: str | None = None
    data_files: tuple[str, ...] = ()
    preferred_backend: str | None = None
    periodic: bool = True
    custom_constraints: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ModelingPlan:
    """Deterministic backend selection and ordered work plan."""

    selected_backend: str
    title: str
    rationale: tuple[str, ...]
    required_inputs: tuple[str, ...]
    steps: tuple[str, ...]
    warnings: tuple[str, ...]
    alternatives: tuple[str, ...]
    backend_status: BackendStatus

    @property
    def runnable(self) -> bool:
        return self.backend_status.usable

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["runnable"] = self.runnable
        return payload


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """Captured result from an external modeling process."""

    backend_id: str
    command: tuple[str, ...]
    working_directory: str
    return_code: int
    stdout: str
    stderr: str
    timed_out: bool
    output_truncated: bool

    @property
    def succeeded(self) -> bool:
        return not self.timed_out and self.return_code == 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["succeeded"] = self.succeeded
        return payload


@dataclass(frozen=True, slots=True)
class SimulationResult:
    """Summary of a PDF simulation generated from a structure model."""

    backend_id: str
    structure_file: str
    output_file: str
    mode: str
    scattering_type: str
    points: int
    r_min: float
    r_max: float
    q_min: float
    q_max: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
