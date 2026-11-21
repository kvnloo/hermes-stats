"""Load the repository root as the package `hermes_stats`, as bin/hermes-stats does, so the tests can import it."""

import importlib.util
import sys
from pathlib import Path

NAME = "hermes_stats"


def load():
    if NAME not in sys.modules:
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location(NAME, root / "__init__.py",
                                                      submodule_search_locations=[str(root)])
        package = importlib.util.module_from_spec(spec)
        sys.modules[NAME] = package
        spec.loader.exec_module(package)
    return sys.modules[NAME]
