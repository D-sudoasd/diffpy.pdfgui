Unified PDF modeling backends
=============================

PDFgui retains its PDFfit2 small-box refinement workflow and adds one interface
for optional simulation, custom refinement, model-independent comparison, and
large-box modeling tools.

The integration consists of four parts:

* backend discovery for installed Python distributions and configured external
  executables;
* deterministic workflow planning from sample type, scientific goal, data count,
  and constraint requirements;
* in-process adapters for SrReal, SrFit, and diffpy.morph;
* process-isolated adapters for separately installed RMCProfile and fullrmc.

The planner does not alter a PDFgui project or start a refinement. A calculation
runs only after an explicit GUI or command-line action.

Installation
------------

Use the supplied conda-forge environment for the complete DiffPy modeling stack.
It resolves compiled libraries such as ``libdiffpy`` together with SrReal. The
currently published SrReal, SrFit, and DiffPy-CMI distributions require Python
earlier than 3.14, so the environment pins Python 3.13::

    micromamba create -f environment-modeling.yml
    micromamba activate diffpy-pdfgui-modeling
    python -m pip install . --no-deps
    pdfgui-model doctor

The same environment file works with Conda::

    conda env create -f environment-modeling.yml
    conda activate diffpy-pdfgui-modeling
    python -m pip install . --no-deps

A normal source installation is used after the conda-forge environment is
created. PEP 660 editable installation can conflict with the shared ``diffpy``
package namespace when several DiffPy distributions are installed together.
Developers who need editable sources can place the repository ``src`` directory
at the front of ``PYTHONPATH`` and run the test suite before packaging.

The environment installs these components from conda-forge:

* ``diffpy.pdffit2``;
* ``diffpy.structure``;
* ``diffpy.utils``;
* ``diffpy.srreal`` and its compiled dependencies;
* ``diffpy.srfit``;
* ``diffpy.cmi``;
* ``diffpy.morph``;
* NumPy, SciPy, Matplotlib, and wxPython.

``requirements/modeling.txt`` is retained as a pip fallback for platforms where
the published wheels and required runtime libraries are already available. The
conda-forge environment is the tested complete installation path.

On Python 3.14, ``pdfgui-model doctor`` reports SrReal, SrFit, and DiffPy-CMI as
unsupported and points to the Python 3.13 modeling environment. PDFgui itself
continues to use the Python range declared in ``pyproject.toml``.

RMCProfile and fullrmc
----------------------

RMCProfile is treated as a separately installed executable. It is not copied,
packaged, or redistributed by this repository. Configure it with::

    PDFGUI_RMCPROFILE_EXECUTABLE=/absolute/path/to/rmcprofile

fullrmc is kept in a separate Python process because it has its own dependency
stack and is distributed under AGPL-3.0. Configure the interpreter that owns the
fullrmc installation with::

    PDFGUI_FULLRMC_PYTHON=/absolute/path/to/fullrmc-environment/python

The external runner receives an argument list, uses ``shell=False``, validates
the working directory, timeout, and environment overrides, writes process output
to temporary files, and reads at most 4 MiB from each stream. Users prepare
version-appropriate RMCProfile inputs or a reviewed fullrmc driver script.

Backend status
--------------

Inspect the active environment with::

    pdfgui-model doctor
    pdfgui-model doctor --json --output backend-status.json

The stable backend identifiers are:

================  ==============================  ==============================
Identifier        Integration                     Main role
================  ==============================  ==============================
``pdfgui``        built in                        small-box PDF refinement
``pdffit2``       in-process dependency           PDFgui refinement engine
``structure``     optional Python package         structure I/O and symmetry
``srreal``        optional Python package         periodic and Debye simulation
``srfit``         optional Python package         custom constrained refinement
``diffpy-cmi``    optional Python package         multi-model and multi-data work
``diffpy-morph``  optional Python package         scale/stretch/smear comparison
``rmcprofile``    external executable             large-box RMC modeling
``fullrmc``       external Python process         scripted large-box RMC modeling
================  ==============================  ==============================

Workflow planning
-----------------

Generate a staged plan before running a model::

    pdfgui-model plan \
        --sample-kind nanocrystalline \
        --goal auto \
        --structure model.cif \
        --data sample.gr

The deterministic selection rules are:

* one crystalline data set starts with PDFgui and PDFfit2;
* multiple data sets or custom constraints select DiffPy-CMI or SrFit;
* direct structure-to-PDF calculation selects SrReal;
* related PDFs requiring scale, stretch, or broadening comparison select
  diffpy.morph;
* amorphous or explicitly disordered samples select an available large-box
  backend;
* an explicit ``--backend`` value overrides automatic selection and the plan
  reports whether that backend is usable.

