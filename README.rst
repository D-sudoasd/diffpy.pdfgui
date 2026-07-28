|Icon| |title|_
===============

.. |title| replace:: AI-PDFgui
.. _title: https://github.com/D-sudoasd/diffpy.pdfgui

.. |Icon| image:: https://avatars.githubusercontent.com/diffpy
        :target: https://github.com/D-sudoasd/diffpy.pdfgui
        :height: 100px

|PR|

|CI| |Black| |Tracking|

.. |Black| image:: https://img.shields.io/badge/code_style-black-black
        :target: https://github.com/psf/black

.. |CI| image:: https://github.com/D-sudoasd/diffpy.pdfgui/actions/workflows/matrix-and-codecov-on-merge-to-main.yml/badge.svg
        :target: https://github.com/D-sudoasd/diffpy.pdfgui/actions/workflows/matrix-and-codecov-on-merge-to-main.yml

.. |PR| image:: https://img.shields.io/badge/PR-Welcome-29ab47ff
        :target: https://github.com/D-sudoasd/diffpy.pdfgui/pulls

.. |Tracking| image:: https://img.shields.io/badge/issue_tracking-github-blue
        :target: https://github.com/D-sudoasd/diffpy.pdfgui/issues

Graphical user interface program for structure refinements to the atomic pair distribution function.

For users who do not have the expertise or necessity for command
line analysis, AI-PDFgui is a convenient and easy to use graphical front
end for the PDFfit2 refinement program. It is capable of full-profile
fitting of the atomic pair distribution function (PDF) derived from x-ray
or neutron diffraction data and comes with built in graphical and structure
visualization capabilities.

AI-PDFgui is a friendly interface to the PDFfit2 refinement engine, with many
powerful extensions.  To get started, please open the manual from the
help menu and follow the tutorial instructions. A detailed description
is available in `this paper <http://dx.doi.org/10.1088/0953-8984/19/33/335219>`_.

For legacy PDFgui tutorials and API details, consult the
`upstream documentation <https://diffpy.github.io/diffpy.pdfgui>`_.


AI-PDFgui preserves the ``diffpy.pdfgui`` Python import namespace, project data
formats, and the legacy ``pdfgui``, ``pdfgui-analyze``, and ``pdfgui-model``
commands. New installations also provide matching ``ai-pdfgui`` aliases.

Citation
--------

If you use AI-PDFgui in a scientific publication, we would like you to
cite this package as

        C L Farrow, P Juhas, J W Liu, D Bryndin, E S Božin,
        J Bloch, Th Proffen and S J L Billinge, PDFfit2 and PDFgui:
        computer programs for studying nanostructure in crystals, J. Phys.:
        Condens. Matter 19 (2007) 335219. doi:10.1088/0953-8984/19/33/335219

Installation
------------

Install the current AI-PDFgui from this repository
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

AI-PDFgui is not currently published as an ``AI-PDFgui`` package on PyPI or
conda-forge. Install its runtime dependencies with Conda, then install the
checked-out repository with pip so the new aliases and analysis/modeling
features come from this source tree::

        git clone https://github.com/D-sudoasd/diffpy.pdfgui.git
        cd diffpy.pdfgui
        conda create -n ai-pdfgui python=3.13
        conda activate ai-pdfgui
        conda install -c conda-forge --file requirements/conda.txt
        python -m pip install . --no-deps

The final command installs the ``AI-PDFgui`` distribution while preserving the
``diffpy.pdfgui`` Python import namespace. Verify both the new GUI alias and the
legacy-compatible command::

        ai-pdfgui --version
        pdfgui --version
        python -c "import diffpy.pdfgui; print(diffpy.pdfgui.__version__)"

Legacy package-name boundary
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The existing ``diffpy.pdfgui`` releases on PyPI and conda-forge are the legacy
upstream distribution. Installing them does not install the ``ai-pdfgui``,
``ai-pdfgui-analyze``, or ``ai-pdfgui-model`` aliases and does not provide the
AI-assisted analysis or unified modeling features in this repository.

On macOS Arm64, install ``diffpy.pdffit2`` from PyPI if a compatible conda-forge
build is unavailable, then install this repository as shown above::

        conda install -c conda-forge wxpython diffpy.utils matplotlib-base pycifrw
        python -m pip install diffpy.pdffit2
        python -m pip install . --no-deps

Optional modeling stack
~~~~~~~~~~~~~~~~~~~~~~~

For SrReal, SrFit, DiffPy-CMI, and diffpy.morph integration, use the supplied
environment and then install this repository::

        conda env create -f environment-modeling.yml
        conda activate ai-pdfgui-modeling
        python -m pip install . --no-deps

Development tests
~~~~~~~~~~~~~~~~~

From the ``diffpy.pdfgui`` repository directory, add the actual test
requirements file and run the suite::

        conda install -c conda-forge --file requirements/tests.txt
        python -m pytest

Getting Started
---------------

You may consult the `upstream documentation <https://diffpy.github.io/diffpy.pdfgui>`_ for legacy PDFgui tutorials and API references.

Support and Contribute
----------------------

`Diffpy user group <https://groups.google.com/g/diffpy-users>`_ is the discussion forum for general questions and discussions about the use of diffpy.pdfgui. Please join the diffpy.pdfgui users community by joining the Google group. The diffpy.pdfgui project welcomes your expertise and enthusiasm!

If you see a bug or want to request a feature, please `report it as an issue <https://github.com/D-sudoasd/diffpy.pdfgui/issues>`_ and/or `submit a fix as a PR <https://github.com/D-sudoasd/diffpy.pdfgui/pulls>`_. You can also post it to the `Diffpy user group <https://groups.google.com/g/diffpy-users>`_.

Feel free to fork the project and contribute. To install AI-PDFgui in
development mode, with its sources being directly used by Python
rather than copied to a package directory, use the following in the root
directory ::

        pip install -e .

To ensure code quality and to prevent accidental commits into the default branch, please set up the use of our pre-commit
hooks.

1. Install pre-commit in your working environment by running ``conda install pre-commit``.

2. Initialize pre-commit (one time only) ``pre-commit install``.

Thereafter your code will be linted by black and isort and checked against flake8 before you can commit.
If it fails by black or isort, just rerun and it should pass (black and isort will modify the files so should
pass after they are modified). If the flake8 test fails please see the error messages and fix them manually before
trying to commit again.

Improvements and fixes are always appreciated.

Before contributing, please read our `Code of Conduct <https://github.com/D-sudoasd/diffpy.pdfgui/blob/main/CODE-OF-CONDUCT.rst>`_.

Contact
-------

For more information on diffpy.pdfgui please visit the project `web-page <https://diffpy.github.io/>`_ or email the maintainers ``Simon Billinge(sbillinge@ucsb.edu)``.

Acknowledgements
----------------

``diffpy.pdfgui`` is built and maintained with `scikit-package <https://scikit-package.github.io/scikit-package/>`_.
