"""Load as a ComfyUI package without polluting its nodes/utils modules."""

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if "chicktools" not in sys.modules:
    spec = importlib.util.spec_from_file_location(
        "chicktools", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
    )
    plugin = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = plugin
    spec.loader.exec_module(plugin)
else:
    plugin = sys.modules["chicktools"]
