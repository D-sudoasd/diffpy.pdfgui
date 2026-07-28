"""Safety regressions for modeling file outputs."""

from __future__ import annotations

from pathlib import Path

import pytest

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
