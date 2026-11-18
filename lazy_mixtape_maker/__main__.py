import sys


def main():
    """No arguments, a .lmm or .lmv file, or --gui opens the app; anything else is the command line."""
    argv = sys.argv
    if len(argv) > 1 and argv[1] == "--stems-worker":       # the packaged app splitting stems for itself
        from . import stems_worker
        if len(argv) > 2 and argv[2] == "deep":              # ... or analysing them with All-In-One
            sys.exit(stems_worker.deep_main(argv[2:]))
        sys.exit(stems_worker.main(argv[1:]))
    if len(argv) == 1 or argv[1].lower().endswith((".lmm", ".lmv")) or argv[1] == "--gui":
        from .gui import main as gui_main

        sys.exit(gui_main([argv[0]] + argv[2:] if len(argv) > 1 and argv[1] == "--gui" else argv))
    from .cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
