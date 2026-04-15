# Release automation design

**Date:** 2026-04-15
**Status:** Draft, pending review
**Author:** Rob Hofmann

## Context

Cutting a release of this HACS integration currently requires a manual, multi-step dance:

1. Merge the feature PR to `main`.
2. Edit `custom_components/gree/manifest.json` by hand to bump the `version` field.
3. Commit, push, and open another PR for that bump.
4. Merge the bump PR.
5. Go to GitHub Releases, create a new tag matching the new version, write release notes.

This is five manual steps for something that should be a single decision ("this next release is a patch / minor / major / alpha"). The `manifest.json` version and the git tag are independent sources of truth today, which is where the friction lives.

**Outcome we want:** one click to start a release, one click to merge it, nothing else. The workflow should also support semver pre-release tracks (`alpha`, `beta`, `rc`) because users who opt into HACS beta should be able to receive test builds without destabilising the stable channel.

## Goals

- Maintainer triggers a release via GitHub Actions with a `bump_type` parameter (`patch | minor | major | prerelease | graduate`) and an optional `prerelease_label` (`alpha | beta | rc`).
- The workflow computes the next semver, writes it to `manifest.json`, opens a PR.
- Merging the PR automatically creates the matching git tag and GitHub Release with auto-generated notes.
- Pre-release versions create GitHub Releases flagged as `prerelease: true` so only HACS beta-track users see them.
- No personal access tokens, no GitHub App, no external services. Default `GITHUB_TOKEN` only.

## Non-goals

- Automatic bumping based on conventional commits (`release-please` style). Deliberately out of scope: single-maintainer repo, existing commit style is free-form, no need for commit-message regime change.
- Maintaining a curated `CHANGELOG.md` file. GitHub's auto-generated release notes (PR titles since last tag) are sufficient.
- Multi-package / monorepo handling. One integration, one version.
- Custom pre-release labels beyond `alpha | beta | rc`.

## Constraints

- `main` is protected; workflows cannot push to it directly. They must open PRs and wait for a human merge.
- Actions performed with the default `GITHUB_TOKEN` do not trigger downstream workflows that listen on `pull_request` events. The publish step therefore listens on `push: main` instead, which fires normally when a human clicks "Merge".
- Must not mention Claude, AI, or any AI tooling in commit messages, PR titles, PR bodies, tag messages, or branch names.

## Architecture

Two workflow files in `.github/workflows/`:

```
┌────────────────────┐            ┌────────────────────┐            ┌────────────────────┐
│ release-bump.yml   │            │ human reviews PR   │            │ release-publish.yml│
│ workflow_dispatch  │   opens    │ and clicks         │  push:main │ push: main trigger │
│ inputs:            │───PR──────▶│ "Squash and merge" │──fires────▶│ with path filter   │
│  - bump_type       │            │                    │            │ on manifest.json   │
│  - prerelease_label│            │                    │            │                    │
└────────────────────┘            └────────────────────┘            └────────────────────┘
         │                                                                    │
         ▼                                                                    ▼
 branch release/X.Y.Z                                             tag vX.Y.Z + GitHub
 with bumped manifest.json                                        Release (auto notes)
```

The publish workflow triggers on `push: main` (not on PR merge) specifically to sidestep GitHub's rule that `GITHUB_TOKEN`-authored PR events do not fire downstream workflows. A human's merge click produces a normal `push` event which always fires.

## Workflow 1 — `release-bump.yml`

### Triggers and inputs

```yaml
on:
  workflow_dispatch:
    inputs:
      bump_type:
        type: choice
        options: [patch, minor, major, prerelease, graduate]
        default: patch
      prerelease_label:
        type: choice
        options: ['', alpha, beta, rc]
        default: ''
```

### Permissions

```yaml
permissions:
  contents: write         # push branch
  pull-requests: write    # gh pr create
```

### Steps (logical, implemented in bash)

1. `actions/checkout@v4` — full history on `main`.
2. Read current version: `CUR=$(jq -r '.version' custom_components/gree/manifest.json)`.
3. Validate `CUR` matches the strict regex `^[0-9]+\.[0-9]+\.[0-9]+(-(alpha|beta|rc)\.[0-9]+)?$`. Fail loudly if not.
4. Compute `NEW` per the version-math table below. Fail loudly on any unsupported transition (see failure cases).
5. Rewrite `manifest.json` with `NEW` (use `jq --indent 2` then `mv` to preserve formatting).
6. Create branch `release/$NEW`, commit with message `Release v$NEW`, push.
7. `gh pr create --title "Release v$NEW" --body "Merging this PR will tag v$NEW and publish a GitHub Release with auto-generated notes."`.

### Version math

Let `CUR = MAJOR.MINOR.PATCH[-LABEL.N]`.

