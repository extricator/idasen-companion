#!/usr/bin/env bash
# Scan for committed secrets, having first proved the scanner can find one.
#
# Three modes, each answering a different question about where a secret
# could be right now:
#
#   history   -- has a secret ever been committed, anywhere in the log?
#                (`gitleaks git --log-opts="--all"`)
#   worktree  -- is one sitting in the checkout on disk right now, whether or
#                not it has ever been committed? (`gitleaks dir`) This is the
#                mode that would have caught an untracked, gitignored
#                credential file -- a history scan cannot see a file that was
#                never committed, by construction.
#   staged    -- is one about to be committed? (`gitleaks git --staged`) The
#                same invocation a pre-commit hook runs, against exactly what
#                `git commit` would record right now, with no prior commit
#                required.
#
# A clean result from an unproven scanner is not evidence. `gitleaks git`
# treats any stderr from the `git log -p` underneath it as fatal: it stops,
# walks nothing, and still exits 0 reporting no leaks (upstream gitleaks#2129).
# A run that saw no commits is byte-identical to a run that saw everything and
# found nothing. The canary below is the only thing that tells those two apart,
# which is why it runs first and the real scan does not start unless it fired
# -- for every mode, not only history, because each mode walks its input a
# different way and a canary proven in one says nothing about another.
#
# This is a committed script because the procedure has been needed twice now,
# and both times it lived in a planning document outside git and had to be
# reconstructed from a file that was about to disappear. Gate on the exit code,
# never on what this prints.
#
# Usage: scan-secrets.sh MODE [OUTPUT_DIR]
#
#   MODE is history, worktree or staged (above).
#
#   OUTPUT_DIR receives the reports, the raw logs and a record of what ran.
#   Defaults to a fresh temporary directory, removed on exit along with the
#   canary fixture. Point it somewhere durable when the evidence has to
#   outlive the shell.
set -euo pipefail

cd "$(dirname "$0")/.."

MODE="${1:-}"
case "$MODE" in
    history|worktree|staged)
        ;;
    *)
        echo "error: usage: scan-secrets.sh MODE [OUTPUT_DIR]" >&2
        echo "       MODE must be one of:" >&2
        echo "         history  -- every revision (gitleaks git --log-opts=\"--all\")" >&2
        echo "         worktree -- the checkout on disk, committed or not (gitleaks dir)" >&2
        echo "         staged   -- what a commit right now would record (gitleaks git --staged)" >&2
        exit 1
        ;;
esac

# The subcommand and its flags, shared verbatim between the canary invocation
# (against $CANARY_DIR, mounted at /repo) and the real one (against this
# repository, also mounted at /repo) -- only the mount source differs.
case "$MODE" in
    history)
        SCAN_ARGS=(git /repo --log-opts="--all")
        ;;
    worktree)
        SCAN_ARGS=(dir /repo)
        ;;
    staged)
        SCAN_ARGS=(git /repo --staged)
        ;;
esac

# Pinned deliberately. A floating tag would make this evidence unfalsifiable
# later: nobody could say afterwards which ruleset produced the clean result.
IMAGE="ghcr.io/gitleaks/gitleaks:v8.30.1"
EXPECTED_VERSION="8.30.1"

OUTPUT_DIR="${2:-}"
OUTPUT_DIR_DEFAULTED=0
if [ -z "$OUTPUT_DIR" ]; then
    OUTPUT_DIR=$(mktemp -d)
    OUTPUT_DIR_DEFAULTED=1
fi
mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR=$(cd "$OUTPUT_DIR" && pwd)

CANARY_DIR=$(mktemp -d)

# One trap for the whole script: bash keeps only the last EXIT trap
# registered, so the canary fixture and a defaulted output directory (never
# otherwise removed, which would leak one per invocation once the staged mode
# runs on every commit through a hook) are cleaned up together here rather
# than via two separate registrations. Registered this early -- right after
# both directories exist -- so it also covers every failure path below this
# point: no runtime found, the image pull, the version check and the version
# mismatch. Each of those exits before the canary fixture is otherwise built,
# and each would leak a defaulted OUTPUT_DIR without this.
cleanup() {
    rm -rf "$CANARY_DIR"
    if [ "$OUTPUT_DIR_DEFAULTED" -eq 1 ]; then
        rm -rf "$OUTPUT_DIR"
    fi
}
trap cleanup EXIT

