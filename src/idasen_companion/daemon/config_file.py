"""Configuration file lifecycle, separate from the applied runtime state."""

from __future__ import annotations

from pathlib import Path

from ..core import logmsg
from ..core.config import AppConfig, ConfigError, load_config, save_config
from ..core.migration import import_idasen_cli_config
from .ringlog import RingLog


class ConfigFileStore:
    """Own the file path and observed revision, never the active config."""

    def __init__(self, path: Path, activity_log: RingLog):
        self.path = path
        self._activity_log = activity_log
        self._mtime: float | None = None

    def load_or_bootstrap(self) -> AppConfig:
        config = self.load()
        if not config.desk.mac and not self.path.exists():
            imported = import_idasen_cli_config()
            if imported:
                self._activity_log.emit(
                    logmsg.SETUP_IMPORTED_CLI,
                    mac=imported.mac, presets=len(imported.presets))
                if imported.mac:
                    config.desk.mac = imported.mac
                for name, height in imported.presets.items():
                    config.presets[name] = height
                if imported.skipped:
                    self._activity_log.diag(
                        "warning", "idasen CLI positions outside this desk's "
                        f"range, not imported: {', '.join(imported.skipped)}")
                # A rejected import must not wedge every subsequent start.
                # Keep the wizard available on defaults and do not stamp a
                # failed write as a newly observed revision.
                try:
                    save_config(config, self.path)
                except (ConfigError, OSError) as error:
                    self._activity_log.diag(
                        "error", f"could not write the imported config: {error}")
                    return self.load()
        self.note_mtime()
        return config

    def load(self) -> AppConfig:
        """Read fresh content without changing the watcher's revision."""
        return load_config(self.path)

    def poll_changed(self) -> bool:
        """Consume a changed revision before its caller attempts to parse it."""
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return False
        # None means the file was absent, not that watching is disabled.
        if mtime == self._mtime:
            return False
        self._mtime = mtime
        return True

    def note_mtime(self) -> None:
        """Refresh after successful loading/application or our own write."""
        try:
            self._mtime = self.path.stat().st_mtime
        except OSError:
            self._mtime = None

    def save(self, config: AppConfig) -> None:
        """Use the validated atomic writer; stamp only a successful write."""
        save_config(config, self.path)
        self.note_mtime()
