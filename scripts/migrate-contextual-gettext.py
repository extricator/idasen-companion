#!/usr/bin/env python3
"""One-time, replayable Qt TS to contextual-gettext migration.

The source pass uses Python AST byte locations: it rewrites only literal
``QObject.tr`` calls and refuses dynamic calls.  The catalog pass combines the
new POT with the old gettext PO and Qt TS translations, rejecting ambiguous
translations instead of guessing.
"""

from __future__ import annotations

import argparse
import ast
from collections import defaultdict
from dataclasses import dataclass
import io
from pathlib import Path
import xml.etree.ElementTree as ET

from babel.messages import pofile


REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "src" / "idasen_companion"

# These are semantic roles, not Python class names.  They also define the
# replayable mapping from the frozen Qt catalog to the unified catalog.
QT_CONTEXTS = {
    "AboutPage": "about",
    "ActivityLogPage": "activity-log.controls",
    "AutomationPage": "automation-settings",
    "BackgroundPortal": "background-permission",
    "DailyBarsChart": "statistics.chart",
    "LogMessage": "activity-log.entry",
    "MainWindow": "window-shell",
    "OverviewPage": "overview",
    "PresetsPage": "presets",
    "ScanPage": "setup.scan",
    "SettingsFormPage": "settings-form",
    "SettingsPage": "settings",
    "SetupWizard": "setup",
    "StatisticsPage": "statistics",
    "TrayIcon": "tray",
    "UsagePage": "setup.usage",
    "WelcomePage": "setup.welcome",
    "util": "shared-widget",
}

FILE_CONTEXTS = {
    "main_window.py": "window-shell",
    "about.py": "about",
    "activity_log.py": "activity-log.controls",
    "automation.py": "automation-settings",
    "overview.py": "overview",
    "presets.py": "presets",
    "settings.py": "settings",
    "statistics.py": "statistics",
    "tray.py": "tray",
    "widgets.py": "statistics.chart",
}

CLASS_CONTEXTS = {
    "AboutPage": "about",
    "ActivityLogPage": "activity-log.controls",
    "AutomationPage": "automation-settings",
    "DailyBarsChart": "statistics.chart",
    "MainWindow": "window-shell",
    "OverviewPage": "overview",
    "PresetsPage": "presets",
    "ScanPage": "setup.scan",
    "SettingsPage": "settings",
    "SetupWizard": "setup",
    "StatisticsPage": "statistics",
    "TrayIcon": "tray",
    "UsagePage": "setup.usage",
    "WelcomePage": "setup.welcome",
}


@dataclass(frozen=True)
class Replacement:
    start: int
    end: int
    text: str


def _offsets(source: str) -> list[int]:
    starts = [0]
    for line in source.splitlines(keepends=True):
        starts.append(starts[-1] + len(line.encode("utf-8")))
    return starts


def _span(node: ast.AST, starts: list[int]) -> tuple[int, int]:
    assert hasattr(node, "end_lineno") and hasattr(node, "end_col_offset")
    return (starts[node.lineno - 1] + node.col_offset,
            starts[node.end_lineno - 1] + node.end_col_offset)


class TrCollector(ast.NodeVisitor):
    def __init__(self, path: Path, source: str) -> None:
        self.path = path
        self.source = source
        self.starts = _offsets(source)
        self.classes: list[str] = []
        self.replacements: list[Replacement] = []
        self.errors: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self.classes.append(node.name)
        self.generic_visit(node)
        self.classes.pop()

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "tr"):
            self.generic_visit(node)
            return
        first = node.args[0] if node.args else None
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            self.errors.append(
                f"{self.path.relative_to(REPO)}:{node.lineno}: dynamic tr call: "
                f"{ast.unparse(node)}")
            self.generic_visit(node)
            return
        class_name = self.classes[-1] if self.classes else ""
        context = CLASS_CONTEXTS.get(class_name) or FILE_CONTEXTS.get(self.path.name)
        if context is None:
            self.errors.append(
                f"{self.path.relative_to(REPO)}:{node.lineno}: no semantic context")
            self.generic_visit(node)
            return
        start, end = _span(node, self.starts)
        arg_start, arg_end = _span(first, self.starts)
        raw_literal = self.source.encode("utf-8")[arg_start:arg_end].decode("utf-8")
        self.replacements.append(
            Replacement(start, end, f"pgettext({context!r}, {raw_literal})"))
        self.generic_visit(node)


