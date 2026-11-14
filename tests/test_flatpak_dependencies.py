"""Flatpak's offline dependency set must match the reviewed application pins."""

import importlib.util
from pathlib import Path
import unittest


class FlatpakDependenciesTest(unittest.TestCase):
    def test_reviewed_dependency_pins(self):
        path = Path(__file__).resolve().parents[1] / "packaging/flatpak/gen-python-deps.py"
        spec = importlib.util.spec_from_file_location("flatpak_deps", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(set(module.TOP), {
            "Babel==2.18.0", "idasen==0.14.0", "bleak==3.1.0",
            "dbus-fast==5.2.0", "PyYAML==6.0.3", "tomlkit==0.15.2",
        })