The planner can emit JSON or a bounded AI explanation prompt::

    pdfgui-model plan --sample-kind amorphous --goal large_box_modeling --json

    pdfgui-model plan \
        --sample-kind nanocrystalline \
        --structure model.cif \
        --data sample.gr \
        --ai-prompt \
        --language "简体中文" \
        --output modeling-prompt.txt

The prompt contains backend status, staged steps, warnings, and bounded metadata.
It excludes raw PDF arrays and structure contents and reduces local paths to file
names.

SrReal simulation
-----------------

Periodic crystal calculation::

    pdfgui-model simulate model.cif calculated.gr \
        --mode periodic \
        --stype X \
        --qmax 25 \
        --rmin 0.5 \
        --rmax 30 \
        --rstep 0.01 \
        --qdamp 0.04 \
        --qbroad 0.01

Debye calculation for a molecular or non-periodic nanoparticle model::

    pdfgui-model simulate cluster.xyz cluster.gr \
        --mode debye \
        --stype X \
        --qmax 25 \
        --rmax 40

The adapter loads the structure through ``diffpy.structure``, selects
``PDFCalculator`` or ``DebyePDFCalculator``, validates returned arrays, and
atomically writes a two-column ``r, G(r)`` file.

SrFit refinement
----------------

Run a controlled single-phase recipe::

    pdfgui-model srfit model.cif sample.gr refined-profile.dat \
        --space-group "Fm-3m" \
        --rmax 20 \
        --max-nfev 1000 \
        --json-output refined-parameters.json

The adapter loads data through ``PDFParser``, constructs a ``PDFGenerator`` or
``DebyePDFGenerator``, and refines scale, ``qdamp``, ``qbroad``, and ``delta2``.
When an explicit space group is supplied, the recipe can add symmetry-allowed
lattice, displacement, and positional variables. Without a space group,
structural variables remain fixed and the result records a warning.

Optimization uses SciPy bounded least squares with bounds exposed by the SrFit
recipe. The exported profile contains ``r``, observed PDF, calculated PDF,
residual, and uncertainty columns.

For multi-phase, multi-data, or multimodal refinements, use the generated plan as
the starting specification for a version-controlled DiffPy-CMI or SrFit recipe.
The project does not silently create an unconstrained multi-model refinement.

Model-independent comparison
----------------------------

Compare two related PDFs with diffpy.morph::

    pdfgui-model morph source.gr target.gr morphed.gr \
        --scale 1.0 \
        --stretch 0.0 \
        --smear 0.0 \
        --xmin 1.5 \
        --xmax 30 \
        --uncertainty \
        --json-output morph-result.json

The supplied scale, stretch, and PDF-smearing values are refined by diffpy.morph
unless ``--apply-only`` is supplied.

External large-box runs
-----------------------

After configuring the external engine, pass its native argument list after
``--``::

    pdfgui-model external rmcprofile \
        --workdir rmc-run \
        --timeout 21600 \
        -- input.cfg

    pdfgui-model external fullrmc \
        --workdir fullrmc-run \
        --timeout 21600 \
        -- driver.py

No command string is evaluated by a shell. Environment overrides use repeated
``--env KEY=VALUE`` options and are validated before process creation.

Graphical interface
-------------------

The PDFgui ``Analysis`` menu contains:

* ``Modeling engine status`` for package, version, capability, license, and
  external-executable information;
* ``Plan modeling workflow`` for deterministic backend selection and optional AI
  explanation;
* ``Simulate PDF with SrReal`` for periodic or Debye calculations.

Long SrReal calculations and AI requests run in worker threads. SrFit, Morph,
RMCProfile, and fullrmc runs remain explicit command-line operations suitable for
reproducible batch directories.

Scientific checks
-----------------

A successful numerical fit does not establish a unique structure model. Preserve
and inspect these records for every run:

* input files, software versions, scattering type, Q range, r range, and data
  uncertainty;
* released variables, constraints, restraints, bounds, and starting values;
* residuals as a function of r, parameter correlations, and alternative starting
  points;
* independent seeds and held-out observables for large-box models;
* complete external-engine input and output directories.

License and distribution boundaries
-----------------------------------

PDFgui, PDFfit2, diffpy.structure, diffpy.srreal, DiffPy-CMI, and diffpy.morph
use their published BSD license metadata. SrFit is labeled
``LicenseRef-diffpy (BSD-compatible)`` to preserve the upstream package label and
its published BSD-compatible description. fullrmc is registered as
AGPL-3.0-only. RMCProfile is registered with external distribution terms because
this repository does not supply or relicense its executable. The status dialog
exposes these labels for packaging and redistribution review.