def rewrite_gui(paths: list[Path], *, check: bool) -> None:
    errors: list[str] = []
    changed: list[Path] = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        collector = TrCollector(path, source)
        collector.visit(ast.parse(source, filename=str(path)))
        errors.extend(collector.errors)
        if not collector.replacements:
            continue
        data = source.encode("utf-8")
        for replacement in sorted(collector.replacements,
                                  key=lambda item: item.start, reverse=True):
            data = (data[:replacement.start] + replacement.text.encode("utf-8")
                    + data[replacement.end:])
        updated = data.decode("utf-8")
        dots = "..." if path.parent.name == "pages" else ".."
        import_line = f"from {dots}core.i18n import pgettext\n"
        if import_line not in updated:
            tree = ast.parse(updated)
            insert_after = 0
            for node in tree.body:
                if (isinstance(node, ast.Expr)
                        and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str)):
                    insert_after = node.end_lineno
                elif (isinstance(node, ast.ImportFrom)
                      and node.module == "__future__"):
                    insert_after = node.end_lineno
                else:
                    break
            lines = updated.splitlines(keepends=True)
            lines.insert(insert_after, "\n" + import_line)
            updated = "".join(lines)
        if updated != source:
            changed.append(path)
            if not check:
                path.write_text(updated, encoding="utf-8")
    if errors:
        raise SystemExit("\n".join(errors))
    if check and changed:
        names = "\n".join(str(path.relative_to(REPO)) for path in changed)
        raise SystemExit(f"contextual gettext rewrite is not applied:\n{names}")
    print(f"{'would rewrite' if check else 'rewrote'} {len(changed)} GUI files")


def rewrite_register(path: Path, *, check: bool) -> None:
    source = path.read_text(encoding="utf-8")
    starts = _offsets(source)
    replacements: list[Replacement] = []
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
            continue
        if node.func.id == "N_":
            start, _end = _span(node, starts)
            func_end = start + len("N_(".encode())
            replacements.append(Replacement(
                start, func_end, "P_('shared.presentation', "))
        elif node.func.id == "NP_" and len(node.args) == 2:
            _start, _end = _span(node, starts)
            first_start, _first_end = _span(node.args[0], starts)
            replacements.append(Replacement(
                first_start, first_start, "'shared.presentation', "))
    data = source.encode("utf-8")
    for replacement in sorted(replacements, key=lambda item: item.start,
                              reverse=True):
        data = (data[:replacement.start] + replacement.text.encode("utf-8")
                + data[replacement.end:])
    updated = data.decode("utf-8")
    if updated != source and not check:
        path.write_text(updated, encoding="utf-8")
    if check and updated != source:
        raise SystemExit("presentation register still contains uncontextual markers")
    print(f"{'would rewrite' if check else 'rewrote'} {len(replacements)} shared keys")


def rewrite_log_messages(path: Path, *, check: bool) -> None:
    source = path.read_text(encoding="utf-8")
    starts = _offsets(source)
    replacements: list[Replacement] = []
    tree = ast.parse(source, filename=str(path))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "Message"):
            continue
        for keyword in node.keywords:
            if keyword.arg not in {"text", "fallback_note", "plural_text"}:
                continue
            if not isinstance(keyword.value, (ast.Constant, ast.BinOp, ast.Call)):
                continue
            if (isinstance(keyword.value, ast.Call)
                    and isinstance(keyword.value.func, ast.Name)
                    and keyword.value.func.id == "P_"):
                continue
            start, end = _span(keyword.value, starts)
            raw = source.encode("utf-8")[start:end].decode("utf-8")
            replacements.append(Replacement(
                start, end, f"P_('activity-log.entry', {raw})"))
    data = source.encode("utf-8")
    for replacement in sorted(replacements, key=lambda item: item.start,
                              reverse=True):
        data = (data[:replacement.start] + replacement.text.encode("utf-8")
                + data[replacement.end:])
    updated = data.decode("utf-8")
    if updated != source and not check:
        path.write_text(updated, encoding="utf-8")
    if check and updated != source:
        raise SystemExit("activity log messages still contain uncontextual text")
    print(f"{'would rewrite' if check else 'rewrote'} {len(replacements)} log keys")


