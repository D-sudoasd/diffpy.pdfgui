Unified PDF modeling backends
=============================

This project keeps the existing PDFgui and PDFfit2 small-box workflow and adds
one interface for optional simulation, complex refinement, model-independent
comparison, and large-box modeling tools.

The integration has four layers:

* backend discovery reports installed Python packages and configured external
  executables;
* a deterministic planner selects a workflow from sample type, scientific goal,
  data count, and constraint requirements;
* in-process adapters run SrReal, SrFit, and diffpy.morph when their packages are
  available;
* an external-process adapter invokes separately installed RMCProfile or a
  fullrmc Python environment without shell command expansion.

The planner produces a staged calculation plan. It does not alter PDFgui
projects, refine parameters, or launch an external engine until the user invokes
an explicit run command.

Installation
------------

The complete DiffPy modeling stack currently requires Python 3.13 because the
published ``diffpy.srreal``, ``diffpy.srfit``, and ``diffpy.cmi`` distributions
require Python earlier than 3.14. From the repository root, create the supplied
environment and install the editable project::

    conda env create -f environment-modeling.yml
    conda activate diffpy-pdfgui-modeling

An existing Python 3.13 environment can use the project extra::

    python -m pip install -e ".[modeling]"

The equivalent requirement list is in ``requirements/modeling.txt``.

On Python 3.14, the environment markers install the compatible packages and skip
the SrReal, SrFit, and DiffPy-CMI packages. ``pdfgui-model doctor`` reports these
backends as unsupported and gives the Python 3.13 environment instruction.

RMCProfile and fullrmc
----------------------

RMCProfile is treated as a separately installed executable. It is not copied,
packaged, or redistributed by this repository. Configure its executable with::

    PDFGUI_RMCPROFILE_EXECUTABLE=/absolute/path/to/rmcprofile

fullrmc is kept in a separate Python process because its public distribution uses
the AGPL-3.0 license and can have a separate dependency stack. Configure the
interpreter that owns the fullrmc installation with::

    PDFGUI_FULLRMC_PYTHON=/absolute/path/to/fullrmc-environment/python

The external runner receives an argument list, uses ``shell=False``, validates
the working directory and timeout, captures output, and limits captured output to
4 MiB per stream. The user remains responsible for preparing version-appropriate
RMCProfile input files or a reviewed fullrmc driver script.

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
``srreal``        optional Python package         periodic and Debye PDF simulation
``srfit``         optional Python package         custom constrained refinement
``diffpy-cmi``    optional Python package         multi-model and multi-data workflows
``diffpy-morph``  optional Python package         scale/stretch/smear comparison
``rmcprofile``    external executable             large-box RMC modeling
``fullrmc``       external Python process         scripted large-box RMC modeling
================  ==============================  ==============================

Workflow planning
-----------------

Generate a plan before running a refinement::

    pdfgui-model plan \
        --sample-kind nanocrystalline \
        --goal auto \
        --structure model.cif \
        --data sample.gr

Examples of deterministic selection are:

* one crystalline data set starts with PDFgui and PDFfit2;
* multiple data sets or custom constraints select DiffPy-CMI or SrFit;
* direct structure-to-PDF calculation selects SrReal;
* related PDFs that need scale, stretch, or broadening comparison select
  diffpy.morph;
* amorphous or explicitly disordered samples select an available large-box
  backend;
* an explicit ``--backend`` selection overrides automatic selection and the plan
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

Debye calculation for a non-periodic molecular or nanoparticle model::

    pdfgui-model simulate cluster.xyz cluster.gr \
        --mode debye \
        --stype X \
        --qmax 25 \
        --rmax 40

The adapter loads the structure through ``diffpy.structure``, chooses
``PDFCalculator`` or ``DebyePDFCalculator``, validates all returned values, and
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
When an explicit space group is supplied, the recipe can also add symmetry-
allowed lattice, displacement, and positional variables. Without an explicit
space group, structural variables remain fixed and the result records a warning.

The implementation uses SciPy bounded least squares with the bounds exposed by
the SrFit recipe. The exported profile contains ``r``, observed PDF, calculated
PDF, residual, and uncertainty columns.

For multi-phase, multi-data, or multimodal refinements, use the generated plan as
the starting specification for a version-controlled DiffPy-CMI or SrFit recipe.
The project does not silently generate unconstrained multi-model refinements.

Model-independent PDF comparison
--------------------------------

Compare two related PDFs with diffpy.morph::

    pdfgui-model morph source.gr target.gr morphed.gr \
        --scale 1.0 \
        --stretch 0.0 \
        --smear 0.0 \
        --xmin 1.5 \
        --xmax 30 \
        --uncertainty \
        --json-output morph-result.json

The initial scale, stretch, and smearing values are refined by diffpy.morph
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
* ``Simulate PDF with SrReal`` for periodic or Debye structure calculations.

Long SrReal calculations and AI requests run in worker threads so the main window
remains responsive. SrFit, Morph, RMCProfile, and fullrmc runs remain explicit
command-line operations because they can be long, version-specific, and suitable
for reproducible batch directories.

Scientific checks
-----------------

A successful numerical fit does not establish a unique structure model. Preserve
and inspect at least the following information for each run:

* input files, software versions, scattering type, Q range, r range, and data
  uncertainty;
* released variables, constraints, restraints, bounds, and starting values;
* fit residuals as a function of r, parameter correlations, and alternative
  starting points;
* independent seeds and held-out observables for large-box models;
* complete external-engine input and output directories.

License and distribution boundaries
-----------------------------------

PDFgui, PDFfit2, diffpy.structure, diffpy.srreal, DiffPy-CMI, and diffpy.morph
are registered as BSD-licensed components according to their published package
metadata. The published diffpy.srfit metadata identifies a restricted-use
license. fullrmc is registered as AGPL-3.0-only. RMCProfile is registered with
external distribution terms because this repository does not supply or relicense
its executable. The status dialog exposes these labels so packaging and
redistribution decisions remain explicit.
