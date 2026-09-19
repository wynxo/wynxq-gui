"""Exercise actual filesystem transactions; replace only expensive venv/pip work."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import pytest

import install as installer
import uninstall as remover


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="wynxq installer ")
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = self.base / "checkout with spaces"
        self.source.mkdir()
        (self.source / "wynxq").mkdir()
        (self.source / "wynxq/__main__.py").write_text("VERSION = 'original'\n")
        (self.source / "assets").mkdir()
        (self.source / "assets/wynxq.svg").write_text("<svg/>")
        (self.source / "native").mkdir()
        (self.source / "native/CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.20)\n")
        for name in (
            "pyproject.toml", "setup.py", "MANIFEST.in", "README.md", "LICENSE",
            "install.py", "uninstall.py",
        ):
            (self.source / name).write_text("fixture\n")
        shutil.copy2(installer.__file__, self.source / "install.py")
        shutil.copy2(remover.__file__, self.source / "uninstall.py")
        self.data = self.base / "user data"
        self.root = self.data / "wynxq-app"
        self.bin = self.base / "bin with spaces"
        self.desktop = self.data / "applications" / f"{installer.APP_ID}.desktop"
        self.icon = self.data / "icons/hicolor/scalable/apps" / f"{installer.APP_ID}.svg"
        self.env = patch.dict(os.environ, {
            "XDG_DATA_HOME": str(self.data),
            "XDG_CONFIG_HOME": str(self.base / "config"),
            "XDG_CACHE_HOME": str(self.base / "cache"),
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.builder = patch.object(installer, "_build_environment", side_effect=self.fake_build)
        self.build = self.builder.start()
        self.addCleanup(self.builder.stop)

    @staticmethod
    def fake_build(release):
        (release / "venv/bin").mkdir(parents=True)
        (release / "venv/bin/python").symlink_to("/usr/bin/python3")

    def install(self):
        return installer.install(self.source, self.root, self.bin)

    def test_install_is_copy_and_handles_spaces(self):
        launcher = self.install()
        self.assertTrue(launcher.is_symlink())
        self.assertEqual(launcher.resolve(), self.root / "wynxq")
        self.assertTrue(os.access(launcher, os.X_OK))
        self.assertIn('Exec="', self.desktop.read_text())
        self.assertIn("--uninstall", launcher.read_text())
        shutil.rmtree(self.source)
        self.assertEqual((self.root / "current/source/wynxq/__main__.py").read_text(), "VERSION = 'original'\n")

    def test_release_copy_keeps_native_build_inputs(self):
        self.install()
        release_source = self.root / "current/source"
        self.assertTrue((release_source / "setup.py").is_file())
        self.assertTrue((release_source / "MANIFEST.in").is_file())
        self.assertTrue((release_source / "native/CMakeLists.txt").is_file())

    def test_installed_uninstall_command_works_after_checkout_removed(self):
        launcher = self.install()
        shutil.rmtree(self.source)
        result = subprocess.run([str(launcher), "--uninstall"], capture_output=True, text=True, cwd=self.base)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Wynxq removed", result.stdout)
        self.assertFalse(self.root.exists())
        self.assertFalse(installer.exists(launcher))

    def test_launcher_directory_must_be_outside_install_root(self):
        with self.assertRaisesRegex(ValueError, "Launcher directory"):
            installer.install(self.source, self.root, self.root)
        self.assertFalse(self.root.exists())

    def test_failed_first_install_leaves_no_app_or_launcher(self):
        self.build.side_effect = RuntimeError("pip failed")
        with self.assertRaisesRegex(RuntimeError, "pip failed"):
            self.install()
        self.assertFalse(self.root.exists())
        self.assertFalse(installer.exists(self.bin / "wynxq"))
        self.assertFalse(self.desktop.exists())

    def test_failed_upgrade_preserves_existing_install(self):
        self.install()
        current = os.readlink(self.root / "current")
        manifest = (self.root / installer.MANIFEST).read_bytes()
        self.build.side_effect = RuntimeError("pip failed")
        with self.assertRaises(RuntimeError):
            self.install()
        self.assertEqual(os.readlink(self.root / "current"), current)
        self.assertEqual((self.root / installer.MANIFEST).read_bytes(), manifest)
        self.assertEqual(len(list((self.root / "releases").iterdir())), 1)
        self.assertTrue(self.desktop.exists())

    def test_publication_failure_rolls_back_current_and_files(self):
        self.install()
        original_manifest = (self.root / installer.MANIFEST).read_bytes()
        original_current = os.readlink(self.root / "current")
        original_icon = self.icon.read_bytes()
        real_write = installer.atomic_write
        raised = False

        def fail_once(path, data, mode=0o644):
            nonlocal raised
            if path == self.desktop and not raised:
                raised = True
                raise OSError("disk full")
            return real_write(path, data, mode)

        (self.source / "assets/wynxq.svg").write_text("<svg>changed</svg>")
        with patch.object(installer, "atomic_write", side_effect=fail_once):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.install()
        self.assertEqual((self.root / installer.MANIFEST).read_bytes(), original_manifest)
        self.assertEqual(os.readlink(self.root / "current"), original_current)
        self.assertEqual(self.icon.read_bytes(), original_icon)
        self.assertEqual(len(list((self.root / "releases").iterdir())), 1)

    def test_upgrade_reuses_owned_paths_and_keeps_running_release(self):
        self.install()
        first = (self.root / "current").resolve()
        self.install()
        self.assertNotEqual((self.root / "current").resolve(), first)
        self.assertTrue(first.exists())
        self.assertEqual(len(installer.read_manifest(self.root)["releases"]), 2)

    def test_refuses_unowned_install_directory(self):
        self.root.mkdir(parents=True)
        precious = self.root / "precious.txt"
        precious.write_text("keep me")
        with self.assertRaisesRegex(ValueError, "unowned"):
            self.install()
        self.assertEqual(precious.read_text(), "keep me")
        self.build.assert_not_called()

    def test_refuses_symlink_install_directory(self):
        victim = self.base / "important"
        victim.mkdir()
        self.root.parent.mkdir()
        self.root.symlink_to(victim, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "unowned"):
            self.install()
        self.assertTrue(victim.is_dir())
        self.assertTrue(self.root.is_symlink())

    def test_refuses_existing_launcher_without_overwriting(self):
        self.bin.mkdir()
        launcher = self.bin / "wynxq"
        launcher.write_text("some other program")
        with self.assertRaisesRegex(ValueError, "does not recognise"):
            self.install()
        self.assertEqual(launcher.read_text(), "some other program")
        self.assertFalse(self.root.exists())

    def test_refuses_modified_desktop_entry_on_upgrade(self):
        self.install()
        self.desktop.write_text("my custom desktop entry")
        current = os.readlink(self.root / "current")
        with self.assertRaisesRegex(ValueError, "does not recognise"):
            self.install()
        self.assertEqual(self.desktop.read_text(), "my custom desktop entry")
        self.assertEqual(os.readlink(self.root / "current"), current)

    def test_uninstall_keeps_data_and_modified_external_file(self):
        self.install()
        (self.data / "wynxq").mkdir()
        history = self.data / "wynxq/history.db"
        history.write_text("my conversations")
        self.desktop.write_text("my modified entry")
        messages = remover.uninstall(self.root)
        self.assertFalse(self.root.exists())
        self.assertFalse(installer.exists(self.bin / "wynxq"))
        self.assertEqual(history.read_text(), "my conversations")
        self.assertEqual(self.desktop.read_text(), "my modified entry")
        self.assertTrue(any("Kept modified" in item for item in messages))

    def test_purge_removes_only_app_data_and_never_follows_data_symlink(self):
        self.install()
        (self.data / "wynxq").mkdir()
        (self.data / "wynxq/history.db").write_text("history")
        models = self.data / "ollama"
        models.mkdir()
        (models / "model.gguf").write_text("model")
        config = self.base / "config"
        config.mkdir()
        (config / "wynxq").symlink_to(models, target_is_directory=True)
        messages = remover.uninstall(self.root, purge=True)
        self.assertFalse((self.data / "wynxq").exists())
        self.assertEqual((models / "model.gguf").read_text(), "model")
        self.assertTrue(any("symlink" in message for message in messages))

    def test_uninstall_preserves_unknown_install_files(self):
        self.install()
        unknown = self.root / "personal.txt"
        unknown.write_text("keep")
        messages = remover.uninstall(self.root)
        self.assertEqual(unknown.read_text(), "keep")
        self.assertTrue(any("unknown files" in message for message in messages))

    def test_uninstall_refuses_symlink_releases(self):
        self.install()
        shutil.rmtree(self.root / "releases")
        victim = self.base / "important"
        victim.mkdir()
        (victim / "file").write_text("keep")
        (self.root / "releases").symlink_to(victim, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink"):
            remover.uninstall(self.root)
        self.assertEqual((victim / "file").read_text(), "keep")

    def test_relative_xdg_variable_uses_home_fallback(self):
        with patch.dict(os.environ, {"XDG_DATA_HOME": "relative"}):
            self.assertEqual(installer.default_root(), Path.home() / ".local/share/wynxq-app")

    def test_control_characters_in_paths_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "control characters"):
            installer.absolute("/tmp/wynxq\nmalformed")


if __name__ == "__main__":
    unittest.main()


# ------------------------------------------------------- stranded launchers
# Losing the install root without losing the launcher used to deadlock the
# user out of their own app: install refused to touch the file, and uninstall
# reported nothing to do.

def test_a_launcher_left_behind_by_a_missing_root_can_be_reinstalled_over(tmp_path, monkeypatch):
    import install as inst
    home = tmp_path / "home"
    (home / ".local/bin").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    root = home / ".local/share/wynxq-app"
    launcher = home / ".local/bin/wynxq"
    launcher.symlink_to(root / "wynxq")          # The root itself never existed.
    assert not inst.exists(root)

    # The guard used to refuse this outright, with no way forward.
    inst.check_managed(launcher, {"files": {}}, root)


def test_a_file_belonging_to_something_else_is_still_refused(tmp_path):
    import install as inst
    root = tmp_path / "wynxq-app"
    intruder = tmp_path / "bin" / "wynxq"
    intruder.parent.mkdir(parents=True)
    intruder.write_text("#!/bin/sh\necho not ours\n")

    with pytest.raises(ValueError, match="does not recognise"):
        inst.check_managed(intruder, {"files": {}}, root)

    # Nor a link that points somewhere outside the installation.
    elsewhere = tmp_path / "bin" / "other"
    elsewhere.symlink_to(tmp_path / "somewhere-else" / "wynxq")
    with pytest.raises(ValueError, match="does not recognise"):
        inst.check_managed(elsewhere, {"files": {}}, root)


def test_uninstall_clears_a_stranded_launcher_instead_of_shrugging(tmp_path, monkeypatch):
    import uninstall as uninst
    home = tmp_path / "home"
    (home / ".local/bin").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    root = home / ".local/share/wynxq-app"
    launcher = home / ".local/bin/wynxq"
    launcher.symlink_to(root / "wynxq")

    messages = uninst.uninstall(root, bin_dir=home / ".local/bin")
    assert not launcher.is_symlink()
    assert any("leftover" in line for line in messages)


def test_uninstall_leaves_a_launcher_pointing_somewhere_else_alone(tmp_path, monkeypatch):
    import uninstall as uninst
    home = tmp_path / "home"
    (home / ".local/bin").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    root = home / ".local/share/wynxq-app"
    foreign = home / ".local/bin/wynxq"
    foreign.symlink_to(tmp_path / "some-other-tool" / "wynxq")

    messages = uninst.uninstall(root, bin_dir=home / ".local/bin")
    assert foreign.is_symlink(), "a link Wynxq did not create was removed"
    assert messages == [f"No installation found at {root}."]