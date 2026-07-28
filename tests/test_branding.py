"""Regression coverage for AI-PDFgui branding and compatibility contracts."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import runpy
import sys
import tomllib
from pathlib import Path

import pytest

from diffpy.pdfgui.analysis.cli import build_parser as build_analysis_parser, main as analysis_main
from diffpy.pdfgui.branding import (
    ANALYSIS_COMMAND,
    APPLICATION_NAME,
    DISTRIBUTION_NAME,
    command_name,
    DISTRIBUTION_NAMES,
    GUI_COMMAND,
    LEGACY_ANALYSIS_COMMAND,
    LEGACY_DISTRIBUTION_NAME,
    LEGACY_GUI_COMMAND,
    LEGACY_MODELING_COMMAND,
    MODELING_COMMAND,
)
from diffpy.pdfgui.gui import pdfguiglobals
from diffpy.pdfgui.modeling.cli import build_parser as build_modeling_parser, main as modeling_main
from diffpy.pdfgui.modeling.registry import backend_map, detect_backends
from diffpy.pdfgui.version import distribution_version


ROOT = Path(__file__).resolve().parents[1]


def test_branding_constants_and_distribution_metadata():
    assert APPLICATION_NAME == "AI-PDFgui"
    assert DISTRIBUTION_NAME == "AI-PDFgui"
    assert DISTRIBUTION_NAMES == ("AI-PDFgui", "diffpy.pdfgui")
    assert pdfguiglobals.name == APPLICATION_NAME

    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert configuration["project"]["name"] == DISTRIBUTION_NAME
    assert configuration["tool"]["pytest"]["ini_options"]["pythonpath"] == ["src"]


def test_new_and_legacy_console_scripts_target_the_same_entry_points():
    configuration = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = configuration["project"]["scripts"]

    pairs = (
        (GUI_COMMAND, LEGACY_GUI_COMMAND),
        (ANALYSIS_COMMAND, LEGACY_ANALYSIS_COMMAND),
        (MODELING_COMMAND, LEGACY_MODELING_COMMAND),
    )
    for new_name, legacy_name in pairs:
        assert scripts[new_name] == scripts[legacy_name]


def test_legacy_python_namespace_and_file_formats_are_preserved():
    package = importlib.import_module("diffpy.pdfgui")
    assert package.__name__ == "diffpy.pdfgui"

    globals_source = (ROOT / "src/diffpy/pdfgui/gui/pdfguiglobals.py").read_text(encoding="utf-8")
    mainframe_source = (ROOT / "src/diffpy/pdfgui/gui/mainframe.py").read_text(encoding="utf-8")
    assert '".pdfgui_py3.cfg"' in globals_source
    assert 'iconpath("pdfgui.ico")' in mainframe_source
    assert "*.ddp;*.ddp3" in mainframe_source
    assert "*.res" in mainframe_source


def test_version_lookup_prefers_new_metadata_and_falls_back_to_legacy():
    calls: list[str] = []

    def new_metadata(name: str) -> str:
        calls.append(name)
        if name == DISTRIBUTION_NAME:
            return "5.0"
        raise importlib.metadata.PackageNotFoundError(name)

    assert distribution_version(new_metadata) == "5.0"
    assert calls == [DISTRIBUTION_NAME]

    calls.clear()

    def legacy_metadata(name: str) -> str:
        calls.append(name)
        if name == LEGACY_DISTRIBUTION_NAME:
            return "4.3"
        raise importlib.metadata.PackageNotFoundError(name)

    assert distribution_version(legacy_metadata) == "4.3"
    assert calls == [DISTRIBUTION_NAME, LEGACY_DISTRIBUTION_NAME]


def test_modeling_registry_recognizes_new_and_legacy_distribution_names():
    for installed_name in DISTRIBUTION_NAMES:

        def version_getter(name: str, *, _installed_name: str = installed_name) -> str:
            if name == _installed_name:
                return "5.1"
            raise importlib.metadata.PackageNotFoundError(name)

        mapped = backend_map(
            detect_backends(
                environ={},
                which=lambda _command: None,
                version_getter=version_getter,
                python_version=(3, 13),
            )
        )
        assert mapped["pdfgui"].display_name == APPLICATION_NAME
        assert mapped["pdfgui"].version == "5.1"


def test_cli_diagnostic_names_preserve_recognized_aliases(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", [r"C:\tools\pdfgui-analyze.exe"])
    assert build_analysis_parser().prog == LEGACY_ANALYSIS_COMMAND
    with pytest.raises(SystemExit):
        analysis_main(["missing.gr", "--max-peaks", "0"])
    assert f"{LEGACY_ANALYSIS_COMMAND}: error:" in capsys.readouterr().err

    monkeypatch.setattr(sys, "argv", [r"C:\tools\pdfgui-model.exe"])
    assert build_modeling_parser().prog == LEGACY_MODELING_COMMAND
    with pytest.raises(SystemExit):
        modeling_main(["not-a-command"])
    assert f"{LEGACY_MODELING_COMMAND}: error:" in capsys.readouterr().err


def test_cli_diagnostic_names_default_to_new_aliases(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["pytest"])
    assert build_analysis_parser().prog == ANALYSIS_COMMAND
    assert build_modeling_parser().prog == MODELING_COMMAND
    assert command_name("AI-PDFGUI-ANALYZE", ANALYSIS_COMMAND, LEGACY_ANALYSIS_COMMAND) == ANALYSIS_COMMAND
    assert (
        command_name("/usr/local/bin/pdfgui-analyze", ANALYSIS_COMMAND, LEGACY_ANALYSIS_COMMAND)
        == LEGACY_ANALYSIS_COMMAND
    )


def test_sphinx_and_project_configuration_use_current_distribution_with_legacy_fallback(monkeypatch):
    calls: list[str] = []

    def legacy_metadata(name: str) -> str:
        calls.append(name)
        if name == LEGACY_DISTRIBUTION_NAME:
            return "4.3"
        raise importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(importlib.metadata, "version", legacy_metadata)
    sphinx = runpy.run_path(str(ROOT / "docs/source/conf.py"))

    assert calls == [DISTRIBUTION_NAME, LEGACY_DISTRIBUTION_NAME]
    assert sphinx["fullversion"] == "4.3"
    assert sphinx["project"] == APPLICATION_NAME
    assert sphinx["html_title"] == "AI-PDFgui Documentation"
    assert sphinx["html_short_title"] == APPLICATION_NAME
    assert sphinx["basename"] == APPLICATION_NAME
    assert sphinx["latex_documents"][0][1:3] == ("AI-PDFgui.tex", "AI-PDFgui Documentation")
    assert sphinx["man_pages"][0][1:3] == (APPLICATION_NAME, "AI-PDFgui Documentation")
    assert sphinx["texinfo_documents"][0][1:3] == (APPLICATION_NAME, "AI-PDFgui Documentation")
    assert sphinx["modindex_common_prefix"] == ["diffpy.pdfgui"]
    assert sphinx["html_context"]["github_repo"] == "diffpy.pdfgui"

    cookiecutter = json.loads((ROOT / "cookiecutter.json").read_text(encoding="utf-8"))
    assert cookiecutter["project_name"] == APPLICATION_NAME
    assert cookiecutter["conda_pypi_package_dist_name"] == DISTRIBUTION_NAME
    assert cookiecutter["github_repo_name"] == "diffpy.pdfgui"
    assert cookiecutter["package_dir_name"] == "diffpy.pdfgui"
    assert (ROOT / "environment.yml").read_text(encoding="utf-8").startswith("name: ai-pdfgui\n")
    assert "BASENAME      = AI-PDFgui" in (ROOT / "docs/Makefile").read_text(encoding="utf-8")

    workflow_files = (ROOT / ".github/workflows").glob("*.yml")
    workflows = "\n".join(path.read_text(encoding="utf-8") for path in workflow_files)
    assert workflows.count("project: AI-PDFgui") == 7
    assert "project: diffpy.pdfgui" not in workflows

    assert sphinx["html_context"]["github_user"] == "diffpy"
