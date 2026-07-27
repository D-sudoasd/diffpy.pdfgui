**Added:**

* Add backend discovery for PDFgui, PDFfit2, diffpy.structure, SrReal, SrFit, DiffPy-CMI, diffpy.morph,
  RMCProfile, and fullrmc.
* Add deterministic workflow planning for small-box, custom, model-independent, and large-box PDF modeling.
* Add ``pdfgui-model`` commands for backend diagnostics, planning, SrReal simulation, SrFit refinement,
  diffpy.morph comparison, and controlled external-process execution.
* Add a PDFgui modeling workbench for backend status, workflow planning, optional AI explanation, and SrReal simulation.
* Add optional modeling requirements, a Python 3.13 environment, tests, and detailed modeling documentation.

**Changed:**

* Keep RMCProfile and fullrmc as separately installed process-isolated backends with explicit configuration.

**Deprecated:**

* No deprecations.

**Removed:**

* No removals.

**Fixed:**

* No fixes.

**Security:**

* Run external engines without shell expansion and validate commands, working directories, timeouts, environment
  overrides, and captured-output limits.
* Exclude raw PDF arrays and structure contents from modeling AI prompts and reduce local paths to file names.
