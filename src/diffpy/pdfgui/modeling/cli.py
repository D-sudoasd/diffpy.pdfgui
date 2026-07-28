"""Public command-line entry point for unified PDF modeling backends."""

from diffpy.pdfgui.modeling.cli_impl import build_parser, main

__all__ = ["build_parser", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
