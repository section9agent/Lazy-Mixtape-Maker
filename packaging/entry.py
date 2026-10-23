"""PyInstaller entry point."""
import multiprocessing

from lazy_mixtape_maker.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
