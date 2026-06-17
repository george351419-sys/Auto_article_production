"""Plugin loader — discovers and loads external modules.

Plugins live in the 'plugins/' directory. Each plugin is a Python file
or package that exports a DistillationPlugin subclass via a simple convention:

    from plugins import DistillationPlugin
    class MyPlugin(DistillationPlugin):
        name = "my_plugin"
        ...
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plugins import DistillationPlugin


def discover_plugins(plugins_dir: str = "plugins") -> list["DistillationPlugin"]:
    """Scan the plugins directory and load all valid plugins."""
    path = Path(plugins_dir)
    if not path.exists():
        return []

    plugins = []

    for entry in path.iterdir():
        # Skip __init__.py, loader.py, and hidden dirs
        if entry.name.startswith("_"):
            continue
        if entry.name == "loader.py":
            continue

        if entry.is_dir() and (entry / "__init__.py").exists():
            # Package
            module_name = f"plugins.{entry.name}"
        elif entry.suffix == ".py":
            # Single file
            module_name = f"plugins.{entry.stem}"
        else:
            continue

        try:
            module = importlib.import_module(module_name)
            for obj_name in dir(module):
                obj = getattr(module, obj_name)
                if isinstance(obj, type) and hasattr(obj, 'name') and obj is not DistillationPlugin:
                    try:
                        instance = obj()
                        plugins.append(instance)
                    except Exception:
                        pass  # Skip plugins that fail to instantiate
        except Exception:
            pass  # Skip broken plugins

    return plugins


def get_plugin_capabilities() -> list[dict]:
    """Return all capabilities across all loaded plugins."""
    plugins = discover_plugins()
    capabilities = []
    for p in plugins:
        for cap in p.get_capabilities():
            capabilities.append({
                "plugin": p.name,
                "capability": cap.name,
                "description": cap.description,
                "input_schema": cap.input_schema,
                "output_schema": cap.output_schema,
            })
    return capabilities
