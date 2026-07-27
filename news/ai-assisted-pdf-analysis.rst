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
* Serialize NumPy arrays, paths, non-finite metadata, and unknown metadata values without breaking report export.
* Reject overlapping r, observed, calculated, and uncertainty columns and accept Fortran-style exponents.
* Bound AI prompt metadata, remove absolute source paths, and limit endpoint response size.

**Security:**

* AI connection settings remain session-only, requests omit full raw data arrays, and endpoint URLs require HTTP or HTTPS.
