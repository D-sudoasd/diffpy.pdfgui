"""Runtime branding and compatibility names for AI-PDFgui."""

APPLICATION_NAME = "AI-PDFgui"
DISTRIBUTION_NAME = "AI-PDFgui"
LEGACY_DISTRIBUTION_NAME = "diffpy.pdfgui"
DISTRIBUTION_NAMES = (DISTRIBUTION_NAME, LEGACY_DISTRIBUTION_NAME)

GUI_COMMAND = "ai-pdfgui"
ANALYSIS_COMMAND = "ai-pdfgui-analyze"
MODELING_COMMAND = "ai-pdfgui-model"

LEGACY_GUI_COMMAND = "pdfgui"
LEGACY_ANALYSIS_COMMAND = "pdfgui-analyze"
LEGACY_MODELING_COMMAND = "pdfgui-model"


def command_name(argv0: str, primary: str, legacy: str) -> str:
    """Return a recognized console-script name or the primary alias."""

    candidate = str(argv0).replace("\\", "/").rsplit("/", 1)[-1]
    if candidate.casefold().endswith(".exe"):
        candidate = candidate[:-4]
    recognized = {
        primary.casefold(): primary,
        legacy.casefold(): legacy,
    }
    return recognized.get(candidate.casefold(), primary)
