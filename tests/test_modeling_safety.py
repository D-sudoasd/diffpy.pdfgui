"""Safety regressions for modeling file outputs."""

from __future__ import annotations

import os

from pathlib import Path

import pytest

from diffpy.pdfgui.modeling import cli_impl
from diffpy.pdfgui.modeling.morph_adapter import compare_pdf_files
from diffpy.pdfgui.modeling.srfit_adapter import SrFitRecipeBundle, save_refined_profile
from diffpy.pdfgui.modeling.srreal_adapter import simulate_structure_pdf


def test_srreal_rejects_structure_output_collision(tmp_path: Path) -> None:
    structure = tmp_path / "model.cif"
    structure.write_text("data_model\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot overwrite the structure"):
        simulate_structure_pdf(structure, structure)


def test_morph_rejects_input_output_collision(tmp_path: Path) -> None:
    source = tmp_path / "source.gr"
    target = tmp_path / "target.gr"
    source.write_text("1 1\n2 2\n3 3\n", encoding="utf-8")
    target.write_text("1 2\n2 3\n3 4\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot overwrite either PDF input"):
        compare_pdf_files(source, target, output_file=source)


def test_srfit_rejects_profile_input_collision(tmp_path: Path) -> None:
    structure = tmp_path / "model.cif"
    data = tmp_path / "sample.gr"
    structure.write_text("data_model\n", encoding="utf-8")
    data.write_text("1 1\n2 2\n3 3\n", encoding="utf-8")
    bundle = SrFitRecipeBundle(
        recipe=None,
        contribution_name="pdf",
        structure_file=str(structure),
        data_file=str(data),
        warnings=(),
    )
    with pytest.raises(ValueError, match="cannot overwrite a structure or PDF input"):
        save_refined_profile(bundle, data)


def _sentinel_files(*paths: Path) -> dict[Path, str]:
    contents: dict[Path, str] = {}
    for index, path in enumerate(paths, start=1):
        text = f"sentinel-{index}\n"
        path.write_text(text, encoding="utf-8")
        contents[path] = text
    return contents


def _assert_sentinels_unchanged(contents: dict[Path, str]) -> None:
    for path, expected in contents.items():
        assert path.read_text(encoding="utf-8") == expected


@pytest.mark.parametrize("protected_name", ["model.cif", "first.gr", "second.gr"])
def test_plan_report_rejects_every_scientific_input_before_planning(
    tmp_path: Path,
    monkeypatch,
    protected_name: str,
) -> None:
    structure = tmp_path / "model.cif"
    first_data = tmp_path / "first.gr"
    second_data = tmp_path / "second.gr"
    sentinels = _sentinel_files(structure, first_data, second_data)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        cli_impl,
        "detect_backends",
        lambda: (_ for _ in ()).throw(AssertionError("planning must not start")),
    )

    result = cli_impl.main(
        [
            "plan",
            "--structure",
            str(structure.resolve()),
            "--data",
            str(first_data.resolve()),
            "--data",
            str(second_data.resolve()),
            "--output",
            protected_name,
        ]
    )

    assert result == 2
    _assert_sentinels_unchanged(sentinels)


@pytest.mark.parametrize("collision_target", ["structure", "primary_output"])
def test_simulate_json_rejects_input_and_primary_output_before_calculation(
    tmp_path: Path,
    monkeypatch,
    collision_target: str,
) -> None:
    structure = tmp_path / "model.cif"
    primary_output = tmp_path / "calculated.gr"
    sentinels = _sentinel_files(structure, primary_output)
    monkeypatch.setattr(
        cli_impl,
        "simulate_structure_pdf",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("simulation must not start")),
    )
    protected = structure if collision_target == "structure" else primary_output

    result = cli_impl.main(
        ["simulate", str(structure), str(primary_output), "--json-output", str(protected.resolve())]
    )

    assert result == 2
    _assert_sentinels_unchanged(sentinels)


@pytest.mark.parametrize("collision_target", ["structure", "data", "primary_output"])
def test_srfit_json_rejects_all_scientific_paths_before_recipe_build(
    tmp_path: Path,
    monkeypatch,
    collision_target: str,
) -> None:
    structure = tmp_path / "model.cif"
    data = tmp_path / "sample.gr"
    primary_output = tmp_path / "refined.dat"
    sentinels = _sentinel_files(structure, data, primary_output)
    monkeypatch.setattr(
        cli_impl,
        "build_single_phase_recipe",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("recipe must not build")),
    )
    protected = {"structure": structure, "data": data, "primary_output": primary_output}[collision_target]

    result = cli_impl.main(
        ["srfit", str(structure), str(data), str(primary_output), "--json-output", str(protected)]
    )

    assert result == 2
    _assert_sentinels_unchanged(sentinels)


@pytest.mark.parametrize("collision_target", ["source", "target", "primary_output"])
def test_morph_json_rejects_all_scientific_paths_before_comparison(
    tmp_path: Path,
    monkeypatch,
    collision_target: str,
) -> None:
    source = tmp_path / "source.gr"
    target = tmp_path / "target.gr"
    primary_output = tmp_path / "morphed.gr"
    sentinels = _sentinel_files(source, target, primary_output)
    monkeypatch.setattr(
        cli_impl,
        "compare_pdf_files",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("comparison must not start")),
    )
    protected = {"source": source, "target": target, "primary_output": primary_output}[collision_target]

    result = cli_impl.main(
        ["morph", str(source), str(target), str(primary_output), "--json-output", str(protected)]
    )

    assert result == 2
    _assert_sentinels_unchanged(sentinels)


@pytest.mark.parametrize("native_argument", ["input.cfg", "--config=input.cfg"])
def test_external_json_resolves_existing_arguments_against_workdir(
    tmp_path: Path,
    monkeypatch,
    native_argument: str,
) -> None:
    workdir = tmp_path / "run"
    workdir.mkdir()
    native_input = workdir / "input.cfg"
    sentinels = _sentinel_files(native_input)
    monkeypatch.setattr(
        cli_impl,
        "backend_map",
        lambda: (_ for _ in ()).throw(AssertionError("backend discovery must not start")),
    )

    result = cli_impl.main(
        [
            "external",
            "rmcprofile",
            "--workdir",
            str(workdir),
            "--json-output",
            str(native_input),
            "--",
            native_argument,
        ]
    )

    assert result == 2
    _assert_sentinels_unchanged(sentinels)


def test_unrelated_plan_report_remains_allowed(tmp_path: Path) -> None:
    structure = tmp_path / "model.cif"
    report = tmp_path / "plan.json"
    sentinels = _sentinel_files(structure)

    result = cli_impl.main(
        ["plan", "--structure", str(structure), "--json", "--output", str(report)]
    )

    assert result == 0
    _assert_sentinels_unchanged(sentinels)
    assert report.is_file()
    assert "selected_backend" in report.read_text(encoding="utf-8")


@pytest.mark.skipif(os.name != "nt", reason="Windows path comparison semantics")
def test_auxiliary_collision_uses_windows_case_normalization(tmp_path: Path, monkeypatch) -> None:
    structure = tmp_path / "Model.CIF"
    sentinels = _sentinel_files(structure)
    monkeypatch.setattr(
        cli_impl,
        "detect_backends",
        lambda: (_ for _ in ()).throw(AssertionError("planning must not start")),
    )

    result = cli_impl.main(
        ["plan", "--structure", str(structure), "--output", str(structure).swapcase()]
    )

    assert result == 2
    _assert_sentinels_unchanged(sentinels)
