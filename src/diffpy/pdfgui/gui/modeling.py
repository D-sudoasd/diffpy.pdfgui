"""wxPython workbench for unified PDF modeling backends."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import wx

from diffpy.pdfgui.analysis.ai import AIClientError, OpenAICompatibleClient
from diffpy.pdfgui.gui.aianalysis import AISettingsDialog
from diffpy.pdfgui.modeling.models import ModelingPlan, ModelingRequest
from diffpy.pdfgui.modeling.planner import build_modeling_ai_prompt, plan_modeling
from diffpy.pdfgui.modeling.registry import detect_backends
from diffpy.pdfgui.modeling.srreal_adapter import SrRealSimulationConfig, simulate_structure_pdf


def install_modeling_workbench(frame: wx.Frame) -> None:
    """Add engine discovery, workflow planning, and SrReal simulation to PDFgui."""

    if hasattr(frame, "_pdfgui_modeling_installed"):
        return
    menu = getattr(frame, "_pdfgui_ai_menu", None)
    if menu is None:
        menu = wx.Menu()
        position = max(0, frame.menuBar.GetMenuCount() - 1)
        frame.menuBar.Insert(position, menu, "&Analysis")
        frame._pdfgui_ai_menu = menu
        frame.menulength = frame.menuBar.GetMenuCount()
    menu.AppendSeparator()
    status_item = menu.Append(wx.ID_ANY, "Modeling engine status...")
    planner_item = menu.Append(wx.ID_ANY, "Plan modeling workflow...")
    simulation_item = menu.Append(wx.ID_ANY, "Simulate PDF with SrReal...")
    frame.Bind(wx.EVT_MENU, lambda event: _show_status(frame), status_item)
    frame.Bind(wx.EVT_MENU, lambda event: _show_planner(frame), planner_item)
    frame.Bind(wx.EVT_MENU, lambda event: _show_srreal(frame), simulation_item)
    frame._pdfgui_modeling_installed = True


def _show_status(parent: wx.Window) -> None:
    dialog = BackendStatusDialog(parent)
    dialog.ShowModal()
    dialog.Destroy()


def _show_planner(parent: wx.Window) -> None:
    window = ModelingPlannerFrame(parent)
    window.Show()


def _show_srreal(parent: wx.Window) -> None:
    window = SrRealSimulationFrame(parent)
    window.Show()


class BackendStatusDialog(wx.Dialog):
    """Display installed, missing, and externally configured modeling engines."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent, title="PDF modeling engines", size=(980, 560))
        panel = wx.Panel(self)
        self.statuses = detect_backends()
        self.list_ctrl = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
        columns = (
            ("Engine", 150),
            ("State", 100),
            ("Version", 100),
            ("Integration", 150),
            ("Capabilities", 390),
        )
        for index, (label, width) in enumerate(columns):
            self.list_ctrl.InsertColumn(index, label, width=width)
        for row, status in enumerate(self.statuses):
            self.list_ctrl.InsertItem(row, status.display_name)
            self.list_ctrl.SetItem(row, 1, status.state)
            self.list_ctrl.SetItem(row, 2, status.version or "-")
            self.list_ctrl.SetItem(row, 3, status.integration_mode)
            self.list_ctrl.SetItem(row, 4, ", ".join(status.capabilities))
        self.details = wx.TextCtrl(
            panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
            size=(-1, 150),
        )
        self.list_ctrl.Bind(wx.EVT_LIST_ITEM_SELECTED, self._on_selected)
        close_button = wx.Button(panel, id=wx.ID_CLOSE)
        close_button.Bind(wx.EVT_BUTTON, lambda event: self.EndModal(wx.ID_CLOSE))
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self.list_ctrl, 1, wx.ALL | wx.EXPAND, 8)
        sizer.Add(self.details, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 8)
        sizer.Add(close_button, 0, wx.ALIGN_RIGHT | wx.LEFT | wx.RIGHT | wx.BOTTOM, 8)
        panel.SetSizer(sizer)
        if self.statuses:
            self.list_ctrl.Select(0)

    def _on_selected(self, event: wx.ListEvent) -> None:
        status = self.statuses[event.GetIndex()]
        lines = [
            f"Backend: {status.display_name}",
            f"State: {status.state}",
            f"License: {status.license_name}",
            f"Detail: {status.detail}",
        ]
        if status.install_hint:
            lines.append(f"Installation/configuration: {status.install_hint}")
        if status.executable:
            lines.append(f"Executable: {status.executable}")
        if status.python_executable:
            lines.append(f"Python executable: {status.python_executable}")
        self.details.SetValue("\n".join(lines))


