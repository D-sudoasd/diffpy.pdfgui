"""Tests for unified PDF modeling backend integration."""

from __future__ import annotations

import importlib.metadata
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from diffpy.pdfgui.modeling.cli import main as modeling_main
from diffpy.pdfgui.modeling.models import BackendStatus, ModelingRequest
from diffpy.pdfgui.modeling.morph_adapter import MorphConfig, compare_pdf_files
from diffpy.pdfgui.modeling.planner import build_modeling_ai_prompt, plan_modeling
from diffpy.pdfgui.modeling.registry import backend_map, detect_backends
from diffpy.pdfgui.modeling.runner import BackendExecutionError, run_external_backend
from diffpy.pdfgui.modeling.srfit_adapter import (
    SrFitRecipeConfig,
    build_single_phase_recipe,
    optimize_recipe,
    save_refined_profile,
)
from diffpy.pdfgui.modeling.srreal_adapter import (
    SrRealSimulationConfig,
    simulate_structure_pdf,
)


def test_registry_detects_packages_external_engines_and_python_gates():
    versions = {
        "diffpy.pdfgui": "4.0",
        "diffpy.pdffit2": "1.6",
        "diffpy.structure": "3.4",
        "diffpy.srreal": "1.4",
        "diffpy.srfit": "3.2",
        "diffpy.cmi": "3.1.2",
        "diffpy.morph": "0.4",
        "fullrmc": "6.0",
    }

    def version_getter(distribution: str) -> str:
        try:
            return versions[distribution]
        except KeyError as error:
            raise importlib.metadata.PackageNotFoundError(distribution) from error

    def which(command: str) -> str | None:
        return "/opt/rmcprofile" if command == "rmcprofile" else None

    statuses = detect_backends(
        environ={},
        which=which,
        version_getter=version_getter,
        python_version=(3, 13),
    )
    mapped = backend_map(statuses)
    assert mapped["srreal"].state == "available"
    assert mapped["srfit"].license_name == "LicenseRef-diffpy (BSD-compatible)"
    assert "environment-modeling.yml" in mapped["srreal"].install_hint
    assert mapped["rmcprofile"].executable == "/opt/rmcprofile"
    assert mapped["fullrmc"].python_executable == sys.executable

    gated = backend_map(
        detect_backends(
            environ={},
            which=which,
            version_getter=version_getter,
            python_version=(3, 14),
        )
    )
    assert gated["structure"].state == "available"
    assert gated["diffpy-morph"].state == "available"
    assert gated["srreal"].state == "unsupported"
    assert gated["srfit"].state == "unsupported"
    assert gated["diffpy-cmi"].state == "unsupported"


def test_planner_selects_staged_workflows_and_bounds_ai_payload():
    statuses = (
        _status("pdfgui"),
        _status("srreal"),
        _status("srfit"),
        _status("diffpy-cmi"),
        _status("diffpy-morph"),
        _status("rmcprofile", state="external", executable="/secret/bin/rmcprofile"),
        _status("fullrmc", state="missing"),
    )
    crystalline = plan_modeling(
        ModelingRequest(
            sample_kind="crystalline",
            structure_file="/private/model.cif",
            data_files=("/private/sample.gr",),
        ),
        statuses,
    )
    assert crystalline.selected_backend == "pdfgui"

    custom = plan_modeling(
        ModelingRequest(
            sample_kind="nanocrystalline",
            data_files=("a.gr", "b.gr"),
            custom_constraints=True,
        ),
        statuses,
    )
    assert custom.selected_backend == "diffpy-cmi"

    request = ModelingRequest(
        sample_kind="amorphous",
        structure_file="/private/start.xyz",
        data_files=("/private/sample.gr",),
        metadata={
            "array": np.arange(40),
            "nonfinite": np.nan,
            "working_directory": "/secret/runs/sample",
        },
    )
    plan = plan_modeling(request, statuses)
    assert plan.selected_backend == "rmcprofile"
    prompt = build_modeling_ai_prompt(
        request,
        plan,
        statuses,
        diagnostic_summary={"raw": np.arange(40)},
    )
    assert "/private/" not in prompt
    assert "/secret/" not in prompt
    assert "start.xyz" in prompt
    assert "rmcprofile" in prompt
    assert "__truncated_items__" in prompt or "<truncated 8 item(s)>" in prompt
    json.loads(prompt.split("```json\n", 1)[1].split("\n```", 1)[0])


