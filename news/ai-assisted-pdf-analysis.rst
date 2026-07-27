**Added:**

* Add deterministic PDF sampling, feature, and fit-residual diagnostics in the GUI and through ``pdfgui-analyze``.
* Add Markdown and JSON report export, a diagnostic plot, and an optional OpenAI-compatible interpretation client.

**Changed:**

* Add an Analysis menu to the main PDFgui window.

**Deprecated:**

* No deprecations.

**Removed:**

* No removals.

**Fixed:**

* Handle non-object AI responses as controlled client errors and normalize invalid request timeouts.
* Detect isolated residual outliers when the median absolute deviation is zero.
* Report command-line output failures cleanly and avoid overwriting batch results with duplicate file stems.
* Keep the main-menu enable/disable count synchronized after adding the Analysis menu.

**Security:**

* AI connection settings remain session-only, and requests omit full raw data arrays.