# Colour escapes are interleaved with the text in the captured logs; strip them
# before anything reads a number out of one.
strip_ansi() {
    sed -e 's/\x1b\[[0-9;]*m//g' "$1"
}

echo ">> Mode: $MODE"
echo ">> Evidence directory: $OUTPUT_DIR"

# ---------------------------------------------------------------------------
# 1. Resolve a container runtime and confirm the pinned scanner is the one
#    that will run.
# ---------------------------------------------------------------------------

RUNTIME=""
for candidate in docker podman; do
    if command -v "$candidate" >/dev/null 2>&1; then
        RUNTIME="$candidate"
        break
    fi
done

if [ -z "$RUNTIME" ]; then
    echo "error: no container runtime found; this needs docker or podman" >&2
    exit 1
fi

# Pull as its own step. A first run on a machine without the image cached
# writes pull progress to stderr, and folding that into the captured output
# below makes the version comparison fail against a wall of download lines --
# on precisely the run this script is written for, which happens once, on a
# machine that has never fetched the image.
if ! PULL_OUTPUT=$("$RUNTIME" pull "$IMAGE" 2>&1); then
    echo "error: could not fetch the pinned scanner image $IMAGE" >&2
    echo "$PULL_OUTPUT" >&2
    echo "Stop and report this. Do not reach for a different tag to get past" >&2
    echo "it -- an unpinned scanner cannot be audited after the fact." >&2
    exit 1
fi

if ! VERSION_OUTPUT=$("$RUNTIME" run --rm "$IMAGE" version 2>/dev/null); then
    echo "error: could not run the pinned scanner image $IMAGE" >&2
    echo "Stop and report this. Do not reach for a different tag to get past" >&2
    echo "it -- an unpinned scanner cannot be audited after the fact." >&2
    exit 1
fi

if [ "${VERSION_OUTPUT#v}" != "$EXPECTED_VERSION" ]; then
    echo "error: the image reported version '$VERSION_OUTPUT'," >&2
    echo "       but this script is written against $EXPECTED_VERSION." >&2
    echo "Stop and report this rather than substituting another tag." >&2
    exit 1
fi

echo ">> Runtime: $RUNTIME, scanner: $IMAGE"

{
    echo "scanned:        $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "mode:           $MODE"
    echo "repository:     $(pwd)"
    echo "runtime:        $RUNTIME ($("$RUNTIME" --version))"
    echo "scanner image:  $IMAGE"
    echo "scanner version: $VERSION_OUTPUT"
} > "$OUTPUT_DIR/scan-environment.txt"

# ---------------------------------------------------------------------------
# 2. The canary. Prove the whole chain -- container, bind mount, SELinux
#    label, the way this mode walks its input, ruleset -- can surface a
#    planted secret. CANARY_DIR itself was already created, and its cleanup
#    already registered, above -- before the runtime/pull/version checks --
#    so this fixture's directory already exists here.
# ---------------------------------------------------------------------------