def _ts_messages(path: Path):
    values: dict[tuple[str, str], list[tuple[str | tuple[str, ...], list[str]]]] = \
        defaultdict(list)
    root = ET.parse(path).getroot()
    for context_node in root.findall("context"):
        old_context = context_node.findtext("name", "")
        context = QT_CONTEXTS.get(old_context)
        if context is None:
            raise SystemExit(f"unmapped Qt context: {old_context}")
        for node in context_node.findall("message"):
            source = node.findtext("source", "")
            translation = node.find("translation")
            if translation is None or translation.get("type") == "unfinished":
                continue
            forms = tuple(form.text or "" for form in translation.findall("numerusform"))
            string: str | tuple[str, ...] = forms or (translation.text or "")
            comments = [text for tag in ("comment", "extracomment", "translatorcomment")
                        if (text := node.findtext(tag))]
            values[(context, source)].append((string, comments))
    return values


def _name_placeholders(text: str, names: tuple[str, ...]) -> str:
    converted = text
    for name in names:
        converted = converted.replace("%s", f"%({name})s", 1)
    if "%s" in converted:
        raise SystemExit(f"unmapped positional placeholder in {text!r}")
    return converted


def migrate_catalog(template: Path, old_po: Path, ts_path: Path,
    output: Path) -> None:
    with template.open("rb") as handle:
        template_bytes = handle.read().replace(
            b"nplurals=INTEGER; plural=EXPRESSION;",
            b"nplurals=2; plural=(n != 1);")
        catalog = pofile.read_po(io.BytesIO(template_bytes), locale="es")
    with old_po.open("rb") as handle:
        old_catalog = pofile.read_po(handle, locale="es")
    catalog.mime_headers = [
        ("Project-Id-Version", "idasen-companion"),
        ("Report-Msgid-Bugs-To",
         "https://github.com/extricator/idasen-companion/issues"),
        ("POT-Creation-Date", "2000-01-01 00:00+0000"),
        ("PO-Revision-Date", "2026-09-16 00:00+0000"),
        ("Last-Translator", "Idasen Companion translators"),
        ("Language", "es"),
        ("Language-Team", "Spanish"),
        ("MIME-Version", "1.0"),
        ("Content-Type", "text/plain; charset=UTF-8"),
        ("Content-Transfer-Encoding", "8bit"),
        ("Plural-Forms", "nplurals=2; plural=(n != 1);"),
    ]
    catalog.header_comment = (
        "# Spanish translations for idasen-companion package.\n"
        "# This file is distributed under the same license as the "
        "idasen-companion package.\n#")
    catalog.fuzzy = False
    old_by_id = {(message.context, message.id): message for message in old_catalog
                 if message.id and message.string}
    ts_values = _ts_messages(ts_path)
    plural_migrations = {
        ("activity-log.entry",
         "First run: imported settings from idasen CLI config "
         "(mac=%(mac)s, %(presets)s preset)"):
            ("Primera ejecución: se importó la configuración de idasen CLI "
             "(mac=%(mac)s, %(presets)s preajuste)",
             "Primera ejecución: se importó la configuración de idasen CLI "
             "(mac=%(mac)s, %(presets)s preajustes)"),
        ("activity-log.entry", "Scan finished: %(count)s device found."):
            ("Escaneo finalizado: %(count)s dispositivo encontrado.",
             "Escaneo finalizado: %(count)s dispositivos encontrados."),
    }
    named_migrations = {
        ("window-shell", "The background service could not be started:\n%(error)s\n\n"
         "Try running this in a terminal:\n  %(command)s"):
            ("The background service could not be started:\n%s\n\n"
             "Try running this in a terminal:\n  %s", ("error", "command")),
        ("automation-settings", "Automation runs %(days)s, %(start)s–%(end)s. "
         "Outside these hours the desk stays put."):
            ("Automation runs %s, %s–%s. Outside these hours the desk stays put.",
             ("days", "start", "end")),
        ("presets", "Preset '%(name)s' set to %(height)s."):
            ("Preset '%s' set to %s.", ("name", "height")),
        ("setup.welcome", "The background service could not be started:\n%(error)s\n\n"
         "Try running this in a terminal, then continue:\n  %(command)s"):
            ("The background service could not be started:\n%s\n\n"
             "Try running this in a terminal, then continue:\n  %s",
             ("error", "command")),
        ("tray", "%(position)s · %(status)s"):
            ("%s · %s", ("position", "status")),
        ("tray", "%(position)s for %(duration)s"):
            ("%s for %s", ("position", "duration")),
        ("tray", "%(status)s · %(countdown)s"):
            ("%s · %s", ("status", "countdown")),
        ("tray", "Today: %(sitting)s sitting / %(standing)s standing"):
            ("Today: %s sitting / %s standing", ("sitting", "standing")),
        ("tray", "%(name)s (%(height)s)"):
            ("%s (%s)", ("name", "height")),
    }
    translated = 0
    for message in catalog:
        if not message.id:
            continue
        msgid = message.id[0] if isinstance(message.id, tuple) else message.id
        candidates = []
        old = old_by_id.get((None, message.id)) or old_by_id.get((None, msgid))
        if old is not None:
            candidates.append((old.string, list(old.user_comments)))
        candidates.extend(ts_values.get((message.context or "", msgid), []))
        if message.context == "activity-log.parameter":
            candidates.extend(ts_values.get(("activity-log.entry", msgid), []))
        if (message.context or "", msgid) in plural_migrations:
            candidates.append((plural_migrations[(message.context or "", msgid)], []))
        named = named_migrations.get((message.context or "", msgid))
        if named is not None:
            old_msgid, names = named
            for string, comments in ts_values.get(
                    (message.context or "", old_msgid), []):
                if isinstance(string, tuple):
                    converted = tuple(_name_placeholders(value, names)
                                      for value in string)
                else:
                    converted = _name_placeholders(string, names)
                candidates.append((converted, comments))
        nonempty = [
            (string, comments) for string, comments in candidates
            if (bool(string) if isinstance(string, str) else any(string))
        ]
        distinct = {string if isinstance(string, str) else tuple(string)
                    for string, _comments in nonempty}
        if len(distinct) > 1:
            raise SystemExit(
                f"ambiguous translation for {message.context!r}/{msgid!r}: "
                f"{sorted(map(repr, distinct))}")
        if nonempty:
            message.string = nonempty[0][0]
            for _string, comments in nonempty:
                message.user_comments[:] = list(dict.fromkeys(
                    [*message.user_comments, *comments]))
            translated += 1
    with output.open("wb") as handle:
        pofile.write_po(handle, catalog, width=79, include_lineno=False,
                        sort_by_file=True)
    try:
        shown_output = output.relative_to(REPO)
    except ValueError:
        shown_output = output
    print(f"migrated {translated} translated entries into {shown_output}")


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    rewrite = subparsers.add_parser("rewrite")
    rewrite.add_argument("--check", action="store_true")
    catalog = subparsers.add_parser("catalog")
    catalog.add_argument("--template", type=Path, default=REPO / "po/idasen_companion.pot")
    catalog.add_argument("--po", type=Path, default=REPO / "po/es.po")
    catalog.add_argument("--ts", type=Path,
                         default=REPO / "translations/idasen_companion_es.ts")
    catalog.add_argument("--output", type=Path, default=REPO / "po/es.po")
    args = parser.parse_args()
    if args.command == "rewrite":
        paths = [path for path in sorted((PACKAGE / "gui").rglob("*.py"))
                 if path.name in FILE_CONTEXTS or path.name == "setup_wizard.py"]
        rewrite_gui(paths, check=args.check)
        rewrite_register(PACKAGE / "core/presentation/register.py",
                         check=args.check)
        rewrite_log_messages(PACKAGE / "core/logmsg.py", check=args.check)
    else:
        migrate_catalog(args.template, args.po, args.ts, args.output)


if __name__ == "__main__":
    main()
