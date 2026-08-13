#!/usr/bin/env bash
# Print one version's section of the changelog, to stdout, for the body of a
# draft release.
#
# The release workflow has no other source for that prose, and every word of
# it is written by hand in CHANGELOG.md. Commit subjects describe changes to
# the code. This text describes changes to the product, and its readers never
# see the repository. A generator closes neither gap, so the obvious
# alternatives -- GitHub's generated notes, a conventional-commits tool --
# supply a starting draft at best and never the finished section.
#
# This is a script rather than an inline awk in the workflow so that a
# version nobody wrote notes for -- or one whose heading is there with
# nothing under it -- is an exit code the publish job stops on, instead of an
# empty release body nobody notices until it is public. Gate on that exit
# code, never on what this prints.
#
# Usage: extract-changelog.sh 1.0.0   (a bare version, no leading v)
set -euo pipefail

cd "$(dirname "$0")/.."

VERSION="${1:?usage: extract-changelog.sh VERSION}"

# Match the heading literally and anchored at column 1, rather than as a
# regex -- a version is full of dots, and each one would otherwise be a
# wildcard able to select a neighbouring release's notes.
SECTION=$(awk -v heading="## [$VERSION]" '
  index($0, heading) == 1 { found = 1; next }
  found && index($0, "## [") == 1 { exit }
  found { print }
' CHANGELOG.md)

if [ -z "$SECTION" ]; then
  echo "CHANGELOG.md has no section with content for version $VERSION" >&2
  exit 1
fi

printf '%s\n' "$SECTION"