# Both values are derived at run time rather than written out. A
# credential-shaped literal sitting in this file would be found by the very
# scan this script performs, on the commit that added the script.
#
# Derived, not random, so a canary that stops firing is a real change in the
# scanner rather than an unlucky draw. The mixed-case alphabet keeps the
# planted value's entropy comfortably above the threshold the generic rule
# applies, instead of a hex digest's marginal one. The seed names the mode so
# each mode plants a distinct value, rather than three modes sharing one.
CANARY_SEED="idasen-companion $MODE scan canary, not a real credential"
CANARY_DIGEST=$(printf '%s' "$CANARY_SEED" | sha256sum | tr 'a-f' 'A-F')
CANARY_KEY="AKIA${CANARY_DIGEST:0:16}"
CANARY_VALUE=$(python3 -c '
import base64, hashlib, sys
digest = hashlib.sha256(sys.argv[1].encode()).digest()
encoded = base64.b64encode(digest).decode()
print(encoded.translate(str.maketrans("+/", "Xy"))[:40])
' "$CANARY_SEED")

# Every git call against the canary goes through this, and none may call git
# directly. The pre-commit hook that invokes this script runs with the
# repository's location exported into its environment, and changing directory
# does not clear that -- so an unguarded init here builds its repository in
# the caller's, not in the temp directory. From a linked worktree that export
# is an absolute path, so the init lands on a real git directory with no work
# tree attached, concludes the repository is bare, and records that in the
# config file every worktree shares. The caller's whole checkout then refuses
# to run: "fatal: this operation must be run in a work tree". Observed; the
# recovery is to set the flag back to false.
canary_git() {
    env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE -u GIT_COMMON_DIR \
        -u GIT_OBJECT_DIRECTORY -u GIT_NAMESPACE -u GIT_PREFIX \
        git -C "$CANARY_DIR" "$@"
}

# The fixture itself differs by mode, matching how that mode actually walks
# its input:
#   history  -- a planted file, committed, so there is history to walk.
#   staged   -- a planted file, added to the index, but never committed --
#               `--staged` reads the index, and this proves that works even
#               against a repository with no prior commits at all.
#   worktree -- a planted file on disk, nothing else. `dir` mode never
#               invokes git, so there is nothing to init, stage or commit.
case "$MODE" in
    history|staged)
        canary_git init -q
        ;;
esac

{
    echo "aws_access_key_id = $CANARY_KEY"
    echo "aws_secret_access_key = $CANARY_VALUE"
} > "$CANARY_DIR/canary-credentials.ini"

case "$MODE" in
    history)
        canary_git add -A
        # An inline identity, so this works on a machine that has never
        # configured one.
        canary_git \
            -c user.email=canary@example.invalid -c user.name=canary \
            commit -qm "canary"
        ;;
    staged)
        canary_git add -A
        ;;
esac

CANARY_REPORT="$OUTPUT_DIR/canary-$MODE-gitleaks.json"
CANARY_LOG="$OUTPUT_DIR/canary-$MODE-gitleaks.log"

echo ">> Running the canary scan..."
set +e
"$RUNTIME" run --rm \
    -v "$CANARY_DIR":/repo:Z \
    -v "$OUTPUT_DIR":/out:Z \
    "$IMAGE" "${SCAN_ARGS[@]}" \
    --report-path="/out/$(basename "$CANARY_REPORT")" \
    --report-format=json \
    --verbose 2>&1 | tee "$CANARY_LOG"
# Must be the very next command: PIPESTATUS is overwritten by anything that
# runs after the pipeline, and tee's own status is not the scanner's.
CANARY_STATUS=${PIPESTATUS[0]}
set -e
echo "exit: $CANARY_STATUS" >> "$CANARY_LOG"

CANARY_FINDINGS=$(python3 -c \
    'import json,sys; print(len(json.load(open(sys.argv[1]))))' \
    "$CANARY_REPORT" 2>/dev/null || echo 0)

if [ "$CANARY_FINDINGS" -lt 1 ]; then
    echo >&2
    echo "error: the canary reported no findings (exit $CANARY_STATUS)." >&2
    echo >&2
    echo "A canary that exits 0 with zero findings means the scan is broken," >&2
    echo "not that the repo is clean. Every result below it would be" >&2
    echo "meaningless. Fix the invocation -- container, bind mount, SELinux" >&2
    echo "label, ruleset -- and re-run before trusting anything." >&2
    exit 1
fi

echo ">> Canary fired: $CANARY_FINDINGS finding(s), exit $CANARY_STATUS -- the scanner works"

# ---------------------------------------------------------------------------
# 3. The real scan.
# ---------------------------------------------------------------------------

REAL_REPORT="$OUTPUT_DIR/$MODE-gitleaks.json"
REAL_LOG="$OUTPUT_DIR/$MODE-gitleaks.log"

case "$MODE" in
    history)  echo ">> Scanning this repository's full history..." ;;
    worktree) echo ">> Scanning the working tree on disk..." ;;
    staged)   echo ">> Scanning what is staged for the next commit..." ;;
esac

set +e
"$RUNTIME" run --rm \
    -v "$(pwd)":/repo:Z \
    -v "$OUTPUT_DIR":/out:Z \
    "$IMAGE" "${SCAN_ARGS[@]}" \
    --report-path="/out/$(basename "$REAL_REPORT")" \
    --report-format=json \
    --verbose 2>&1 | tee "$REAL_LOG"
