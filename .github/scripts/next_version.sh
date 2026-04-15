#!/usr/bin/env bash
# Compute the next semver given the current version, a bump type, and an optional
# pre-release label. Prints the new version on stdout. Exits non-zero with a clear
# message on any unsupported transition.
#
# Usage: next_version.sh <current_version> <bump_type> [<prerelease_label>]
#   bump_type:        patch | minor | major | prerelease | graduate
#   prerelease_label: alpha | beta | rc   (optional, defaults to empty)

set -euo pipefail

CUR="${1:-}"
BUMP="${2:-}"
LABEL="${3:-}"

if [[ -z "$CUR" || -z "$BUMP" ]]; then
  echo "Usage: $0 <current_version> <patch|minor|major|prerelease|graduate> [<alpha|beta|rc>]" >&2
  exit 2
fi

if [[ ! "$CUR" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)(-(alpha|beta|rc)\.([0-9]+))?$ ]]; then
  echo "Invalid current version '$CUR': must match MAJOR.MINOR.PATCH[-LABEL.N]" >&2
  exit 1
fi

MAJ="${BASH_REMATCH[1]}"
MIN="${BASH_REMATCH[2]}"
PAT="${BASH_REMATCH[3]}"
CUR_LABEL="${BASH_REMATCH[5]:-}"
CUR_COUNT="${BASH_REMATCH[6]:-0}"

label_rank() {
  case "$1" in
    alpha) echo 1 ;;
    beta)  echo 2 ;;
    rc)    echo 3 ;;
    '')    echo 0 ;;
    *)     echo 99 ;;
  esac
}

case "$BUMP" in
  patch|minor|major)
    if [[ -n "$CUR_LABEL" && -z "$LABEL" ]]; then
      echo "Current '$CUR' is a pre-release. Use 'graduate' first, or pick a label (alpha|beta|rc) to continue the pre-release track." >&2
      exit 1
    fi
    case "$BUMP" in
      patch) PAT=$((PAT + 1)) ;;
      minor) MIN=$((MIN + 1)); PAT=0 ;;
      major) MAJ=$((MAJ + 1)); MIN=0; PAT=0 ;;
    esac
    if [[ -n "$LABEL" ]]; then
      NEW="${MAJ}.${MIN}.${PAT}-${LABEL}.1"
    else
      NEW="${MAJ}.${MIN}.${PAT}"
    fi
    ;;
  prerelease)
    if [[ -z "$CUR_LABEL" ]]; then
      echo "Current '$CUR' is stable. Start a pre-release track with patch|minor|major + a label." >&2
      exit 1
    fi
    if [[ -z "$LABEL" || "$LABEL" == "$CUR_LABEL" ]]; then
      NEW_COUNT=$((CUR_COUNT + 1))
      NEW="${MAJ}.${MIN}.${PAT}-${CUR_LABEL}.${NEW_COUNT}"
    else
      CUR_RANK=$(label_rank "$CUR_LABEL")
      NEW_RANK=$(label_rank "$LABEL")
      if (( NEW_RANK <= CUR_RANK )); then
        echo "Cannot transition pre-release backward or sideways ($CUR_LABEL -> $LABEL). Allowed order: alpha < beta < rc." >&2
        exit 1
      fi
      NEW="${MAJ}.${MIN}.${PAT}-${LABEL}.1"
    fi
    ;;
  graduate)
    if [[ -z "$CUR_LABEL" ]]; then
      echo "Current '$CUR' is already stable, nothing to graduate." >&2
      exit 1
    fi
    NEW="${MAJ}.${MIN}.${PAT}"
    ;;
  *)
    echo "Unknown bump_type '$BUMP' (expected: patch|minor|major|prerelease|graduate)." >&2
    exit 1
    ;;
esac

echo "$NEW"