def test_external_runner_uses_argument_lists_and_bounds_output(tmp_path):
    status = _status(
        "fullrmc",
        state="external",
        python_executable=sys.executable,
    )
    result = run_external_backend(
        status,
        ["-c", "print('runner-ok')"],
        working_directory=tmp_path,
        timeout=10,
    )
    assert result.succeeded
    assert result.command[0] == sys.executable
    assert result.stdout.strip() == "runner-ok"

    large = run_external_backend(
        status,
        ["-c", "import sys; sys.stdout.write('x' * 4200000)"],
        working_directory=tmp_path,
        timeout=10,
    )
    assert large.succeeded
    assert large.output_truncated
    assert len(large.stdout.encode("utf-8")) <= 4 * 1024 * 1024

    with pytest.raises(BackendExecutionError, match="arguments are required"):
        run_external_backend(status, [], working_directory=tmp_path)
    with pytest.raises(BackendExecutionError, match="text, not bytes"):
        run_external_backend(status, [b"bad"], working_directory=tmp_path)
    with pytest.raises(BackendExecutionError, match="invalid environment variable"):
        run_external_backend(
            status,
            ["-c", "print(1)"],
            working_directory=tmp_path,
            extra_environment={"BAD-NAME": "1"},
        )


def test_srreal_adapter_runs_with_optional_modules(monkeypatch, tmp_path):
    calculators: list[object] = []

    class FakeCalculator:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.qdamp = None
            self.qbroad = None
            self.scatteringfactortable = None
            calculators.append(self)

        def __call__(self, structure):
            assert structure == {"loaded": "model.cif"}
            return np.array([0.0, 0.5, 1.0]), np.array([1.0, 2.0, 3.0])

    class FakeTable:
        @staticmethod
        def createByType(scattering_type):
            return f"table:{scattering_type}"

    structure_module = types.ModuleType("diffpy.structure")
    structure_module.load_structure = lambda filename: {"loaded": Path(filename).name}
    srreal_package = types.ModuleType("diffpy.srreal")
    srreal_package.__path__ = []
    calculator_module = types.ModuleType("diffpy.srreal.pdfcalculator")
    calculator_module.PDFCalculator = FakeCalculator
    calculator_module.DebyePDFCalculator = FakeCalculator
    table_module = types.ModuleType("diffpy.srreal.scatteringfactortable")
    table_module.ScatteringFactorTable = FakeTable
    monkeypatch.setitem(sys.modules, "diffpy.structure", structure_module)
    monkeypatch.setitem(sys.modules, "diffpy.srreal", srreal_package)
    monkeypatch.setitem(sys.modules, "diffpy.srreal.pdfcalculator", calculator_module)
    monkeypatch.setitem(sys.modules, "diffpy.srreal.scatteringfactortable", table_module)

    structure_file = tmp_path / "model.cif"
    structure_file.write_text("data_model\n", encoding="utf-8")
    output_file = tmp_path / "calculated.gr"
    result = simulate_structure_pdf(
        structure_file,
        output_file,
        SrRealSimulationConfig(
            mode="periodic",
            scattering_type="X",
            q_max=20,
            r_max=1,
            r_step=0.5,
            scale=2,
        ),
    )
    assert result.points == 3
    assert np.allclose(np.loadtxt(output_file)[:, 1], [2, 4, 6])
    assert calculators[0].kwargs["qmax"] == 20
    assert calculators[0].scatteringfactortable == "table:X"