SCAN_STATUS=${PIPESTATUS[0]}
set -e
echo "exit: $SCAN_STATUS" >> "$REAL_LOG"

FINDINGS=$(python3 -c \
    'import json,sys; print(len(json.load(open(sys.argv[1]))))' \
    "$REAL_REPORT" 2>/dev/null || echo -1)

# ---------------------------------------------------------------------------
# 4. Cross-check the walk -- history mode only. This is the half that catches
#    #2129 after the fact: the canary proves the scanner *can* find
#    something, this proves this particular run actually looked at the
#    history it claims to have covered -- and that "the history" meant every
#    ref the server has, not merely the ones this clone happens to hold.
#
#    The other two modes have no walk to cross-check. `worktree` never
#    invokes git at all, so there is no commit count to compare against.
#    `staged` reads the index rather than the log, and reports having looked
#    at no commits on every single successful run -- the same line that would
#    be fatal for history mode is the ordinary case here, so porting this
#    check to it would fail every clean run. Those two modes are trusted by
#    their own canary above plus their own scan's exit code and finding count
#    below, and by nothing else.
# ---------------------------------------------------------------------------

WALK_OK=1
if [ "$MODE" = "history" ]; then
    REVISIONS=$(git rev-list --all --count)
    NON_MERGE_REVISIONS=$(git rev-list --all --count --no-merges)
    REPORTED=$(strip_ansi "$REAL_LOG" \
        | grep -oE '[0-9]+ commits scanned' \
        | grep -oE '^[0-9]+' \
        | tail -1 || true)
    REF_COUNT=$(git for-each-ref --format='%(refname)' | wc -l | tr -d ' ')

    # Every ref this run resolved to. The flag that selects them means every
    # ref in this *clone*, not every ref on the server, so naming them is the
    # only way a later reader can tell what a clean result actually covered.
    git for-each-ref --format='%(objectname) %(refname)' \
        > "$OUTPUT_DIR/refs-walked.txt"

    # Recording the refs is not enough on its own, because the dangerous ones
    # are the refs that are absent. A clone never fetches a forge's
    # pull-request refs, so they sit outside the selection above by default --
    # yet the forge keeps them permanently, and they hold every intermediate
    # commit of a proposed change, including commits a squash-merge collapsed
    # and whose content therefore never reached the default branch. A secret
    # added in one of those and cleaned up before the merge lives on that ref
    # and appears nowhere a scan of the branches would look. Skipping them
    # makes this mode narrower than its name promises, which is the single
    # failure this whole script exists to refuse.
    PULL_HEADS=""
    PULL_SCOPE="no remote configured -- nothing to compare against"
    if git remote get-url origin >/dev/null 2>&1; then
        if PULL_HEADS=$(git ls-remote origin 'refs/pull/*/head' 2>/dev/null); then
            PULL_TOTAL=$(printf '%s' "$PULL_HEADS" | grep -c . || true)
            PULL_MISSING=0
            if [ "$PULL_TOTAL" -gt 0 ]; then
                REACHABLE=$(git rev-list --all)
                while read -r head_sha head_ref; do
                    [ -z "$head_sha" ] && continue
                    printf '%s\n' "$REACHABLE" | grep -qx "$head_sha" \
                        || PULL_MISSING=$((PULL_MISSING + 1))
                done <<< "$PULL_HEADS"
            fi
            PULL_SCOPE="$PULL_TOTAL on the remote, $PULL_MISSING not reachable here"
            if [ "$PULL_MISSING" -gt 0 ]; then
                echo "error: origin publishes $PULL_TOTAL pull-request ref(s), and" >&2
                echo "       $PULL_MISSING of them is unreachable from any ref in this" >&2
                echo "       clone -- so this scan did not walk it. Those refs outlive" >&2
                echo "       the branches they came from and become fetchable by" >&2
                echo "       anyone the moment the repository is public." >&2
                echo "Fetch them, then re-run this scan:" >&2
                echo "  git fetch origin '+refs/pull/*/head:refs/remotes/origin/pr/*'" >&2
                WALK_OK=0
            fi
        else
            echo "error: could not ask origin which pull-request refs it publishes," >&2
            echo "       so this scan's scope cannot be established. A scan that" >&2
            echo "       cannot say what it covered is not evidence -- re-run it with" >&2
            echo "       network access rather than trusting the result below." >&2
            WALK_OK=0
        fi
    fi

    {
        echo "git rev-list --all --count:            $REVISIONS"
        echo "git rev-list --all --count --no-merges: $NON_MERGE_REVISIONS"
        echo "commits the scanner reported walking:  ${REPORTED:-<not reported>}"
        echo "refs in this clone:                    $REF_COUNT (listed in refs-walked.txt)"
        echo "pull-request refs:                     $PULL_SCOPE"
    } | tee "$OUTPUT_DIR/walk-cross-check.txt"

    if [ -z "$REPORTED" ]; then
        # Not a soft warning. The canary proves the scanner works, but it
        # scans a different repository -- gitleaks#2129 is triggered by
        # stderr from the log walk over *this* one, and produces a report
        # byte-identical to a clean scan. This cross-check is the only thing
        # that detects it, so a count it could not read is an unproven walk,
        # not a passing one.
        echo "error: the scanner reported no commit count, so nothing here shows it" >&2
        echo "       walked this repository at all. The canary cannot cover this --" >&2
        echo "       it scans a different repository. Read the log before trusting" >&2
        echo "       any clean result: $REAL_LOG" >&2
        WALK_OK=0
    elif [ "$REPORTED" -eq 0 ]; then
        echo "error: the scanner reports having walked no commits at all." >&2
        WALK_OK=0
    elif [ "$((REPORTED * 2))" -lt "$REVISIONS" ]; then
        echo "error: the scanner reports $REPORTED commits against $REVISIONS in" >&2
        echo "       the repository -- far too few to be the same history." >&2
        WALK_OK=0
    fi
    # A small shortfall is expected and not a failure: merge commits carry no
    # diff of their own, so the walk legitimately reports fewer than the total.
