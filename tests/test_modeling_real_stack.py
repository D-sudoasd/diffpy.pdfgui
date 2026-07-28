"""Smoke tests against the complete conda-forge DiffPy modeling stack."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("diffpy.structure")
pytest.importorskip("diffpy.srreal.pdfcalculator")
pytest.importorskip("diffpy.srfit.fitbase")
pytest.importorskip("diffpy.morph.morphpy")

from diffpy.pdfgui.modeling.morph_adapter import MorphConfig, compare_pdf_files
from diffpy.pdfgui.modeling.srfit_adapter import (
    SrFitRecipeConfig,
    build_single_phase_recipe,
    save_refined_profile,
)
from diffpy.pdfgui.modeling.srreal_adapter import (
    SrRealSimulationConfig,
    simulate_structure_pdf,
)

_CIF = """data_Ni
_space_group_name_H-M_alt 'P 1'
_cell_length_a 3.5200
_cell_length_b 3.5200
_cell_length_c 3.5200
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
_atom_site_U_iso_or_equiv
Ni1 Ni 0 0 0 1 0.005
"""


def test_real_srreal_srfit_and_morph_adapters(tmp_path: Path) -> None:
    structure_file = tmp_path / "nickel.cif"
    structure_file.write_text(_CIF, encoding="utf-8")
    simulated_file = tmp_path / "nickel.gr"

    simulation = simulate_structure_pdf(
        structure_file,
        simulated_file,
        SrRealSimulationConfig(
            mode="periodic",
            scattering_type="X",
            q_min=0.0,
            q_max=20.0,
            r_min=0.5,
            r_max=6.0,
            r_step=0.05,
            qdamp=0.02,
        ),
    )
    simulated = np.loadtxt(simulated_file)
    assert simulation.points == simulated.shape[0]
    assert simulated.shape[1] == 2
    assert np.all(np.isfinite(simulated))

    bundle = build_single_phase_recipe(
        structure_file,
        simulated_file,
        SrFitRecipeConfig(
            periodic=True,
            scattering_type="X",
            q_min=0.0,
            q_max=20.0,
            r_min=0.5,
            r_max=6.0,
            r_step=0.05,
            refine_lattice=False,
            refine_adp=False,
            refine_positions=False,
            initial_scale=1.0,
            initial_qdamp=0.02,
            initial_qbroad=0.0,
            initial_delta2=0.0,
        ),
    )
    values = np.asarray(bundle.recipe.getValues(), dtype=float)
    residual = np.asarray(bundle.recipe.residual(values), dtype=float)
    assert residual.ndim == 1
    assert residual.size > 10
    assert np.all(np.isfinite(residual))

    refined_file = tmp_path / "nickel-refined.dat"
    save_refined_profile(bundle, refined_file)
    refined = np.loadtxt(refined_file)
    assert refined.shape[1] == 5
    assert np.all(np.isfinite(refined[:, :4]))

    morphed_file = tmp_path / "nickel-morphed.gr"
    morph_result = compare_pdf_files(
        simulated_file,
        simulated_file,
        output_file=morphed_file,
        config=MorphConfig(
            scale=1.0,
            stretch=0.0,
            smear_pdf=0.0,
            x_min=0.5,
            x_max=6.0,
            apply_only=True,
        ),
    )
    assert morph_result["points"] > 10
    assert np.loadtxt(morphed_file).shape[1] == 2
    json.dumps(morph_result, allow_nan=False)