def test_srfit_adapter_builds_optimizes_and_exports(monkeypatch, tmp_path):
    class Parameter:
        def __init__(self, name, value=0.0):
            self.name = name
            self.value = value

    class Profile:
        def __init__(self):
            self.x = np.array([1.0, 2.0, 3.0])
            self.y = np.array([2.0, 3.0, 4.0])
            self.dy = np.array([0.1, 0.1, 0.1])
            self.ycalc = np.zeros(3)

        def loadParsedData(self, parser):
            self.parser = parser

        def setCalculationRange(self, **kwargs):
            self.range_kwargs = kwargs

    class Parser:
        def parseFile(self, filename):
            self.filename = filename

    class Generator:
        def __init__(self, name):
            self.name = name
            self.scale = Parameter("scale")
            self.qdamp = Parameter("qdamp")
            self.qbroad = Parameter("qbroad")
            self.delta2 = Parameter("delta2")
            self.phase = object()

        def setStructure(self, structure, periodic=True):
            self.structure = structure
            self.periodic = periodic

        def setScatteringType(self, value):
            self.scattering_type = value

        def setQmin(self, value):
            self.qmin = value

        def setQmax(self, value):
            self.qmax = value

    class Contribution:
        def __init__(self, name):
            self.name = name

        def addProfileGenerator(self, generator):
            self.generator = generator

        def setProfile(self, profile, xname):
            self.profile = profile
            self.xname = xname

    class Recipe:
        def __init__(self):
            self.parameters = []

        def clearFitHooks(self):
            return None

        def addContribution(self, contribution):
            self.contribution = contribution
            setattr(self, contribution.name, contribution)

        def addVar(self, parameter, value=None, **kwargs):
            if value is not None:
                parameter.value = value
            self.parameters.append(parameter)

        def getValues(self):
            return np.array([parameter.value for parameter in self.parameters])

        def getNames(self):
            return [parameter.name for parameter in self.parameters]

        def getBounds2(self):
            count = len(self.parameters)
            return np.full(count, -np.inf), np.full(count, np.inf)

        def residual(self, values):
            for parameter, value in zip(self.parameters, values, strict=True):
                parameter.value = value
            self.contribution.profile.ycalc = self.contribution.profile.y - 0.1
            target = np.arange(len(self.parameters), dtype=float) * 0.01
            return np.asarray(values) - target

    class SymmetryParameters:
        latpars = [Parameter("a", 4.0)]
        adppars = [Parameter("Biso", 0.01)]
        xyzpars = [Parameter("x", 0.25)]

    fitbase_module = types.ModuleType("diffpy.srfit.fitbase")
    fitbase_module.FitContribution = Contribution
    fitbase_module.FitRecipe = Recipe
    fitbase_module.Profile = Profile
    pdf_module = types.ModuleType("diffpy.srfit.pdf")
    pdf_module.PDFGenerator = Generator
    pdf_module.DebyePDFGenerator = Generator
    pdf_module.PDFParser = Parser
    srfit_structure_module = types.ModuleType("diffpy.srfit.structure")
    srfit_structure_module.constrainAsSpaceGroup = lambda phase, group: SymmetryParameters()
    srfit_package = types.ModuleType("diffpy.srfit")
    srfit_package.__path__ = []
    structure_module = types.ModuleType("diffpy.structure")
    structure_module.load_structure = lambda filename: {"loaded": Path(filename).name}
    monkeypatch.setitem(sys.modules, "diffpy.srfit", srfit_package)
    monkeypatch.setitem(sys.modules, "diffpy.srfit.fitbase", fitbase_module)
    monkeypatch.setitem(sys.modules, "diffpy.srfit.pdf", pdf_module)
    monkeypatch.setitem(sys.modules, "diffpy.srfit.structure", srfit_structure_module)
    monkeypatch.setitem(sys.modules, "diffpy.structure", structure_module)

    structure_file = tmp_path / "model.cif"
    data_file = tmp_path / "sample.gr"
    structure_file.write_text("data_model\n", encoding="utf-8")
    data_file.write_text("1 2\n2 3\n3 4\n", encoding="utf-8")
    bundle = build_single_phase_recipe(
        structure_file,
        data_file,
        SrFitRecipeConfig(
            scattering_type="X",
            q_max=25,
            r_max=3,
            space_group="Fm-3m",
            refine_positions=True,
        ),
    )
    result = optimize_recipe(bundle, max_nfev=100)
    assert result["success"]
    expected = {"scale", "qdamp", "qbroad", "delta2", "a", "Biso", "x"}
    assert set(result["variables"]) >= expected
    output = tmp_path / "refined.dat"
    assert save_refined_profile(bundle, output) == str(output.resolve())
    assert np.loadtxt(output).shape == (3, 5)


