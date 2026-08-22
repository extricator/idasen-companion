#!/usr/bin/env bash
# Extract, update, and compile all translation catalogs.
#
# Two independent catalogs (see docs/TRANSLATING.md and the module docstrings
# in gui/i18n.py and core/i18n.py for *why* there are two):
#
#   * GUI  — Qt Linguist. Sources: gui/**/*.py wrapped in tr()/translate().
#            .ts (editable, committed) -> .qm (compiled, shipped).
#   * daemon + core — GNU gettext. Sources: every *.py under the package
#            except gui/, wrapped in _()/ngettext() (the daemon) or the
#            marker functions in core/presentation/register.py (the shared
#            layer). .pot/.po (editable, committed) -> .mo (compiled, shipped).
#
# Run after adding/changing user-facing strings, or to add a language. Adding
# a language = add its code to LANGS below and re-run; then translate the new
# translations/*.ts and po/*.po and re-run to compile. Idempotent.
#
# Requires: pyside6-lupdate, pyside6-lrelease (PySide6 tools), xgettext,
# msginit, msgmerge, msgfmt (gettext). Prefer running from the project venv so
# the PySide6 tools are on PATH.
set -euo pipefail

# Languages we ship. English is the source language (no catalog needed).
LANGS=(es)

cd "$(dirname "$0")/.."
PKG=src/idasen_companion

# Tools: prefer venv-local pyside6-* if present.
LUPDATE=${LUPDATE:-$(command -v pyside6-lupdate || echo pyside6-lupdate)}
LRELEASE=${LRELEASE:-$(command -v pyside6-lrelease || echo pyside6-lrelease)}

mkdir -p translations "$PKG/gui/translations" po

# ---- GUI (Qt Linguist) -------------------------------------------------------
gui_sources=$(find "$PKG/gui" -name '*.py' | sort)

ts_args=()
for lang in "${LANGS[@]}"; do
    ts_args+=(-ts "translations/idasen_companion_${lang}.ts")
done
echo ">> lupdate: extracting GUI strings -> translations/*.ts"
# Source references are not stored. Every other setting lupdate offers records
# a line number, which then moves whenever anything above a translatable string
# moves -- adding a comment was enough to rewrite four entries. That churn is
# indistinguishable, to a regenerate-then-diff check, from a string shipped
# untranslated, so the freshness gate would fail pull requests that touch no
# text at all. The daemon catalog avoids the same trap via --add-location=file
# below; lupdate has no filename-only setting, so it drops the reference.
#
# Nothing depends on the references: they are stripped when compiling to .qm,
# no test or gate reads them, and lupdate re-matches entries by context plus
# source text (verified -- all 391 existing translations survived their
# removal). They served only Qt Linguist's jump-to-source. The glossary in
# docs/TRANSLATING.md now carries the context a translator needs instead.
# shellcheck disable=SC2086
"$LUPDATE" -locations none -no-obsolete $gui_sources "${ts_args[@]}"

for lang in "${LANGS[@]}"; do
    echo ">> lrelease: translations/idasen_companion_${lang}.ts -> .qm"
    "$LRELEASE" "translations/idasen_companion_${lang}.ts" \
        -qm "$PKG/gui/translations/idasen_companion_${lang}.qm"
done

# ---- Daemon notifications + the shared presentation register (GNU gettext) --
# Every source file under the package except gui/ — the GUI's strings are
# extracted separately, above, into the Qt catalog. Widened from a
# daemon/-only scan so the shared vocabulary under core/presentation/ is
# reachable too; see core/presentation/register.py for the two marker
# functions this scope now covers.
core_sources=$(find "$PKG" -name '*.py' -not -path "$PKG/gui/*" | sort)

echo ">> xgettext: extracting daemon and core strings -> po/idasen_companion.pot"
# Filename-only location comments below, so lines added or removed above a
# translatable string don't shift every `#:` comment in the file and churn
# the diff on every run (deterministic output for GATE-02 CI).
# shellcheck disable=SC2086
xgettext --language=Python --from-code=UTF-8 \
    --keyword=_ --keyword=ngettext:1,2 --keyword=N_ --keyword=NP_:1,2 \
    --add-location=file \
    --package-name=idasen-companion \
    --msgid-bugs-address=https://github.com/extricator/idasen-companion/issues \
    -o po/idasen_companion.pot $core_sources

# Pin the creation date: xgettext stamps the current time, which would churn
# the diff on every run even with zero source changes (deterministic output
# for GATE-02 CI). msgmerge below propagates this same pinned value into
# each language's .po header.
sed -i 's/^"POT-Creation-Date:.*/"POT-Creation-Date: 2000-01-01 00:00+0000\\n"/' \
    po/idasen_companion.pot

for lang in "${LANGS[@]}"; do
    po="po/${lang}.po"
    if [[ -f "$po" ]]; then
        echo ">> msgmerge: refreshing $po"
        msgmerge --update --backup=none --quiet "$po" po/idasen_companion.pot
    else
        echo ">> msginit: creating $po"
        msginit --no-translator --locale="$lang" \
            -i po/idasen_companion.pot -o "$po"
    fi
    mo="$PKG/locale/${lang}/LC_MESSAGES/idasen_companion.mo"
    mkdir -p "$(dirname "$mo")"
    echo ">> msgfmt: $po -> $mo"
    msgfmt "$po" -o "$mo"
done

echo ">> done."