| Current | `bump_type` | `prerelease_label` | Next | Rule |
|---|---|---|---|---|
| `3.5.0` | `patch` | `''` | `3.5.1` | normal patch |
| `3.5.0` | `minor` | `''` | `3.6.0` | normal minor |
| `3.5.0` | `major` | `''` | `4.0.0` | normal major |
| `3.5.0` | `patch` | `alpha` | `3.5.1-alpha.1` | start pre-release track on next patch |
| `3.5.0` | `minor` | `beta` | `3.6.0-beta.1` | start pre-release track on next minor |
| `3.5.0` | `major` | `rc` | `4.0.0-rc.1` | start pre-release track on next major |
| `3.6.0-alpha.1` | `prerelease` | `''` | `3.6.0-alpha.2` | increment counter, keep current label |
| `3.6.0-beta.3` | `prerelease` | `''` | `3.6.0-beta.4` | increment counter, keep current label |
| `3.6.0-alpha.3` | `prerelease` | `beta` | `3.6.0-beta.1` | transition label forward, counter resets to 1 |
| `3.6.0-beta.2` | `prerelease` | `rc` | `3.6.0-rc.1` | transition label forward, counter resets to 1 |
| `3.6.0-rc.2` | `graduate` | `''` | `3.6.0` | strip pre-release suffix |

Label ordering for transitions: `alpha < beta < rc`. Transitions may only move forward in this ordering.

### Failure cases (must abort with a clear error before any push)

- `patch | minor | major` with empty label when `CUR` already has a pre-release suffix. *(Rationale: ambiguous — are you re-starting the pre-release track, or finalising? Force the maintainer to pick `graduate` or re-specify a label.)*
- `prerelease` when `CUR` is stable. *(Rationale: starting a new pre-release track requires picking a version, which means `patch/minor/major` + a label.)*
- `prerelease` with a label that moves backwards in the `alpha < beta < rc` ordering relative to the current label.
- `graduate` when `CUR` is already stable.
- `CUR` does not match the strict regex.

## Workflow 2 — `release-publish.yml`

### Trigger

```yaml
on:
  push:
    branches: [main]
    paths: ['custom_components/gree/manifest.json']
```

### Permissions

```yaml
permissions:
  contents: write         # create tag + release
```

### Steps

1. `actions/checkout@v4` — fetch-depth 0, needed for tag operations.
2. Read `V=$(jq -r '.version' custom_components/gree/manifest.json)`.
3. Idempotency guard: `if git rev-parse "v$V" >/dev/null 2>&1; then exit 0; fi`. Treats re-runs and unrelated manifest edits gracefully.
4. Create annotated tag: `git tag -a "v$V" -m "Release v$V"` and `git push origin "v$V"`.
5. Detect pre-release: `PRE_FLAG=$(if [[ "$V" == *-* ]]; then echo "--prerelease"; fi)`.
6. `gh release create "v$V" --generate-notes --title "v$V" $PRE_FLAG`.

### Behaviour summary

- First `push: main` after a merged release PR: creates tag and release.
- Re-run / unrelated edits to `manifest.json`: no-op (tag already exists).
- Pre-release versions: Release marked as pre-release on GitHub; HACS shows them only to users who opt into betas.

## One-time GitHub setting

Repository → *Settings → Actions → General → Workflow permissions*: check **"Allow GitHub Actions to create and approve pull requests"**. Without this, `gh pr create` from within a workflow returns HTTP 403. This is the only configuration outside the YAML files.

## Safety analysis

- **Idempotency**: publish is a no-op when the tag already exists. Re-running workflows cannot double-tag or double-release.
- **No half-state**: the bump workflow validates regex and computes the next version *before* any git operation. Failure here aborts cleanly with no branch created. If `git push` succeeds but `gh pr create` subsequently fails (e.g., network glitch, revoked permission), the orphan branch is harmless and can be deleted manually; re-running the workflow after fixing the cause will fail on branch collision (handled below) which forces deliberate cleanup.
- **Branch collision**: if `release/X.Y.Z` already exists from a previous abandoned attempt, the push fails. Recovery: delete the branch in the UI and re-run. Safe, explicit.
- **Ad-hoc manifest edits**: if the maintainer edits `manifest.json` manually (typo fix, `documentation` URL change), `release-publish` runs, reads the unchanged version, sees tag exists, no-ops. Cost: one ~10-second workflow run. Acceptable.
- **Concurrency**: two simultaneous bump runs would produce two branches targeting different versions; whichever PR merges first wins, the other is closed manually. Not worth adding `concurrency:` blocks.
- **Semver ordering**: git tags `v3.6.0-alpha.1` sort before `v3.6.0` per semver pre-release rules. HACS honours this for update detection.

## Rollout plan

1. Single PR titled `Add release automation workflows` adds the two YAML files and this spec.
2. After merge, toggle the repo setting in *Actions → General* mentioned above.
3. **First smoke test — patch release**: run `release-bump` with `bump_type: patch`, empty label. Expect a PR for `3.5.1`. Merge it. Verify:
   - Tag `v3.5.1` exists.
   - GitHub Release `v3.5.1` was created with auto-generated notes listing PRs merged since `v3.5.0`.
   - Release is not marked pre-release.
4. **Second smoke test — pre-release**: run `release-bump` with `bump_type: minor`, label `alpha`. Expect a PR for `3.6.0-alpha.1`. Merge. Verify the release is marked pre-release.
5. If any smoke test fails mid-flow: close the PR, delete the branch, iterate on the YAML. Nothing ships to users until the PR merges and the publish workflow runs to completion.

## Files touched

| Path | Change |
|---|---|
| `.github/workflows/release-bump.yml` | new |
| `.github/workflows/release-publish.yml` | new |
| `docs/superpowers/specs/2026-04-15-release-automation-design.md` | new (this document) |

No changes to `custom_components/gree/` or `manifest.json` in the initial PR — the workflows become useful on the *next* release after merge.

## Open questions

None at this time.