def test_morph_adapter_saves_json_safe_result(monkeypatch, tmp_path):
    morph_package = types.ModuleType("diffpy.morph")
    morph_package.__path__ = []
    morphpy_module = types.ModuleType("diffpy.morph.morphpy")

    def morph(source, target, **kwargs):
        assert Path(source).name == "source.gr"
        assert Path(target).name == "target.gr"
        assert kwargs["smear_pdf"] == -0.05
        info = {"scale": np.float64(1.1), "uncertainty": np.array([0.02])}
        table = np.array([[1.0, 2.0], [2.0, 3.0], [3.0, 4.0]])
        return info, table

    morphpy_module.morph = morph
    monkeypatch.setitem(sys.modules, "diffpy.morph", morph_package)
    monkeypatch.setitem(sys.modules, "diffpy.morph.morphpy", morphpy_module)
    source = tmp_path / "source.gr"
    target = tmp_path / "target.gr"
    source.write_text("1 1\n2 2\n3 3\n", encoding="utf-8")
    target.write_text("1 2\n2 3\n3 4\n", encoding="utf-8")
    output = tmp_path / "morphed.gr"
    result = compare_pdf_files(
        source,
        target,
        output_file=output,
        config=MorphConfig(smear_pdf=-0.05),
    )
    assert result["morph_info"]["scale"] == 1.1
    assert result["morph_info"]["uncertainty"] == [0.02]
    json.dumps(result, allow_nan=False)
    assert np.loadtxt(output).shape == (3, 2)


def test_cli_and_modeling_environment_metadata(capsys):
    result = modeling_main(["plan", "--sample-kind", "crystalline", "--json"])
    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["selected_backend"] == "pdfgui"
    assert payload["runnable"] is True

    root = Path(__file__).resolve().parents[1]
    import tomllib

    configuration = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert configuration["project"]["scripts"]["pdfgui-model"].endswith("modeling.cli:main")
    modeling_requirements = configuration["project"]["optional-dependencies"]["modeling"]
    assert any(requirement.startswith("diffpy.structure") for requirement in modeling_requirements)
    assert any(requirement.startswith("diffpy.srfit") for requirement in modeling_requirements)

    environment = (root / "environment-modeling.yml").read_text(encoding="utf-8")
    assert "python=3.13" in environment
    assert "diffpy.srreal>=1.4,<2" in environment
    assert "diffpy.srfit>=3.2,<4" in environment
    assert "diffpy.cmi>=3.1.2,<4" in environment
    assert "diffpy.morph>=0.3.1,<1" in environment
    assert "-e .[modeling]" not in environment


def test_new_python_files_follow_repository_line_limit():
    root = Path(__file__).resolve().parents[1]
    paths = list((root / "src" / "diffpy" / "pdfgui" / "modeling").glob("*.py"))
    paths.append(root / "src" / "diffpy" / "pdfgui" / "gui" / "modeling.py")
    offenders = []
    for path in paths:
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if len(line) > 115:
                offenders.append(f"{path.relative_to(root)}:{line_number}:{len(line)}")
    assert not offenders, "lines exceed 115 characters: " + ", ".join(offenders)


def _status(
    backend_id: str,
    *,
    state: str = "available",
    executable: str | None = None,
    python_executable: str | None = None,
) -> BackendStatus:
    return BackendStatus(
        backend_id=backend_id,
        display_name=backend_id,
        state=state,
        version="1.0" if state != "missing" else None,
        capabilities=("test",),
        integration_mode="external-process" if state == "external" else "in-process",
        license_name="test",
        detail=f"{backend_id} {state}",
        executable=executable,
        python_executable=python_executable,
    )
