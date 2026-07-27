"""wxPython interface for deterministic and AI-assisted PDF diagnostics."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import numpy as np
import wx

from diffpy.pdfgui.analysis.ai import AIClientError, AISettings, OpenAICompatibleClient
from diffpy.pdfgui.analysis.core import analyze_pdf_data
from diffpy.pdfgui.analysis.io import load_pdf_data
from diffpy.pdfgui.analysis.models import PDFAnalysis, PDFSeries
from diffpy.pdfgui.analysis.report import analysis_to_json, analysis_to_markdown, build_ai_prompt


def install_ai_analysis(frame: wx.Frame) -> None:
    """Install the PDF analysis menu on an existing PDFgui main frame."""

    if hasattr(frame, "_pdfgui_ai_menu"):
        return
    menu = wx.Menu()
    selected_item = menu.Append(wx.ID_ANY, "Analyze selected PDF data...\tCtrl+Shift+A")
    file_item = menu.Append(wx.ID_ANY, "Analyze PDF data file...")
    menu.AppendSeparator()
    settings_item = menu.Append(wx.ID_ANY, "AI connection settings...")
    position = max(0, frame.menuBar.GetMenuCount() - 1)
    frame.menuBar.Insert(position, menu, "&Analysis")
    frame._pdfgui_ai_menu = menu
    frame._pdfgui_ai_settings = AISettings.from_environment()
    frame.Bind(wx.EVT_MENU, lambda event: _open_selected_dataset(frame), selected_item)
    frame.Bind(wx.EVT_MENU, lambda event: _open_data_file(frame), file_item)
    frame.Bind(wx.EVT_MENU, lambda event: _edit_ai_settings(frame), settings_item)


def _open_selected_dataset(frame: wx.Frame) -> None:
    selections = frame.treeCtrlMain.GetSelections()
    if len(selections) != 1:
        _message(frame, "Select exactly one data-set node in the Fit Tree.")
        return
    data_object = frame.treeCtrlMain.GetControlData(selections[0])
    try:
        series = _series_from_dataset(data_object)
    except (AttributeError, TypeError, ValueError) as error:
        _message(frame, f"The selected item does not contain usable PDF data.\n\n{error}")
        return
    _show_analysis(frame, series)


def _open_data_file(frame: wx.Frame) -> None:
    wildcard = "PDF data (*.gr;*.dat;*.txt;*.csv)|*.gr;*.dat;*.txt;*.csv|All files (*.*)|*.*"
    with wx.FileDialog(
        frame,
        "Open PDF data",
        wildcard=wildcard,
        style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST,
    ) as dialog:
        if dialog.ShowModal() != wx.ID_OK:
            return
        filename = dialog.GetPath()
    with ColumnSelectionDialog(frame) as columns_dialog:
        if columns_dialog.ShowModal() != wx.ID_OK:
            return
        observed_column, calculated_column, sigma_column = columns_dialog.get_columns()
    try:
        series = load_pdf_data(
            filename,
            observed_column=observed_column,
            calculated_column=calculated_column,
            sigma_column=sigma_column,
        )
    except (OSError, ValueError) as error:
        _message(frame, f"Could not read PDF data.\n\n{error}")
        return
    _show_analysis(frame, series)


def _show_analysis(frame: wx.Frame, series: PDFSeries) -> None:
    try:
        analysis = analyze_pdf_data(series)
    except ValueError as error:
        _message(frame, f"Could not analyze PDF data.\n\n{error}")
        return
    window = AIAnalysisFrame(frame, series, analysis, frame._pdfgui_ai_settings)
    window.Show()


def _edit_ai_settings(frame: wx.Frame) -> None:
    with AISettingsDialog(frame, frame._pdfgui_ai_settings) as dialog:
        if dialog.ShowModal() == wx.ID_OK:
            dialog.apply()


def _series_from_dataset(data_object: Any) -> PDFSeries:
    name = str(getattr(data_object, "name", "Selected PDF data"))
    metadata = dict(getattr(data_object, "metadata", {}) or {})
    for attribute in ("stype", "qmax", "qdamp", "qbroad", "dscale", "fitrmin", "fitrmax", "fitrstep"):
        value = getattr(data_object, attribute, None)
        if value is not None:
            metadata[attribute] = value
    refined = getattr(data_object, "refined", None)
    if isinstance(refined, dict) and refined:
        metadata["refined_parameters"] = dict(refined)

    r_observed = np.asarray(getattr(data_object, "robs", []), dtype=float)
    g_observed = np.asarray(getattr(data_object, "Gobs", []), dtype=float)
    if len(r_observed) < 3 or len(r_observed) != len(g_observed):
        raise ValueError("selected node has no complete robs/Gobs arrays")
    sigma_observed = _positive_sigma(getattr(data_object, "dGobs", None), len(r_observed))

    r_calculated = np.asarray(getattr(data_object, "rcalc", []), dtype=float)
    g_calculated = np.asarray(getattr(data_object, "Gcalc", []), dtype=float)
    g_truncated = np.asarray(getattr(data_object, "Gtrunc", []), dtype=float)
    if (
        len(r_calculated) >= 3
        and len(r_calculated) == len(g_calculated)
        and len(r_calculated) == len(g_truncated)
    ):
        sigma_truncated = _positive_sigma(getattr(data_object, "dGtrunc", None), len(r_calculated))
        return PDFSeries(
            name=name,
            r=r_calculated,
            observed=g_truncated,
            calculated=g_calculated,
            sigma=sigma_truncated,
            metadata=metadata,
            qmax=_optional_float(getattr(data_object, "qmax", None)),
            source=getattr(data_object, "filename", None),
        )

    return PDFSeries(
        name=name,
        r=r_observed,
        observed=g_observed,
        sigma=sigma_observed,
        metadata=metadata,
        qmax=_optional_float(getattr(data_object, "qmax", None)),
        source=getattr(data_object, "filename", None),
    )


def _positive_sigma(values: Any, expected_length: int) -> np.ndarray | None:
    if values is None:
        return None
    array = np.asarray(values, dtype=float)
    if len(array) != expected_length or not np.any(np.isfinite(array) & (array > 0.0)):
        return None
    return array


def _optional_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) and number > 0.0 else None


class ColumnSelectionDialog(wx.Dialog):
    """Select 1-based columns for a generic data file."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent, title="PDF data columns")
        panel = wx.Panel(self)
        self.observed = wx.SpinCtrl(panel, min=1, max=100, initial=2)
        self.use_calculated = wx.CheckBox(panel, label="Calculated G(r) column")
        self.calculated = wx.SpinCtrl(panel, min=1, max=100, initial=3)
        self.calculated.Enable(False)
        self.use_sigma = wx.CheckBox(panel, label="Uncertainty column")
        self.sigma = wx.SpinCtrl(panel, min=1, max=100, initial=4)
        self.sigma.Enable(False)
        self.use_calculated.Bind(wx.EVT_CHECKBOX, lambda event: self.calculated.Enable(event.IsChecked()))
        self.use_sigma.Bind(wx.EVT_CHECKBOX, lambda event: self.sigma.Enable(event.IsChecked()))

        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=12)
        grid.Add(wx.StaticText(panel, label="Observed G(r) column"), 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.observed, 0, wx.EXPAND)
        grid.Add(self.use_calculated, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.calculated, 0, wx.EXPAND)
        grid.Add(self.use_sigma, 0, wx.ALIGN_CENTER_VERTICAL)
        grid.Add(self.sigma, 0, wx.EXPAND)
        grid.AddGrowableCol(1)

        buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(panel, label="Column numbers are 1-based; the first column is r."), 0, wx.ALL, 10)
        sizer.Add(grid, 1, wx.LEFT | wx.RIGHT | wx.EXPAND, 10)
        sizer.Add(buttons, 0, wx.ALL | wx.EXPAND, 10)
        panel.SetSizer(sizer)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizerAndFit(outer)

    def get_columns(self) -> tuple[int, int | None, int | None]:
        calculated = self.calculated.GetValue() - 1 if self.use_calculated.GetValue() else None
        sigma = self.sigma.GetValue() - 1 if self.use_sigma.GetValue() else None
        return self.observed.GetValue() - 1, calculated, sigma