fi

# ---------------------------------------------------------------------------
# 5. Verdict.
# ---------------------------------------------------------------------------

echo
if [ "$MODE" = "history" ] && [ "$WALK_OK" -ne 1 ]; then
    echo "FAILED: the history was not walked, or not all of it was in scope." >&2
    echo "Nothing here says the repository is clean." >&2
    exit 1
fi

if [ "$FINDINGS" -lt 0 ]; then
    echo "FAILED: no report was written; the scan did not complete (exit $SCAN_STATUS)." >&2
    exit 1
fi

if [ "$FINDINGS" -gt 0 ] || [ "$SCAN_STATUS" -ne 0 ]; then
    echo "FAILED: $FINDINGS finding(s) (exit $SCAN_STATUS)." >&2
    echo "Triage every one. A finding is not automatically a blocker; an" >&2
    echo "unexplained one is. Report: $REAL_REPORT" >&2
    exit 1
fi

case "$MODE" in
    history)
        echo "PASSED: canary fired, $REPORTED commits walked by the scanner"
        echo "        (git counts $REVISIONS revisions across $REF_COUNT refs), no findings."
        echo "        Pull-request refs: $PULL_SCOPE."
        echo
        echo "This covered credential-shaped secrets only. It does NOT cover personal"
        echo "data -- MAC addresses, home directory paths, email addresses, authorship"
        echo "trailers -- which needs a person judging each distinct value against the"
        echo "ones that are expected. Do that sweep by hand before publishing."
        ;;
    worktree)
        echo "PASSED: canary fired, the working tree was scanned, no findings."
        echo
        echo "This covered credential-shaped secrets only. It does NOT cover personal"
        echo "data -- MAC addresses, home directory paths, email addresses, authorship"
        echo "trailers -- which needs a person judging each distinct value against the"
        echo "ones that are expected. Do that sweep by hand before publishing."
        ;;
    staged)
        # No personal-data advisory here: this mode is meant to run on every
        # commit through a hook, and a four-line reminder on every commit is
        # how a hook gets uninstalled.
        echo "PASSED: canary fired, the staged diff was scanned, no findings."
        ;;
esac
