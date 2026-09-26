#!/usr/bin/env bash
# bump-version.sh — the UNIFORM ActiveAI version script.            (rev 1)
#
# This file is IDENTICAL in every repository. Do not edit it per project —
# copy it in verbatim, and put anything project-specific in the two optional
# sidecar files next to it (see "Per-project" below). Spec:
# docs/versioning-standard.md in the backbone repo.
#
#   bash scripts/bump-version.sh              1.2.3 -> 1.2.4   (default: patch)
#   bash scripts/bump-version.sh --minor      1.2.3 -> 1.3.0
#   bash scripts/bump-version.sh --major      1.2.3 -> 2.0.0
#   bash scripts/bump-version.sh --set 1.2.3  write exactly this everywhere
#   bash scripts/bump-version.sh --sync       re-align every file, no increment
#   bash scripts/bump-version.sh --print      print the current version, change nothing
#   SKIP_VERSION_BUMP=1 …                     do nothing, exit 0 (manual escape hatch)
#
# What it guarantees
#   - version.ini at the repo root is the SOURCE OF TRUTH and is always
#     written. The build/deploy pipeline reads `version = X.Y.Z` from it to
#     decide whether there is anything new to ship — no bump, no deploy.
#   - version.json is always written alongside it, and the root package.json
#     (when there is one) is always kept in step.
#   - Every other file that carries the version is listed in
#     scripts/bump-version.conf and rewritten too.
#   - It refuses to run if another file is AHEAD of version.ini (someone
#     hand-edited it — bumping would silently move the version backwards), and
#     it re-reads every file afterwards and fails if any of them disagree.
#   - Touched files are `git add`ed, so it works as a pre-commit hook as well.
#
# Per-project (both optional, both live in scripts/):
#   bump-version.conf     one repo-relative path per line; # comments. In each
#                         file the FIRST quoted X.Y.Z that follows the word
#                         "version" (any case) is replaced. That one rule covers
#                         package.json / app.json, `export const V = "1.2.3"`,
#                         `__version__ = '1.2.3'`, and the like.
#   bump-version.post.sh  run after the files are written, with the new version
#                         as $1 and $NEW_VERSION — for anything a path list
#                         can't express (regenerating a stamp, a lockfile…).
#
# Version numbers are cheap; a change that ships WITHOUT a bump is not. So this
# script is meant to be called from every place that might matter — Submit, a
# pre-commit hook, bumpandpush.sh, build/dev hooks — and two bumps landing in
# one commit is fine and expected. SKIP_VERSION_BUMP=1 is only a manual escape
# hatch (a rebase, a bulk history edit); no tool sets it.
#
# Deliberately plain bash 3.2 + awk: no node, python, jq or GNU-only sed, so it
# behaves the same on macOS, Linux and a bare CI agent.
set -eu

[ "${SKIP_VERSION_BUMP:-}" = "1" ] && { echo "bump-version: skipped (SKIP_VERSION_BUMP=1)"; exit 0; }

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
INI="$ROOT/version.ini"
JSON="$ROOT/version.json"
CONF="$ROOT/scripts/bump-version.conf"
POST="$ROOT/scripts/bump-version.post.sh"
SEMVER='[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*'

die() { echo "bump-version: ERROR: $*" >&2; exit 1; }
is_semver() { printf '%s' "$1" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; }

# ── args ─────────────────────────────────────────────────────────────────────
MODE="patch"; SET_TO=""
while [ $# -gt 0 ]; do
  case "$1" in
    --patch) MODE="patch" ;;
    --minor) MODE="minor" ;;
    --major) MODE="major" ;;
    --sync)  MODE="sync" ;;
    --print) MODE="print" ;;
    --set)   MODE="set"; shift; SET_TO="${1:-}"; is_semver "$SET_TO" || die "--set needs X.Y.Z" ;;
    -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $1 (try --help)" ;;
  esac
  shift
done

# ── reading versions ─────────────────────────────────────────────────────────
ini_version() { [ -f "$INI" ] && sed -n "s/^[[:space:]]*version[[:space:]]*=[[:space:]]*\($SEMVER\).*/\1/p" "$INI" | head -1; }

# First quoted X.Y.Z after the word "version" (any case) in a file.
file_version() {
  [ -f "$1" ] || return 0
  awk -v q="'" '
    BEGIN { re = "version[^0-9]*[\"" q "][0-9]+\\.[0-9]+\\.[0-9]+[\"" q "]" }
    { l = tolower($0)
      if (match(l, re)) {
        seg = substr($0, RSTART, RLENGTH)
        if (match(seg, /[0-9]+\.[0-9]+\.[0-9]+/)) { print substr(seg, RSTART, RLENGTH); exit }
      } }' "$1"
}

# ver_gt A B → true when A > B
ver_gt() {
  local a1 a2 a3 b1 b2 b3
  IFS=. read -r a1 a2 a3 <<EOF
$1
EOF
  IFS=. read -r b1 b2 b3 <<EOF
$2
EOF
  [ "$a1" -gt "$b1" ] && return 0; [ "$a1" -lt "$b1" ] && return 1
  [ "$a2" -gt "$b2" ] && return 0; [ "$a2" -lt "$b2" ] && return 1
  [ "$a3" -gt "$b3" ]
}