class AISettingsDialog(wx.Dialog):
    """Edit session-only AI endpoint settings."""

    def __init__(self, parent: wx.Window, settings: AISettings):
        super().__init__(parent, title="AI connection settings")
        self.settings = settings
        panel = wx.Panel(self)
        self.endpoint = wx.TextCtrl(panel, value=settings.endpoint, size=(520, -1))
        self.model = wx.TextCtrl(panel, value=settings.model)
        self.api_key = wx.TextCtrl(panel, value=settings.api_key, style=wx.TE_PASSWORD)
        self.timeout = wx.SpinCtrlDouble(panel, min=1.0, max=600.0, initial=settings.timeout, inc=5.0)
        self.timeout.SetDigits(0)

        grid = wx.FlexGridSizer(cols=2, vgap=8, hgap=12)
        for label, control in (
            ("Chat-completions endpoint", self.endpoint),
            ("Model", self.model),
            ("API key", self.api_key),
            ("Timeout (s)", self.timeout),
        ):
            grid.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            grid.Add(control, 1, wx.EXPAND)
        grid.AddGrowableCol(1)
        explanation = wx.StaticText(
            panel,
            label=(
                "Settings are held only for this PDFgui session. The request contains computed "
                "diagnostics and the "
                "question; it does not include the full raw data arrays."
            ),
        )
        explanation.Wrap(620)
        buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(grid, 0, wx.ALL | wx.EXPAND, 12)
        sizer.Add(explanation, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        sizer.Add(buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        panel.SetSizer(sizer)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(panel, 1, wx.EXPAND)
        self.SetSizerAndFit(outer)

    def apply(self) -> None:
        self.settings.endpoint = self.endpoint.GetValue().strip()
        self.settings.model = self.model.GetValue().strip()
        self.settings.api_key = self.api_key.GetValue().strip()
        self.settings.timeout = float(self.timeout.GetValue())


class AIAnalysisFrame(wx.Frame):
    """Display a complete deterministic report and optional AI interpretation."""

    def __init__(
        self,
        parent: wx.Window,
        series: PDFSeries,
        analysis: PDFAnalysis,
        settings: AISettings,
    ):
        super().__init__(parent, title=f"PDF analysis — {analysis.name}", size=(920, 720))
        self.series = series
        self.analysis = analysis
        self.settings = settings
        panel = wx.Panel(self)
        notebook = wx.Notebook(panel)
        notebook.AddPage(self._build_report_page(notebook), "Report")
        notebook.AddPage(self._build_peaks_page(notebook), "Features")
        notebook.AddPage(self._build_ai_page(notebook), "AI assistant")

        plot_button = wx.Button(panel, label="Diagnostic plot")
        save_markdown_button = wx.Button(panel, label="Save Markdown")
        save_json_button = wx.Button(panel, label="Save JSON")
        close_button = wx.Button(panel, id=wx.ID_CLOSE)
        plot_button.Bind(wx.EVT_BUTTON, self._on_plot)
        save_markdown_button.Bind(wx.EVT_BUTTON, lambda event: self._save_report("markdown"))
        save_json_button.Bind(wx.EVT_BUTTON, lambda event: self._save_report("json"))
        close_button.Bind(wx.EVT_BUTTON, lambda event: self.Close())

        button_sizer = wx.BoxSizer(wx.HORIZONTAL)
        button_sizer.Add(plot_button, 0, wx.RIGHT, 8)
        button_sizer.Add(save_markdown_button, 0, wx.RIGHT, 8)
        button_sizer.Add(save_json_button, 0, wx.RIGHT, 8)
        button_sizer.AddStretchSpacer()
        button_sizer.Add(close_button, 0)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(notebook, 1, wx.ALL | wx.EXPAND, 8)
        sizer.Add(button_sizer, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
        panel.SetSizer(sizer)

    def _build_report_page(self, parent: wx.Window) -> wx.Window:
        panel = wx.Panel(parent)
        report = wx.TextCtrl(
            panel,
            value=analysis_to_markdown(self.analysis),
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
        )
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(report, 1, wx.EXPAND)
        panel.SetSizer(sizer)
        return panel

    def _build_peaks_page(self, parent: wx.Window) -> wx.Window:
        panel = wx.Panel(parent)
        features = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        for index, (label, width) in enumerate(
            (("r (Å)", 110), ("Type", 100), ("G(r)", 130), ("Prominence", 130), ("Width (Å)", 120))
        ):
            features.InsertColumn(index, label, width=width)
        for row, peak in enumerate(self.analysis.peaks):
            features.InsertItem(row, f"{peak.position:.6g}")
            features.SetItem(row, 1, peak.sign)
            features.SetItem(row, 2, f"{peak.amplitude:.6g}")
            features.SetItem(row, 3, f"{peak.prominence:.6g}")
            features.SetItem(row, 4, "n/a" if peak.width is None else f"{peak.width:.6g}")
        note = wx.StaticText(
            panel,
            label=(
                "Detected features are numerical extrema above the configured prominence threshold. "
                "They are not automatic atom-pair assignments."
            ),
        )
        note.Wrap(820)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(features, 1, wx.EXPAND)
        sizer.Add(note, 0, wx.ALL | wx.EXPAND, 8)
        panel.SetSizer(sizer)
        return panel

    def _build_ai_page(self, parent: wx.Window) -> wx.Window:
        panel = wx.Panel(parent)
        self.question = wx.TextCtrl(panel, style=wx.TE_MULTILINE, size=(-1, 90))
        self.language = wx.Choice(panel, choices=("English", "简体中文"))
        self.language.SetSelection(0)
        self.ai_output = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2)
        self.ai_status = wx.StaticText(
            panel, label="AI interpretation is optional; deterministic results are complete."
        )
        self.ask_button = wx.Button(panel, label="Ask AI")
        prompt_button = wx.Button(panel, label="Copy prompt")
        settings_button = wx.Button(panel, label="Connection settings")
        self.ask_button.Bind(wx.EVT_BUTTON, self._on_ask_ai)
        prompt_button.Bind(wx.EVT_BUTTON, self._on_copy_prompt)
        settings_button.Bind(wx.EVT_BUTTON, self._on_settings)

        language_row = wx.BoxSizer(wx.HORIZONTAL)
        language_row.Add(
            wx.StaticText(panel, label="Response language"),
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            8,
        )
        language_row.Add(self.language, 0)
        action_row = wx.BoxSizer(wx.HORIZONTAL)
        action_row.Add(self.ask_button, 0, wx.RIGHT, 8)
        action_row.Add(prompt_button, 0, wx.RIGHT, 8)
        action_row.Add(settings_button, 0)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(wx.StaticText(panel, label="Question or interpretation task"), 0, wx.BOTTOM, 4)
        sizer.Add(self.question, 0, wx.BOTTOM | wx.EXPAND, 8)
        sizer.Add(language_row, 0, wx.BOTTOM, 8)
        sizer.Add(action_row, 0, wx.BOTTOM, 8)
        sizer.Add(self.ai_status, 0, wx.BOTTOM | wx.EXPAND, 8)
        sizer.Add(self.ai_output, 1, wx.EXPAND)
        panel.SetSizer(sizer)
        return panel

    def _prompt(self) -> str:
        return build_ai_prompt(
            self.analysis,
            question=self.question.GetValue(),
            language=self.language.GetStringSelection(),
        )

    def _on_ask_ai(self, event: wx.CommandEvent) -> None:
        if not self.settings.endpoint or not self.settings.model:
            self._on_settings(event)
            if not self.settings.endpoint or not self.settings.model:
                return
        self.ask_button.Disable()
        self.ai_status.SetLabel("Request in progress...")
        self.ai_output.SetValue("")
        prompt = self._prompt()

        def worker() -> None:
            try:
                response = OpenAICompatibleClient(self.settings).ask(prompt)
            except AIClientError as error:
                wx.CallAfter(self._finish_ai, "", str(error))
            else:
                wx.CallAfter(self._finish_ai, response, "")

        threading.Thread(target=worker, name="pdfgui-ai-request", daemon=True).start()

    def _finish_ai(self, response: str, error: str) -> None:
        self.ask_button.Enable()
        if error:
            self.ai_status.SetLabel(error)
            return
        self.ai_output.SetValue(response)
        self.ai_status.SetLabel("AI response received.")

    def _on_copy_prompt(self, event: wx.CommandEvent) -> None:
        data = wx.TextDataObject(self._prompt())
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(data)
                self.ai_status.SetLabel("Prompt copied to the clipboard.")
            finally:
                wx.TheClipboard.Close()
        else:
            self.ai_status.SetLabel("Could not open the clipboard.")

    def _on_settings(self, event: wx.CommandEvent) -> None:
        with AISettingsDialog(self, self.settings) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                dialog.apply()
                self.ai_status.SetLabel("AI connection settings updated for this session.")

    def _save_report(self, output_format: str) -> None:
        extension = "json" if output_format == "json" else "md"
        wildcard = "JSON (*.json)|*.json" if output_format == "json" else "Markdown (*.md)|*.md"
        default_name = f"{_safe_stem(self.analysis.name)}-analysis.{extension}"
        with wx.FileDialog(
            self,
            "Save PDF analysis",
            wildcard=wildcard,
            defaultFile=default_name,
            style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            target = Path(dialog.GetPath())
        text = analysis_to_json(self.analysis) if output_format == "json" else analysis_to_markdown(self.analysis)
        try:
            target.write_text(text, encoding="utf-8")
        except OSError as error:
            _message(self, f"Could not save report.\n\n{error}")

    def _on_plot(self, event: wx.CommandEvent) -> None:
        try:
            plot = DiagnosticPlotFrame(self, self.series, self.analysis)
        except ImportError as error:
            _message(self, f"Matplotlib plotting is unavailable.\n\n{error}")
            return
        plot.Show()


class DiagnosticPlotFrame(wx.Frame):
    """Plot observed, calculated, residual, and detected-feature positions."""

    def __init__(self, parent: wx.Window, series: PDFSeries, analysis: PDFAnalysis):
        from matplotlib.backends.backend_wxagg import FigureCanvasWxAgg, NavigationToolbar2WxAgg
        from matplotlib.figure import Figure

        super().__init__(parent, title=f"PDF diagnostic plot — {analysis.name}", size=(900, 650))
        figure = Figure()
        r = np.asarray(series.r, dtype=float)
        observed = np.asarray(series.observed, dtype=float)
        mask = np.isfinite(r) & np.isfinite(observed)
        r = r[mask]
        observed = observed[mask]
        order = np.argsort(r)
        r = r[order]
        observed = observed[order]
        calculated = None
        if series.calculated is not None:
            calculated_array = np.asarray(series.calculated, dtype=float)[mask][order]
            if len(calculated_array) == len(r):
                calculated = calculated_array

        if calculated is None:
            axes = figure.add_subplot(111)
            axes.plot(r, observed, label="Observed G(r)")
            axes.set_ylabel("G(r)")
        else:
            axes = figure.add_subplot(211)
            residual_axes = figure.add_subplot(212, sharex=axes)
            axes.plot(r, observed, label="Observed G(r)")
            axes.plot(r, calculated, label="Calculated G(r)")
            residual_axes.plot(r, observed - calculated, label="Residual")
            residual_axes.axhline(0.0, linewidth=0.8)
            residual_axes.set_xlabel("r (Å)")
            residual_axes.set_ylabel("Residual")
            residual_axes.legend()
        for peak in analysis.peaks:
            axes.axvline(peak.position, linewidth=0.7, alpha=0.35)
        axes.set_xlabel("r (Å)" if calculated is None else "")
        axes.set_ylabel("G(r)")
        axes.legend()
        figure.tight_layout()

        panel = wx.Panel(self)
        canvas = FigureCanvasWxAgg(panel, -1, figure)
        toolbar = NavigationToolbar2WxAgg(canvas)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(canvas, 1, wx.EXPAND)
        sizer.Add(toolbar, 0, wx.EXPAND)
        panel.SetSizer(sizer)


def _safe_stem(value: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in "-_." else "-" for character in value)
    return cleaned.strip("-.") or "pdf"


def _message(parent: wx.Window, message: str) -> None:
    wx.MessageBox(message, "PDF analysis", wx.OK | wx.ICON_INFORMATION, parent)