class ModelingPlannerFrame(wx.Frame):
    """Build and explain a deterministic modeling workflow."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent, title="PDF modeling workflow planner", size=(980, 760))
        self.host_frame = parent
        self.statuses = detect_backends()
        self.current_request: ModelingRequest | None = None
        self.current_plan: ModelingPlan | None = None
        self.data_files: list[str] = []

        panel = wx.Panel(self)
        self.sample_kind = wx.Choice(
            panel,
            choices=("crystalline", "nanocrystalline", "disordered", "amorphous", "molecular"),
        )
        self.sample_kind.SetSelection(0)
        self.goal = wx.Choice(
            panel,
            choices=(
                "auto",
                "small_box_refinement",
                "custom_refinement",
                "pdf_simulation",
                "series_comparison",
                "large_box_modeling",
            ),
        )
        self.goal.SetSelection(0)
        self.backend_ids = [None] + [status.backend_id for status in self.statuses]
        self.backend = wx.Choice(
            panel,
            choices=["Automatic"] + [status.display_name for status in self.statuses],
        )
        self.backend.SetSelection(0)
        self.structure = wx.FilePickerCtrl(
            panel,
            message="Select a structure model",
            wildcard="Structure files (*.cif;*.stru;*.xyz;*.pdb)|*.cif;*.stru;*.xyz;*.pdb|All files (*.*)|*.*",
            style=wx.FLP_OPEN | wx.FLP_FILE_MUST_EXIST | wx.FLP_USE_TEXTCTRL,
        )
        self.data_text = wx.TextCtrl(panel, style=wx.TE_READONLY)
        data_button = wx.Button(panel, label="Select PDF data...")
        data_button.Bind(wx.EVT_BUTTON, self._select_data)
        self.non_periodic = wx.CheckBox(panel, label="Treat the structure as non-periodic")
        self.custom_constraints = wx.CheckBox(panel, label="Require custom constraints or restraints")

        form = wx.FlexGridSizer(cols=2, vgap=8, hgap=10)
        for label, control in (
            ("Sample type", self.sample_kind),
            ("Goal", self.goal),
            ("Preferred backend", self.backend),
            ("Structure model", self.structure),
        ):
            form.Add(wx.StaticText(panel, label=label), 0, wx.ALIGN_CENTER_VERTICAL)
            form.Add(control, 1, wx.EXPAND)
        form.Add(wx.StaticText(panel, label="PDF data"), 0, wx.ALIGN_CENTER_VERTICAL)
        data_row = wx.BoxSizer(wx.HORIZONTAL)
        data_row.Add(self.data_text, 1, wx.RIGHT | wx.EXPAND, 6)
        data_row.Add(data_button, 0)
        form.Add(data_row, 1, wx.EXPAND)
        form.AddGrowableCol(1)

        self.plan_output = wx.TextCtrl(
            panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
        )
        self.question = wx.TextCtrl(panel, style=wx.TE_MULTILINE, size=(-1, 70))
        self.ai_output = wx.TextCtrl(
            panel,
            style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2,
            size=(-1, 130),
        )
        self.ai_status = wx.StaticText(panel, label="AI explanation is optional.")
        build_button = wx.Button(panel, label="Build plan")
        copy_button = wx.Button(panel, label="Copy AI prompt")
        self.ask_button = wx.Button(panel, label="Ask AI")
        settings_button = wx.Button(panel, label="AI settings")
        close_button = wx.Button(panel, id=wx.ID_CLOSE)
        build_button.Bind(wx.EVT_BUTTON, self._build_plan)
        copy_button.Bind(wx.EVT_BUTTON, self._copy_prompt)
        self.ask_button.Bind(wx.EVT_BUTTON, self._ask_ai)
        settings_button.Bind(wx.EVT_BUTTON, self._settings)
        close_button.Bind(wx.EVT_BUTTON, lambda event: self.Close())

        actions = wx.BoxSizer(wx.HORIZONTAL)
        for button in (build_button, copy_button, self.ask_button, settings_button):
            actions.Add(button, 0, wx.RIGHT, 8)
        actions.AddStretchSpacer()
        actions.Add(close_button, 0)

        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(form, 0, wx.ALL | wx.EXPAND, 10)
        sizer.Add(self.non_periodic, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        sizer.Add(self.custom_constraints, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 10)
        sizer.Add(wx.StaticText(panel, label="Deterministic plan"), 0, wx.LEFT | wx.RIGHT, 10)
        sizer.Add(self.plan_output, 1, wx.ALL | wx.EXPAND, 10)
        sizer.Add(wx.StaticText(panel, label="Question for AI explanation"), 0, wx.LEFT | wx.RIGHT, 10)
        sizer.Add(self.question, 0, wx.ALL | wx.EXPAND, 10)
        sizer.Add(self.ai_status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        sizer.Add(self.ai_output, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        sizer.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 10)
        panel.SetSizer(sizer)

    def _select_data(self, event: wx.CommandEvent) -> None:
        wildcard = "PDF data (*.gr;*.dat;*.txt;*.csv)|*.gr;*.dat;*.txt;*.csv|All files (*.*)|*.*"
        with wx.FileDialog(
            self,
            "Select PDF data",
            wildcard=wildcard,
            style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE,
        ) as dialog:
            if dialog.ShowModal() != wx.ID_OK:
                return
            self.data_files = dialog.GetPaths()
        self.data_text.SetValue("; ".join(Path(path).name for path in self.data_files))

    def _request(self) -> ModelingRequest:
        structure = self.structure.GetPath().strip() or None
        backend = self.backend_ids[self.backend.GetSelection()]
        return ModelingRequest(
            sample_kind=self.sample_kind.GetStringSelection(),
            goal=self.goal.GetStringSelection(),
            structure_file=structure,
            data_files=tuple(self.data_files),
            preferred_backend=backend,
            periodic=not self.non_periodic.GetValue(),
            custom_constraints=self.custom_constraints.GetValue(),
        )

    def _build_plan(self, event: wx.CommandEvent | None = None) -> None:
        try:
            request = self._request()
            plan = plan_modeling(request, self.statuses)
        except ValueError as error:
            _message(self, str(error))
            return
        self.current_request = request
        self.current_plan = plan
        self.plan_output.SetValue(_plan_text(plan))

    def _prompt(self) -> str:
        if self.current_request is None or self.current_plan is None:
            self._build_plan()
        if self.current_request is None or self.current_plan is None:
            raise ValueError("a valid modeling plan is required")
        return build_modeling_ai_prompt(
            self.current_request,
            self.current_plan,
            self.statuses,
            question=self.question.GetValue(),
            language="简体中文",
        )

    def _copy_prompt(self, event: wx.CommandEvent) -> None:
        try:
            prompt = self._prompt()
        except ValueError as error:
            _message(self, str(error))
            return
        if wx.TheClipboard.Open():
            try:
                wx.TheClipboard.SetData(wx.TextDataObject(prompt))
                self.ai_status.SetLabel("AI prompt copied.")
            finally:
                wx.TheClipboard.Close()
        else:
            self.ai_status.SetLabel("Could not open the clipboard.")

    def _ask_ai(self, event: wx.CommandEvent) -> None:
        settings = getattr(self.host_frame, "_pdfgui_ai_settings", None)
        if settings is None or not settings.endpoint or not settings.model:
            self._settings(event)
            settings = getattr(self.host_frame, "_pdfgui_ai_settings", None)
        if settings is None or not settings.endpoint or not settings.model:
            return
        try:
            prompt = self._prompt()
        except ValueError as error:
            _message(self, str(error))
            return
        self.ask_button.Disable()
        self.ai_status.SetLabel("Request in progress...")
        self.ai_output.SetValue("")

        def worker() -> None:
            try:
                response = OpenAICompatibleClient(settings).ask(prompt)
            except AIClientError as error:
                wx.CallAfter(self._finish_ai, "", str(error))
            else:
                wx.CallAfter(self._finish_ai, response, "")

        threading.Thread(target=worker, name="pdfgui-modeling-ai", daemon=True).start()

    def _finish_ai(self, response: str, error: str) -> None:
        self.ask_button.Enable()
        if error:
            self.ai_status.SetLabel(error)
            return
        self.ai_output.SetValue(response)
        self.ai_status.SetLabel("AI explanation received.")

    def _settings(self, event: wx.CommandEvent) -> None:
        settings = getattr(self.host_frame, "_pdfgui_ai_settings", None)
        if settings is None:
            _message(self, "AI analysis settings have not been initialized.")
            return
        with AISettingsDialog(self, settings) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                dialog.apply()
                self.ai_status.SetLabel("AI settings updated for this session.")


class SrRealSimulationFrame(wx.Frame):
    """Configure and run a periodic or Debye PDF simulation."""

    def __init__(self, parent: wx.Window):
        super().__init__(parent, title="SrReal PDF simulation", size=(760, 520))
        panel = wx.Panel(self)
        self.structure = wx.FilePickerCtrl(
            panel,
            message="Select a structure model",
            wildcard="Structure files (*.cif;*.stru;*.xyz;*.pdb)|*.cif;*.stru;*.xyz;*.pdb|All files (*.*)|*.*",
            style=wx.FLP_OPEN | wx.FLP_FILE_MUST_EXIST | wx.FLP_USE_TEXTCTRL,
        )
        self.output = wx.FilePickerCtrl(
            panel,
            message="Save calculated PDF",
            wildcard="PDF data (*.gr)|*.gr|Text data (*.dat)|*.dat|All files (*.*)|*.*",
            style=wx.FLP_SAVE | wx.FLP_OVERWRITE_PROMPT | wx.FLP_USE_TEXTCTRL,
        )
        self.mode = wx.Choice(panel, choices=("periodic", "debye"))
        self.mode.SetSelection(0)
        self.stype = wx.Choice(panel, choices=("X", "N", "E"))
        self.stype.SetSelection(0)
        defaults = {
            "qmin": "0",
            "qmax": "25",
            "rmin": "0",
            "rmax": "30",
            "rstep": "0.01",
            "qdamp": "0",
            "qbroad": "0",
            "scale": "1",
        }
        self.numeric = {name: wx.TextCtrl(panel, value=value) for name, value in defaults.items()}

        form = wx.FlexGridSizer(cols=2, vgap=8, hgap=10)
        form.Add(wx.StaticText(panel, label="Structure"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.structure, 1, wx.EXPAND)
        form.Add(wx.StaticText(panel, label="Output"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.output, 1, wx.EXPAND)
        form.Add(wx.StaticText(panel, label="Mode"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.mode, 0)
        form.Add(wx.StaticText(panel, label="Scattering type"), 0, wx.ALIGN_CENTER_VERTICAL)
        form.Add(self.stype, 0)
        for name in defaults:
            form.Add(wx.StaticText(panel, label=name), 0, wx.ALIGN_CENTER_VERTICAL)
            form.Add(self.numeric[name], 1, wx.EXPAND)
        form.AddGrowableCol(1)

        self.status = wx.StaticText(panel, label="The calculation runs in a worker thread.")
        self.run_button = wx.Button(panel, label="Run simulation")
        close_button = wx.Button(panel, id=wx.ID_CLOSE)
        self.run_button.Bind(wx.EVT_BUTTON, self._run)
        close_button.Bind(wx.EVT_BUTTON, lambda event: self.Close())
        actions = wx.BoxSizer(wx.HORIZONTAL)
        actions.Add(self.run_button, 0, wx.RIGHT, 8)
        actions.AddStretchSpacer()
        actions.Add(close_button, 0)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(form, 1, wx.ALL | wx.EXPAND, 12)
        sizer.Add(self.status, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        sizer.Add(actions, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 12)
        panel.SetSizer(sizer)

    def _config(self) -> SrRealSimulationConfig:
        values = {name: float(control.GetValue()) for name, control in self.numeric.items()}
        return SrRealSimulationConfig(
            mode=self.mode.GetStringSelection(),
            scattering_type=self.stype.GetStringSelection(),
            q_min=values["qmin"],
            q_max=values["qmax"],
            r_min=values["rmin"],
            r_max=values["rmax"],
            r_step=values["rstep"],
            qdamp=values["qdamp"],
            qbroad=values["qbroad"],
            scale=values["scale"],
        )

    def _run(self, event: wx.CommandEvent) -> None:
        structure = self.structure.GetPath().strip()
        output = self.output.GetPath().strip()
        if not structure or not output:
            _message(self, "Select a structure file and output file.")
            return
        try:
            config = self._config()
        except ValueError as error:
            _message(self, f"Invalid numerical setting: {error}")
            return
        self.run_button.Disable()
        self.status.SetLabel("Simulation in progress...")

        def worker() -> None:
            try:
                result = simulate_structure_pdf(structure, output, config)
            except (OSError, ValueError, RuntimeError) as error:
                wx.CallAfter(self._finish, None, str(error))
            else:
                wx.CallAfter(self._finish, result.to_dict(), "")

        threading.Thread(target=worker, name="pdfgui-srreal", daemon=True).start()

    def _finish(self, result: dict[str, object] | None, error: str) -> None:
        self.run_button.Enable()
        if error:
            self.status.SetLabel(error)
            return
        self.status.SetLabel(json.dumps(result, ensure_ascii=False, sort_keys=True))


def _plan_text(plan: ModelingPlan) -> str:
    lines = [
        f"Selected backend: {plan.backend_status.display_name} ({plan.backend_status.state})",
        f"Runnable now: {'yes' if plan.runnable else 'no'}",
        "",
        "Rationale:",
    ]
    lines.extend(f"- {item}" for item in plan.rationale)
    lines.extend(["", "Required inputs:"])
    lines.extend(f"- {item}" for item in plan.required_inputs)
    lines.extend(["", "Steps:"])
    lines.extend(f"{index}. {item}" for index, item in enumerate(plan.steps, start=1))
    if plan.warnings:
        lines.extend(["", "Warnings:"])
        lines.extend(f"- {item}" for item in plan.warnings)
    if plan.alternatives:
        lines.extend(["", "Available alternatives: " + ", ".join(plan.alternatives)])
    return "\n".join(lines)


def _message(parent: wx.Window, message: str) -> None:
    wx.MessageBox(message, "PDF modeling", wx.OK | wx.ICON_INFORMATION, parent)
