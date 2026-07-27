AI-assisted PDF analysis
========================

The Analysis menu adds numerical diagnostics for atomic pair distribution
function data without changing refinement parameters.  It can analyze the
selected PDFgui data set or a separate text file.

The report includes:

* r-grid validation, gap detection, and a ``pi/Qmax`` sampling check;
* robust signal and difference-noise statistics;
* positive-peak and negative-trough detection with prominence and width;
* RMSE, MAE, Rw, weighted Rw, residual bias, autocorrelation, outliers, and
  interval-by-interval residual statistics when calculated data are present;
* Markdown and JSON export plus a diagnostic plot.

Command-line use
----------------

Analyze an experimental ``.gr`` file::

    pdfgui-analyze sample.gr --output sample-analysis.md

Analyze a file whose third column contains calculated G(r) and fourth column
contains positive uncertainties::

    pdfgui-analyze fit.dat --calculated-column 3 --sigma-column 4 \
        --output fit-analysis.json --format json

Column numbers in the command line are 1-based.  The first column is always
interpreted as r.

Optional AI interpretation
--------------------------

The AI assistant sends a bounded prompt containing the computed diagnostics,
metadata, detected features, and the user's question.  Full raw arrays are not
included.  The assistant does not alter PDFgui models or refinement parameters.

Configure a session from ``Analysis > AI connection settings`` or set these
environment variables before starting PDFgui:

``PDFGUI_AI_ENDPOINT``
    Full endpoint for an OpenAI-compatible chat-completions request.

``PDFGUI_AI_MODEL``
    Model identifier accepted by the configured endpoint.

``PDFGUI_AI_API_KEY``
    Optional bearer token.  It is held in memory for the running process and is
    not written to a project or report.

``PDFGUI_AI_TIMEOUT``
    Optional request timeout in seconds; the default is 60.

The generated prompt explicitly separates numerical observations from
structural hypotheses.  Phase identity, coordination, bond assignments, defect
chemistry, and model selection still require experimental context and an
explicit structural model.
