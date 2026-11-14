"""Flatpak's offline dependency set must match the reviewed application pins."""

import importlib.util
import hashlib
from pathlib import Path
import tempfile
import unittest


class FlatpakDependenciesTest(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "packaging/flatpak/gen-python-deps.py"
        spec = importlib.util.spec_from_file_location("flatpak_deps", path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_reviewed_dependency_pins(self):
        self.assertEqual(set(self.module.TOP), {
            "Babel==2.18.0", "idasen==0.14.0", "bleak==3.1.0",
            "dbus-fast==5.2.0", "PyYAML==6.0.3", "tomlkit==0.15.2",
        })

    def test_rejects_wrong_bytes_and_unexpected_or_missing_wheels(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = [p.replace("-", "_").replace("==", "-") + "-py3-none-any.whl"
                     for p in self.module.TOP]
            for name in names:
                (root / name).write_bytes(b"wheel")

            def metadata(name, version):
                filename = f"{name}-{version}-py3-none-any.whl"
                return [{"filename": filename, "url": "https://example.invalid/" + filename,
                         "size": 5, "digests": {"sha256": hashlib.sha256(b"wheel").hexdigest()}}]

            self.assertEqual(len(self.module.checked_sources(root, metadata)[0]), 6)
            (root / names[0]).write_bytes(b"wrong")
            with self.assertRaisesRegex(ValueError, "bytes differ"):
                self.module.checked_sources(root, metadata)
            (root / names[0]).write_bytes(b"wheel")
            (root / "extra-1-py3-none-any.whl").write_bytes(b"wheel")
            with self.assertRaisesRegex(ValueError, "unexpected"):
                self.module.checked_sources(root, metadata)
            (root / "extra-1-py3-none-any.whl").unlink()
            (root / names[0]).unlink()
            with self.assertRaisesRegex(ValueError, "missing wheels"):
                self.module.checked_sources(root, metadata)
