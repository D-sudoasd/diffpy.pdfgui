"""Unified optional backends for atomic PDF modeling and refinement."""

from diffpy.pdfgui.modeling.models import (
    BackendStatus,
    ExecutionResult,
    ModelingPlan,
    ModelingRequest,
    SimulationResult,
)
from diffpy.pdfgui.modeling.planner import build_modeling_ai_prompt, plan_modeling
from diffpy.pdfgui.modeling.registry import backend_map, detect_backends

__all__ = [
    "BackendStatus",
    "ExecutionResult",
    "ModelingPlan",
    "ModelingRequest",
    "SimulationResult",
    "backend_map",
    "build_modeling_ai_prompt",
    "detect_backends",
    "plan_modeling",
]
