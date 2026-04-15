#!/usr/bin/env bash
# Tests for next_version.sh. Runs every case in the release-automation spec table
# plus all documented failure cases. Exits non-zero on any mismatch.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NV="${SCRIPT_DIR}/next_version.sh"

PASS=0
FAIL=0
FAILED_CASES=()

expect_ok() {
  local desc="$1"; shift
  local want="$1"; shift
  local got
  if ! got=$("$NV" "$@" 2>&1); then
    echo "FAIL: $desc -- expected '$want' but script errored: $got"
    FAIL=$((FAIL + 1))
    FAILED_CASES+=("$desc")
    return
  fi
  if [[ "$got" != "$want" ]]; then
    echo "FAIL: $desc -- expected '$want' got '$got'"
    FAIL=$((FAIL + 1))
    FAILED_CASES+=("$desc")
    return
  fi
  PASS=$((PASS + 1))
}

expect_fail() {
  local desc="$1"; shift
  if "$NV" "$@" >/dev/null 2>&1; then
    echo "FAIL: $desc -- expected failure but command succeeded"
    FAIL=$((FAIL + 1))
    FAILED_CASES+=("$desc")
    return
  fi
  PASS=$((PASS + 1))
}

# --- Happy path: stable bumps ---
expect_ok "stable patch"                  "3.5.1"               "3.5.0" "patch"
expect_ok "stable minor"                  "3.6.0"               "3.5.0" "minor"
expect_ok "stable major"                  "4.0.0"               "3.5.0" "major"

# --- Happy path: start pre-release on next bump ---
expect_ok "stable patch + alpha"          "3.5.1-alpha.1"       "3.5.0" "patch"  "alpha"
expect_ok "stable minor + beta"           "3.6.0-beta.1"        "3.5.0" "minor"  "beta"
expect_ok "stable major + rc"             "4.0.0-rc.1"          "3.5.0" "major"  "rc"

# --- Happy path: continue pre-release (prerelease + empty/same label) ---
expect_ok "alpha.1 -> alpha.2 (empty lbl)"  "3.6.0-alpha.2"     "3.6.0-alpha.1" "prerelease"
expect_ok "alpha.1 -> alpha.2 (same lbl)"   "3.6.0-alpha.2"     "3.6.0-alpha.1" "prerelease" "alpha"
expect_ok "beta.3 -> beta.4"                "3.6.0-beta.4"      "3.6.0-beta.3"  "prerelease"
expect_ok "rc.7 -> rc.8"                    "3.6.0-rc.8"        "3.6.0-rc.7"    "prerelease"

# --- Happy path: transition between pre-release labels ---
expect_ok "alpha.3 -> beta.1"             "3.6.0-beta.1"        "3.6.0-alpha.3" "prerelease" "beta"
expect_ok "alpha.3 -> rc.1"               "3.6.0-rc.1"          "3.6.0-alpha.3" "prerelease" "rc"
expect_ok "beta.2 -> rc.1"                "3.6.0-rc.1"          "3.6.0-beta.2"  "prerelease" "rc"

# --- Happy path: graduate ---
expect_ok "graduate rc.2 -> stable"       "3.6.0"               "3.6.0-rc.2"    "graduate"
expect_ok "graduate alpha.1 -> stable"    "3.6.0"               "3.6.0-alpha.1" "graduate"

# --- Failure: patch/minor/major on pre-release without label ---
expect_fail "patch on alpha without label"  "3.6.0-alpha.1" "patch"
expect_fail "minor on beta without label"   "3.6.0-beta.2"  "minor"
expect_fail "major on rc without label"     "3.6.0-rc.1"    "major"

# --- Failure: prerelease bump on stable ---
expect_fail "prerelease on stable"          "3.5.0"         "prerelease"
expect_fail "prerelease+label on stable"    "3.5.0"         "prerelease" "alpha"

# --- Failure: backward transition ---
expect_fail "beta -> alpha"                 "3.6.0-beta.2"  "prerelease" "alpha"
expect_fail "rc -> alpha"                   "3.6.0-rc.1"    "prerelease" "alpha"
expect_fail "rc -> beta"                    "3.6.0-rc.1"    "prerelease" "beta"

# --- Failure: graduate on stable ---
expect_fail "graduate on stable"            "3.5.0"         "graduate"

# --- Failure: malformed versions ---
expect_fail "malformed 4-part"              "3.5.0.1"       "patch"
expect_fail "malformed v-prefix"            "v3.5.0"        "patch"
expect_fail "malformed unknown label"       "3.5.0-dev.1"   "prerelease"
expect_fail "malformed missing counter"     "3.5.0-alpha"   "prerelease"

# --- Failure: unknown bump_type ---
expect_fail "unknown bump"                  "3.5.0"         "bogus"

echo ""
echo "Passed: $PASS"
echo "Failed: $FAIL"
if (( FAIL > 0 )); then
  printf '  - %s\n' "${FAILED_CASES[@]}"
  exit 1
fi
