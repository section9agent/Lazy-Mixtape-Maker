"""Lazy Mixtape Maker desktop app (PySide6)."""


def main(argv=None):
    import sys

    from .main_window import run

    return run(argv if argv is not None else sys.argv)