# ── targets: root package.json (automatic) + everything in the .conf ─────────
TARGETS=""   # newline-separated, repo-relative
add_target() { case "
$TARGETS
" in *"
$1
"*) ;; *) TARGETS="${TARGETS:+$TARGETS
}$1" ;; esac; }
[ -f "$ROOT/package.json" ] && add_target "package.json"
if [ -f "$CONF" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%%#*}"
    line="$(printf '%s' "$line" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
    [ -n "$line" ] && add_target "$line"
  done < "$CONF"
fi

# ── current version ──────────────────────────────────────────────────────────
CURRENT="$(ini_version || true)"
if [ -z "$CURRENT" ]; then
  # First run in this repo: adopt the HIGHEST version any existing file claims,
  # so adopting the standard can never move a project backwards.
  CURRENT="0.0.0"
  OLD_IFS="$IFS"; IFS='
'
  for rel in "version.json" $TARGETS; do
    v="$(file_version "$ROOT/$rel" || true)"
    if [ -n "$v" ] && ver_gt "$v" "$CURRENT"; then CURRENT="$v"; fi
  done
  IFS="$OLD_IFS"
  [ "$CURRENT" = "0.0.0" ] && CURRENT="1.0.0"
  [ "$MODE" = "print" ] || echo "bump-version: no version.ini yet — starting from $CURRENT (highest version found in the existing files)"
fi
if [ "$MODE" = "print" ]; then echo "$CURRENT"; exit 0; fi

# ── pre-flight: nothing may be AHEAD of the source of truth ──────────────────
if [ "$MODE" != "sync" ] && [ "$MODE" != "set" ]; then
  ahead=""
  OLD_IFS="$IFS"; IFS='
'
  for rel in "version.json" $TARGETS; do
    v="$(file_version "$ROOT/$rel" || true)"
    if [ -n "$v" ] && ver_gt "$v" "$CURRENT"; then ahead="$ahead
  $rel = $v"; fi
  done
  IFS="$OLD_IFS"
  if [ -n "$ahead" ]; then
    echo "bump-version: ERROR: these files are AHEAD of version.ini ($CURRENT):$ahead" >&2
    echo "  version.ini is the source of truth; bumping now would move them backwards." >&2
    echo "  Fix:  bash scripts/bump-version.sh --set <the version you really want>" >&2
    exit 1
  fi
fi

# ── next version ─────────────────────────────────────────────────────────────
IFS=. read -r MAJOR MINOR PATCH <<EOF
$CURRENT
EOF
case "$MODE" in
  patch) NEW="$MAJOR.$MINOR.$((PATCH + 1))" ;;
  minor) NEW="$MAJOR.$((MINOR + 1)).0" ;;
  major) NEW="$((MAJOR + 1)).0.0" ;;
  sync)  NEW="$CURRENT" ;;
  set)   NEW="$SET_TO" ;;
esac
NOW="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

# ── write version.ini + version.json (keeping each repo's existing dialect) ──
SECTION="[version]"
if [ -f "$INI" ]; then
  s="$(sed -n 's/^[[:space:]]*\(\[[^]]*\]\).*/\1/p' "$INI" | head -1)"
  [ -n "$s" ] && SECTION="$s"
fi
printf '%s\nversion = %s\nupdated_at = %s\n' "$SECTION" "$NEW" "$NOW" > "$INI"

STAMP_KEY="updatedAt"
[ -f "$JSON" ] && grep -q '"updated_at"' "$JSON" && STAMP_KEY="updated_at"
printf '{\n  "version": "%s",\n  "%s": "%s"\n}\n' "$NEW" "$STAMP_KEY" "$NOW" > "$JSON"

# ── rewrite every target ─────────────────────────────────────────────────────
patch_file() {
  local file="$1" tmp
  [ -f "$file" ] || die "$2 is listed as a version file but does not exist"
  tmp="$(mktemp "${TMPDIR:-/tmp}/bump-version.XXXXXX")"
  if awk -v new="$NEW" -v q="'" '
      BEGIN { re = "version[^0-9]*[\"" q "][0-9]+\\.[0-9]+\\.[0-9]+[\"" q "]"; done = 0 }
      { if (!done) { l = tolower($0)
          if (match(l, re)) {
            head = substr($0, 1, RSTART - 1); seg = substr($0, RSTART, RLENGTH); tail = substr($0, RSTART + RLENGTH)
            sub(/[0-9]+\.[0-9]+\.[0-9]+/, new, seg); $0 = head seg tail; done = 1 } }
        print }
      END { exit done ? 0 : 3 }' "$file" > "$tmp"; then
    cat "$tmp" > "$file"    # keep the original inode, mode and owner
    rm -f "$tmp"
  else
    rm -f "$tmp"
    die "$2: found no  version … \"X.Y.Z\"  to update — fix the file or remove it from scripts/bump-version.conf"
  fi
}
OLD_IFS="$IFS"; IFS='
'
for rel in $TARGETS; do patch_file "$ROOT/$rel" "$rel"; done
IFS="$OLD_IFS"

# ── project-specific follow-up ───────────────────────────────────────────────
if [ -f "$POST" ]; then
  NEW_VERSION="$NEW" bash "$POST" "$NEW" || die "scripts/bump-version.post.sh failed"
fi

# ── verify: every file must now say NEW ──────────────────────────────────────
bad=""
[ "$(ini_version)" = "$NEW" ] || bad="$bad version.ini"
[ "$(file_version "$JSON")" = "$NEW" ] || bad="$bad version.json"
IFS='
'
for rel in $TARGETS; do [ "$(file_version "$ROOT/$rel")" = "$NEW" ] || bad="$bad $rel"; done
IFS="$OLD_IFS"
[ -z "$bad" ] || die "files disagree after the bump (expected $NEW):$bad"

# ── stage ────────────────────────────────────────────────────────────────────
if git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  IFS='
'
  for rel in "version.ini" "version.json" $TARGETS; do git -C "$ROOT" add -- "$rel" 2>/dev/null || true; done
  IFS="$OLD_IFS"
fi

if [ "$MODE" = "sync" ]; then echo "Version synced: $NEW"
else echo "Version bumped: $CURRENT → $NEW"; fi
