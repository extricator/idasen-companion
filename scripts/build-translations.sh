#!/usr/bin/env bash
# Extract, update, and compile all translation catalogs.
#
# One app-owned GNU gettext catalog covers GUI, daemon and core. Qt's prebuilt
# qtbase catalog remains separate and is not built by this project.
#
# Run after adding/changing user-facing strings, or to add a language. Adding
# a language = add po/<code>.po and re-run. Idempotent.
#
# Requires: xgettext, msginit, msgmerge and msgfmt.
set -euo pipefail

# Languages are discovered from editable catalogs. English is the source
# language and needs no PO file.
mapfile -t LANGS < <(find po -maxdepth 1 -name '*.po' -printf '%f\n' \
    | sed 's/\.po$//' | sort)

cd "$(dirname "$0")/.."
PKG=src/idasen_companion

mkdir -p po

app_sources=$(find "$PKG" -name '*.py' | sort)

echo ">> xgettext: extracting all app strings -> po/idasen_companion.pot"
# Filename-only location comments below, so lines added or removed above a
# translatable string don't shift every `#:` comment in the file and churn
# the diff on every run (deterministic output for GATE-02 CI).
# shellcheck disable=SC2086
xgettext --language=Python --from-code=UTF-8 \
    --keyword=_ --keyword=ngettext:1,2 \
    --keyword=pgettext:1c,2 --keyword=npgettext:1c,2,3 \
    --keyword=P_:1c,2 --keyword=NP_:1c,2,3 \
    --add-comments=Translators: \
    --add-location=file \
    --package-name=idasen-companion \
    --msgid-bugs-address=https://github.com/extricator/idasen-companion/issues \
    -o po/idasen_companion.pot $app_sources

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
