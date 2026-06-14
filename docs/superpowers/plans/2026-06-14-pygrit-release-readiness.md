# pygrit Release-Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing read-core `pygrit` MVP installable from PyPI (`pip install pygrit`) by adding packaging metadata and a trusted-publishing release workflow — with zero changes to the binding code or the existing test suite.

**Architecture:** Three in-repo changes plus two human-only one-time setup steps. (1) Fill in `Cargo.toml`/`pyproject.toml` packaging metadata. (2) Add a small, unit-tested release-inventory checker under `.github/scripts/`. (3) Add `.github/workflows/release.yml`, a dedicated trusted-publishing (OIDC, no stored secrets) pipeline that mirrors CI's proven build recipe and gates publishing behind version, provenance, and inventory checks. (4) Document the release procedure in `README.md`. (5) [Maintainer, manual] register the PyPI/TestPyPI pending publishers and create the protected GitHub Environments. The workflow publishes only the three CI-validated wheel targets (Linux x86_64 + aarch64, macOS arm64) plus an sdist.

**Tech Stack:** GitHub Actions, PyPI Trusted Publishing (OIDC), `pypa/gh-action-pypi-publish`, maturin `abi3` wheels, PyO3, Rust 1.94.1 (pinned), uv (uv-only tooling — no pip/poetry).

**Spec:** `docs/superpowers/specs/2026-06-14-pygrit-release-readiness-design.md` (read it for rationale; this plan is the executable form).

**Execution note (branch/worktree):** This plan modifies CI/CD and packaging on a published repo. Per superpowers:subagent-driven-development + superpowers:using-git-worktrees, execute on an isolated worktree/feature branch, **not** directly on `main`. Do not `git push` or perform the Task 5 human steps without explicit maintainer confirmation.

---

## File Structure

| File | Action | Responsibility |
| --- | --- | --- |
| `Cargo.toml` | Modify (`[package]`) | Crate metadata: `description`, `repository`, `homepage`, `documentation` (clears the maturin manifest warning; feeds Rust-side metadata). |
| `pyproject.toml` | Modify (add `[project.urls]`) | PyPI sidebar links (Homepage / Repository / Issues). |
| `.github/scripts/check_release_inventory.py` | Create | Typed, testable checker: asserts `dist/` holds exactly 3 `cp311-abi3` wheels + 1 sdist, all the same version. Imported by its test; invoked by the publish jobs. |
| `.github/scripts/test_check_release_inventory.py` | Create | Unit tests for the checker (release tooling — deliberately **outside** `tests/`, so the binding suite is untouched and CI's `pytest tests/` does not collect it). |
| `.github/workflows/release.yml` | Create | The trusted-publishing release pipeline: `version-guard` → `build` (3 targets) + `sdist` → `publish-pypi` / `publish-testpypi`. |
| `README.md` | Modify (add `## Releasing`) | Maintainer docs: one-time trusted-publisher/environment setup + cut-a-release procedure + TestPyPI dry-run. |

---

## Task 1: Packaging metadata (`Cargo.toml` + `pyproject.toml`)

**Files:**
- Modify: `Cargo.toml` (the `[package]` table, lines 1–6)
- Modify: `pyproject.toml` (insert a `[project.urls]` table after the `[project]` table)
- No code test — verified via `cargo metadata` and the generated sdist `PKG-INFO`.

- [ ] **Step 1: Capture the current (pre-change) state**

Run:
```bash
cargo metadata --locked --format-version=1 \
  | python3 -c "import json,sys; p=[x for x in json.load(sys.stdin)['packages'] if x['name']=='pygrit'][0]; print('description=',p.get('description')); print('repository=',p.get('repository')); print('homepage=',p.get('homepage')); print('documentation=',p.get('documentation'))"
```
Expected (the fields are absent today):
```
description= None
repository= None
homepage= None
documentation= None
```

- [ ] **Step 2: Add the four metadata fields to `Cargo.toml`'s `[package]` table**

Replace the existing `[package]` block:
```toml
[package]
name = "pygrit"
version = "0.1.0"
edition = "2021"
license = "MIT"
publish = false
```
with:
```toml
[package]
name = "pygrit"
version = "0.1.0"
edition = "2021"
license = "MIT"
description = "Python bindings for grit-lib (a Rust reimplementation of Git)"
repository = "https://github.com/linsomniac/pygrit"
homepage = "https://github.com/linsomniac/pygrit"
documentation = "https://github.com/linsomniac/pygrit"
publish = false
```
(`description` deliberately matches the existing `pyproject.toml` `description` string. `publish = false` stays — this crate is never published to crates.io.)

- [ ] **Step 3: Add `[project.urls]` to `pyproject.toml`**

Insert this table immediately after the `dynamic = ["version"]` line (i.e. right after the `[project]` table closes, before `[tool.maturin]`):
```toml
[project.urls]
Homepage = "https://github.com/linsomniac/pygrit"
Repository = "https://github.com/linsomniac/pygrit"
Issues = "https://github.com/linsomniac/pygrit/issues"
```

- [ ] **Step 4: Verify `cargo metadata` now reports all four fields**

Run:
```bash
cargo metadata --locked --format-version=1 \
  | python3 -c "import json,sys; p=[x for x in json.load(sys.stdin)['packages'] if x['name']=='pygrit'][0]; assert p['description'] and p['repository'] and p['homepage'] and p['documentation'], p; print('cargo metadata OK:', p['repository'])"
```
Expected:
```
cargo metadata OK: https://github.com/linsomniac/pygrit
```

- [ ] **Step 5: Verify the maturin manifest warning is gone and the URLs land in the sdist `PKG-INFO`**

Run:
```bash
rm -rf /tmp/pygrit-meta && uv run maturin sdist --out /tmp/pygrit-meta 2>&1 | tee /tmp/pygrit-sdist.log
grep -i "manifest has no" /tmp/pygrit-sdist.log && echo "WARNING STILL PRESENT (FAIL)" || echo "warning cleared OK"
tar -xzOf /tmp/pygrit-meta/pygrit-0.1.0.tar.gz pygrit-0.1.0/PKG-INFO | grep -i "^Project-URL"
```
Expected:
```
warning cleared OK
Project-URL: Homepage, https://github.com/linsomniac/pygrit
Project-URL: Repository, https://github.com/linsomniac/pygrit
Project-URL: Issues, https://github.com/linsomniac/pygrit/issues
```
(If `grep -i "manifest has no"` had matched, the `&&` branch would print `WARNING STILL PRESENT (FAIL)` — that is a failure; the fields were not picked up.)

- [ ] **Step 6: Commit**

```bash
git add Cargo.toml pyproject.toml
git commit -m "build: add packaging metadata for PyPI (urls, repository, description)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Release-inventory checker (`.github/scripts/check_release_inventory.py` + test)

This is a tiny, typed, pure-Python helper the publish jobs call to assert the
collected artifact set is exactly right before any upload. It is fully unit-tested
locally (TDD), which is the one piece of the release pipeline that *can* be tested
offline. It lives under `.github/scripts/` (not `tests/`) so the binding test suite
stays untouched and CI's `pytest tests/` does not collect it.

**Files:**
- Create: `.github/scripts/check_release_inventory.py`
- Create: `.github/scripts/test_check_release_inventory.py`

- [ ] **Step 1: Write the failing test**

Create `.github/scripts/test_check_release_inventory.py`:
```python
"""Tests for the release-inventory checker.

Release tooling — intentionally outside ``tests/`` so the binding suite (run by
CI's ``pytest tests/``) does not collect it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from check_release_inventory import check_inventory  # noqa: E402


def _touch(directory: Path, name: str) -> None:
    (directory / name).write_bytes(b"")


def _good_dist(directory: Path, version: str = "0.1.0") -> None:
    _touch(directory, f"pygrit-{version}.tar.gz")
    _touch(
        directory,
        f"pygrit-{version}-cp311-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl",
    )
    _touch(
        directory,
        f"pygrit-{version}-cp311-abi3-manylinux_2_17_aarch64.manylinux2014_aarch64.whl",
    )
    _touch(directory, f"pygrit-{version}-cp311-abi3-macosx_11_0_arm64.whl")


def test_valid_inventory_passes(tmp_path: Path) -> None:
    _good_dist(tmp_path)
    assert check_inventory(tmp_path) == []


def test_missing_sdist_fails(tmp_path: Path) -> None:
    _good_dist(tmp_path)
    (tmp_path / "pygrit-0.1.0.tar.gz").unlink()
    errors = check_inventory(tmp_path)
    assert any("sdist" in e for e in errors), errors


def test_extra_sdist_fails(tmp_path: Path) -> None:
    _good_dist(tmp_path)
    _touch(tmp_path, "pygrit-0.1.0.zip.tar.gz")
    errors = check_inventory(tmp_path)
    assert any("sdist" in e for e in errors), errors


def test_wrong_wheel_count_fails(tmp_path: Path) -> None:
    _good_dist(tmp_path)
    (tmp_path / "pygrit-0.1.0-cp311-abi3-macosx_11_0_arm64.whl").unlink()
    errors = check_inventory(tmp_path)
    assert any("3 wheels" in e for e in errors), errors


def test_non_abi3_wheel_fails(tmp_path: Path) -> None:
    _good_dist(tmp_path)
    (tmp_path / "pygrit-0.1.0-cp311-abi3-macosx_11_0_arm64.whl").unlink()
    _touch(tmp_path, "pygrit-0.1.0-cp311-cp311-macosx_11_0_arm64.whl")
    errors = check_inventory(tmp_path)
    assert any("abi3" in e for e in errors), errors


def test_version_mismatch_fails(tmp_path: Path) -> None:
    _good_dist(tmp_path)
    (tmp_path / "pygrit-0.1.0-cp311-abi3-macosx_11_0_arm64.whl").unlink()
    _touch(tmp_path, "pygrit-0.2.0-cp311-abi3-macosx_11_0_arm64.whl")
    errors = check_inventory(tmp_path)
    assert any("version" in e for e in errors), errors
```

- [ ] **Step 2: Run the test to verify it fails (module does not exist yet)**

Run:
```bash
uv run pytest .github/scripts/test_check_release_inventory.py -q
```
Expected: collection/import error — `ModuleNotFoundError: No module named 'check_release_inventory'` (the implementation does not exist yet).

- [ ] **Step 3: Write the implementation**

Create `.github/scripts/check_release_inventory.py`:
```python
#!/usr/bin/env python3
"""Validate the release artifact set before publishing to PyPI.

Asserts that a ``dist/`` directory contains exactly the artifacts the release
workflow is expected to produce: three CPython ``abi3`` wheels (one per target
platform) and one sdist, every file carrying the same project version. Any
deviation -- a missing or extra artifact, a version disagreement, a non-abi3
wheel -- is a hard error, so a malformed upload set can never reach PyPI.

Because each target platform yields a uniquely named wheel, "exactly 3 wheels"
already implies three distinct platforms; there is no separate platform-tag
check (the exact tag strings shift with runner images and would be brittle).

Usage: ``python check_release_inventory.py <dist-dir>``
"""

from __future__ import annotations

import sys
from pathlib import Path

DIST_NAME = "pygrit"
EXPECTED_WHEELS = 3
SDIST_SUFFIX = ".tar.gz"
WHEEL_SUFFIX = ".whl"


def check_inventory(dist_dir: Path) -> list[str]:
    """Return a list of human-readable problems with ``dist_dir`` (empty == OK)."""
    errors: list[str] = []
    versions: set[str] = set()

    sdists = sorted(dist_dir.glob(f"*{SDIST_SUFFIX}"))
    if len(sdists) != 1:
        names = [p.name for p in sdists]
        errors.append(f"expected exactly 1 sdist (*{SDIST_SUFFIX}), found {len(sdists)}: {names}")
    for sdist in sdists:
        stem = sdist.name[: -len(SDIST_SUFFIX)]
        parts = stem.split("-")
        if len(parts) != 2 or parts[0] != DIST_NAME:
            errors.append(f"unexpected sdist filename: {sdist.name}")
            continue
        versions.add(parts[1])

    wheels = sorted(dist_dir.glob(f"*{WHEEL_SUFFIX}"))
    if len(wheels) != EXPECTED_WHEELS:
        names = [p.name for p in wheels]
        errors.append(f"expected exactly {EXPECTED_WHEELS} wheels, found {len(wheels)}: {names}")
    for wheel in wheels:
        stem = wheel.name[: -len(WHEEL_SUFFIX)]
        parts = stem.split("-")
        # Expected: name-version-pythontag-abitag-platformtag (no build tag).
        if len(parts) != 5 or parts[0] != DIST_NAME:
            errors.append(f"unexpected wheel filename: {wheel.name}")
            continue
        _, version, python_tag, abi_tag, _platform = parts
        versions.add(version)
        if python_tag != "cp311" or abi_tag != "abi3":
            errors.append(f"wheel is not cp311-abi3: {wheel.name}")

    if len(versions) > 1:
        errors.append(f"artifacts disagree on version: {sorted(versions)}")

    return errors


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <dist-dir>", file=sys.stderr)
        return 2
    dist_dir = Path(argv[1])
    if not dist_dir.is_dir():
        print(f"not a directory: {dist_dir}", file=sys.stderr)
        return 2
    errors = check_inventory(dist_dir)
    if errors:
        for err in errors:
            print(f"::error::release inventory: {err}", file=sys.stderr)
        return 1
    print(f"release inventory OK: {EXPECTED_WHEELS} wheels + 1 sdist, single version")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
uv run pytest .github/scripts/test_check_release_inventory.py -q
```
Expected: `6 passed`.

- [ ] **Step 5: Format and type-check the new Python (global CLAUDE.md conventions)**

Run:
```bash
uv run ruff format .github/scripts/check_release_inventory.py .github/scripts/test_check_release_inventory.py
uv run ruff check .github/scripts/check_release_inventory.py .github/scripts/test_check_release_inventory.py
uv run mypy .github/scripts/check_release_inventory.py
```
Expected: ruff reports no issues (it may reformat — re-run the pytest from Step 4 if it does); `mypy` reports `Success: no issues found in 1 source file`.

(`mypy` is run on the checker module only. The test uses a `sys.path` import shim that mypy cannot resolve by module name; that is acceptable for release tooling and does not affect the gated `mypy python tests` in CI.)

- [ ] **Step 6: Commit**

```bash
git add .github/scripts/check_release_inventory.py .github/scripts/test_check_release_inventory.py
git commit -m "ci: add release-inventory checker for the publish gate" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Release workflow (`.github/workflows/release.yml`)

The dedicated trusted-publishing pipeline. It must mirror CI's proven build recipe
(so we ship exactly what CI validates) and keep the OIDC `id-token: write`
permission off the everyday push/PR workflow.

**Files:**
- Create: `.github/workflows/release.yml`
- No code test — validated by `uvx yamllint`, a structural grep self-check, the
  `gh`-confirmed publish-action pin, and (post-merge, by the maintainer) a TestPyPI
  `workflow_dispatch` dry-run.

- [ ] **Step 1: Confirm the pinned publish-action SHA still resolves to v1.14.0**

The publish action is the one credential/OIDC-bearing action and is commit-SHA-pinned. Verify the pin before writing it:
```bash
gh api repos/pypa/gh-action-pypi-publish/commits/v1.14.0 --jq '.sha'
```
Expected:
```
cef221092ed1bacb1cc03d23a2d87d1d172e277b
```
If the printed SHA differs (e.g. the tag was re-cut), use the printed value in Step 2 instead, and update the trailing `# v1.14.0` comment accordingly.

- [ ] **Step 2: Write `.github/workflows/release.yml`**

Create the file with exactly this content (if Step 1 printed a different SHA, substitute it in both `publish-*` jobs):
```yaml
# Trusted-publishing release pipeline for pygrit (PyO3 + maturin abi3 bindings).
#
# Separate from ci.yml so the OIDC `id-token: write` permission never lives in the
# everyday push/PR workflow. Flow:
#   version-guard  — (release only) tag must be vX.Y.Z and equal the crate version.
#   build          — 3 targets (linux x86_64/aarch64, macOS arm64): build the abi3
#                    wheel, assert exactly one cp311-abi3 wheel, import-smoke it
#                    (native on x86_64/macOS; emulated arm64 via QEMU), upload.
#   sdist          — build the sdist with the locked maturin, source-compile +
#                    import-smoke it, upload.
#   publish-pypi   — (release) provenance + inventory gate, then OIDC publish to PyPI.
#   publish-testpypi (workflow_dispatch) — same gate, OIDC publish to TestPyPI.
#
# Conventions (match ci.yml): pinned Rust 1.94.1, --locked builds, setup-uv@v8.2.0
# (no floating major exists), checkout@v6 / upload-artifact@v7 / download-artifact@v7
# (node24, v4+ backend). Only the publish action is commit-SHA-pinned (it handles
# the OIDC credential / upload); other actions follow ci.yml's floating-major style.

name: Release

on:
  release:
    types: [published]      # -> real PyPI
  workflow_dispatch: {}     # -> TestPyPI dry-run

permissions:
  contents: read

concurrency:
  group: release-${{ github.event.release.tag_name || github.ref }}
  cancel-in-progress: false   # never cancel a partially-completed publish

jobs:
  version-guard:
    name: version guard
    runs-on: ubuntu-latest
    if: github.event_name == 'release'
    steps:
      - uses: actions/checkout@v6
        with:
          persist-credentials: false
      - uses: dtolnay/rust-toolchain@1.94.1
      - name: Assert tag matches crate version
        shell: bash
        run: |
          set -euo pipefail
          tag="${{ github.event.release.tag_name }}"
          # v1 policy: final releases only, vX.Y.Z (no PEP 440 prereleases — see spec).
          if [[ ! "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
            echo "::error::Release tag '$tag' is not of the form vX.Y.Z (final releases only)."
            exit 1
          fi
          tag_version="${tag#v}"
          crate_version="$(cargo metadata --locked --format-version=1 \
            | python3 -c "import json,sys; print([p['version'] for p in json.load(sys.stdin)['packages'] if p['name']=='pygrit'][0])")"
          echo "tag=$tag_version crate=$crate_version"
          if [[ "$tag_version" != "$crate_version" ]]; then
            echo "::error::Tag version ($tag_version) != crate version ($crate_version). Bump Cargo.toml AND Cargo.lock."
            exit 1
          fi
          echo "version-guard OK: $tag_version"

  build:
    name: build (${{ matrix.os }} ${{ matrix.target }})
    needs: [version-guard]
    # version-guard is skipped on workflow_dispatch (its own `if`); allow build to
    # run when the guard either succeeded (release) or was skipped (dispatch), but
    # not when it actually failed.
    if: always() && (needs.version-guard.result == 'success' || needs.version-guard.result == 'skipped')
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        include:
          - os: ubuntu-latest
            target: x86_64
            smoke: native
          - os: ubuntu-latest
            target: aarch64
            smoke: emulated
          - os: macos-14
            target: aarch64
            smoke: native
    steps:
      - uses: actions/checkout@v6
        with:
          persist-credentials: false
      - uses: dtolnay/rust-toolchain@1.94.1
      - uses: PyO3/maturin-action@v1
        with:
          target: ${{ matrix.target }}
          args: --release --locked --out dist
          manylinux: "2014"
      - name: Verify exactly one cp311-abi3 wheel
        shell: bash
        run: |
          set -euo pipefail
          shopt -s nullglob
          wheels=(dist/*-cp311-abi3-*.whl)
          if [[ ${#wheels[@]} -ne 1 ]]; then
            echo "::error::expected exactly one *-cp311-abi3-*.whl, found ${#wheels[@]}: ${wheels[*]:-<none>}"
            ls -la dist || true
            exit 1
          fi
          echo "abi3 wheel OK: ${wheels[0]}"
      - name: Set up Python 3.11 for native smoke
        if: matrix.smoke == 'native'
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Import smoke (native, Python 3.11)
        if: matrix.smoke == 'native'
        shell: bash
        run: |
          set -euxo pipefail
          python -m venv /tmp/smoke
          /tmp/smoke/bin/python -m pip install --upgrade pip
          /tmp/smoke/bin/pip install dist/*-cp311-abi3-*.whl
          /tmp/smoke/bin/python -c "import pygrit; pygrit.Repository"
          /tmp/smoke/bin/python -c "import pygrit, os; p=os.path.dirname(pygrit.__file__); assert 'site-packages' in p, p; print('imported from', p)"
      - name: Set up QEMU for emulated arm64 smoke
        if: matrix.smoke == 'emulated'
        uses: docker/setup-qemu-action@v3
      - name: Import smoke (emulated aarch64, Python 3.11 container)
        if: matrix.smoke == 'emulated'
        shell: bash
        run: |
          set -euxo pipefail
          wheel="$(ls dist/*-cp311-abi3-*.whl)"
          docker run --rm --platform linux/arm64 \
            -v "$PWD/dist:/dist:ro" python:3.11-slim \
            bash -c "pip install /dist/$(basename "$wheel") && python -c 'import pygrit; pygrit.Repository'"
      - uses: actions/upload-artifact@v7
        with:
          name: wheels-${{ matrix.os }}-${{ matrix.target }}
          path: dist
          if-no-files-found: error

  sdist:
    name: sdist
    needs: [version-guard]
    if: always() && (needs.version-guard.result == 'success' || needs.version-guard.result == 'skipped')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
        with:
          persist-credentials: false
      - uses: dtolnay/rust-toolchain@1.94.1
      - uses: astral-sh/setup-uv@v8.2.0
      - run: uv sync --group dev
      - name: Build sdist (locked maturin)
        run: uv run maturin sdist --out dist
      - name: Source-compile + import-smoke the sdist
        shell: bash
        run: |
          set -euxo pipefail
          python3 -m venv /tmp/sdisttest
          /tmp/sdisttest/bin/python -m pip install --upgrade pip
          /tmp/sdisttest/bin/pip install dist/pygrit-*.tar.gz
          /tmp/sdisttest/bin/python -c "import pygrit; pygrit.Repository"
      - uses: actions/upload-artifact@v7
        with:
          name: sdist
          path: dist
          if-no-files-found: error

  publish-pypi:
    name: publish to PyPI
    needs: [build, sdist]
    if: github.event_name == 'release'
    runs-on: ubuntu-latest
    environment: pypi
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0
          persist-credentials: false
      - name: Provenance — built commit must be an ancestor of origin/main
        shell: bash
        run: |
          set -euo pipefail
          git fetch --no-tags origin main
          if ! git merge-base --is-ancestor "$GITHUB_SHA" origin/main; then
            echo "::error::commit $GITHUB_SHA is not an ancestor of origin/main; refusing to publish."
            exit 1
          fi
          echo "provenance OK: $GITHUB_SHA is on origin/main"
      - uses: actions/download-artifact@v7
        with:
          pattern: "*"
          merge-multiple: true
          path: dist
      - name: Inventory — exactly 3 wheels + 1 sdist, single version
        shell: bash
        run: |
          set -euo pipefail
          ls -la dist
          python3 .github/scripts/check_release_inventory.py dist
      - uses: pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b  # v1.14.0
        with:
          packages-dir: dist

  publish-testpypi:
    name: publish to TestPyPI
    needs: [build, sdist]
    if: github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    environment: testpypi
    permissions:
      id-token: write
      contents: read
    steps:
      - uses: actions/checkout@v6
        with:
          fetch-depth: 0
          persist-credentials: false
      - name: Provenance — built commit must be an ancestor of origin/main
        shell: bash
        run: |
          set -euo pipefail
          git fetch --no-tags origin main
          if ! git merge-base --is-ancestor "$GITHUB_SHA" origin/main; then
            echo "::error::commit $GITHUB_SHA is not an ancestor of origin/main; refusing to publish."
            exit 1
          fi
          echo "provenance OK: $GITHUB_SHA is on origin/main"
      - uses: actions/download-artifact@v7
        with:
          pattern: "*"
          merge-multiple: true
          path: dist
      - name: Inventory — exactly 3 wheels + 1 sdist, single version
        shell: bash
        run: |
          set -euo pipefail
          ls -la dist
          python3 .github/scripts/check_release_inventory.py dist
      - uses: pypa/gh-action-pypi-publish@cef221092ed1bacb1cc03d23a2d87d1d172e277b  # v1.14.0
        with:
          repository-url: https://test.pypi.org/legacy/
          packages-dir: dist
```

- [ ] **Step 3: Validate YAML syntax**

Run:
```bash
uvx yamllint -d relaxed .github/workflows/release.yml && echo "yamllint OK"
```
Expected: `yamllint OK` (exit 0). The `relaxed` profile keeps real syntax errors fatal while ignoring style nits (line length, `on:` truthiness); style warnings, if any, are acceptable.

- [ ] **Step 4: Structural self-check (all required jobs/gates present)**

Run:
```bash
for k in \
  "name: version guard" \
  "name: build (" \
  "name: sdist" \
  "publish-pypi:" \
  "publish-testpypi:" \
  "id-token: write" \
  "persist-credentials: false" \
  "manylinux: \"2014\"" \
  "docker/setup-qemu-action@v3" \
  "check_release_inventory.py dist" \
  "merge-base --is-ancestor" \
  "cef221092ed1bacb1cc03d23a2d87d1d172e277b" \
  "test.pypi.org/legacy"; do
  grep -qF "$k" .github/workflows/release.yml && echo "OK : $k" || echo "MISSING: $k"
done
```
Expected: every line prints `OK : …` (no `MISSING:`).

- [ ] **Step 5: Confirm the everyday workflow was NOT given OIDC permission**

Run:
```bash
grep -n "id-token" .github/workflows/ci.yml && echo "UNEXPECTED: ci.yml has id-token" || echo "ci.yml clean (no id-token) OK"
```
Expected: `ci.yml clean (no id-token) OK`.

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add trusted-publishing release workflow (PyPI + TestPyPI)" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: README "Releasing" section

Document the cut-a-release procedure and the one-time maintainer setup so the
human steps in Task 5 (and every future release) are discoverable in-repo.

**Files:**
- Modify: `README.md` (add a `## Releasing` section)

- [ ] **Step 1: Add the `## Releasing` section to `README.md`**

Insert this section immediately **before** the final `## License` section (so it sits after "How it maps to grit-lib" / "Version compatibility"):
```markdown
## Releasing

pygrit publishes to PyPI via [trusted publishing](https://docs.pypi.org/trusted-publishers/)
(OpenID Connect) — no API tokens are stored in the repo. Publishing a GitHub Release
runs [`.github/workflows/release.yml`](.github/workflows/release.yml), which rebuilds
and re-smoke-tests the exact wheels + sdist that CI validates, checks the tag and
provenance, and uploads to PyPI over OIDC.

### One-time setup (maintainer, manual)

These cannot be automated and must be done once before the first release:

1. **Register the PyPI "pending publisher"** at
   <https://pypi.org/manage/account/publishing/>:
   - PyPI Project Name: `pygrit`
   - Owner: `linsomniac`
   - Repository name: `pygrit`
   - Workflow name: `release.yml`
   - Environment name: `pypi`

   For the dry-run path, repeat at <https://test.pypi.org/manage/account/publishing/>
   with Environment name `testpypi`. A pending publisher does **not** reserve the
   name, so cut the first real release promptly to claim `pygrit`.

2. **Create the protected GitHub Environments** (Settings → Environments). GitHub
   silently auto-creates an *unprotected* environment if a workflow merely
   references one, so create them explicitly:
   - `pypi` — restrict deployments to protected `v*` tags (back it with a repository
     ruleset that protects `v*` tags). Required-reviewer protection is impractical
     for a solo maintainer (self-review is blocked); add a reviewer if the project
     gains maintainers.
   - `testpypi` — restrict deployments to the `main` branch.

### Cutting a release

1. Bump the version in **both** `Cargo.toml` (`[package] version`) **and**
   `Cargo.lock`: edit `Cargo.toml`, then run `cargo update -p pygrit` (or `cargo
   build` without `--locked`) so the lockfile matches. The workflow's `cargo
   metadata --locked` version guard fails if `Cargo.lock` is stale.
2. Commit to `main` and push.
3. Create a GitHub Release with tag **`vX.Y.Z`** (final releases only — the version
   guard rejects anything that is not `vX.Y.Z`). Publishing the release builds and
   smoke-tests the three wheels + sdist, verifies `tag == crate version` and that the
   commit is on `main`, and publishes to PyPI automatically.

### TestPyPI dry-run (optional)

Trigger the workflow manually (Actions → Release → "Run workflow") to build and
publish to **TestPyPI** instead of PyPI. Because PyPI/TestPyPI filenames are
immutable, a repeat dry-run needs a **unique version** (bump the patch). A green
dry-run validates the build/smoke/OIDC *mechanics*, but TestPyPI uses a separate
trusted-publisher registration, so it does **not** prove the real-PyPI config — the
first live release does.
```

- [ ] **Step 2: Verify the section and its links are well-formed**

Run:
```bash
grep -n "^## Releasing" README.md && echo "section present"
grep -c "https://github.com/linsomniac/pygrit\|pypi.org/manage/account/publishing\|test.pypi.org" README.md
# Confirm the in-repo workflow link target actually exists:
test -f .github/workflows/release.yml && echo "workflow link target exists"
```
Expected: `## Releasing` found (`section present`); a non-zero count of the expected URLs; `workflow link target exists`.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document the trusted-publishing release procedure" \
  -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Manual prerequisites — HUMAN-ONLY (do NOT automate)

> **For the implementing agent:** This task **cannot** be performed by a subagent.
> Do **not** attempt to register publishers or create environments via API/CLI.
> Mark it as a hand-off item and surface it to the maintainer. It is listed here so
> the work is tracked and the exact values are recorded; the canonical copy now also
> lives in the README "Releasing → One-time setup" section (Task 4).

The maintainer must, before the first `pip install pygrit` can work, complete the
two steps documented in Task 4 / the README:

- [ ] **Register the PyPI pending publisher** — Project `pygrit`, Owner `linsomniac`,
  Repo `pygrit`, Workflow `release.yml`, Environment `pypi`
  (https://pypi.org/manage/account/publishing/).
- [ ] **(Optional, dry-run) Register the TestPyPI pending publisher** — same values,
  Environment `testpypi` (https://test.pypi.org/manage/account/publishing/).
- [ ] **Create + protect the `pypi` Environment** — restrict to protected `v*` tags
  (repository ruleset protecting `v*` tags).
- [ ] **Create + protect the `testpypi` Environment** — restrict to the `main` branch.

**Validation of the whole pipeline (maintainer, post-merge):** run the TestPyPI
dry-run via `workflow_dispatch` (needs the `testpypi` registration + environment).
A green run exercises build → smoke → collect → inventory → OIDC-publish mechanics.
The first live `vX.Y.Z` GitHub Release confirms the real-PyPI registration.

---

## Out of scope (carried from the spec — do NOT add)

- No write/mutation API; read-core only, binding code unchanged.
- No new wheel platforms beyond the 3 green targets (no Intel macOS, no Windows).
- No switch from `maturin-action` to cibuildwheel.
- No automated version bumping / release-please.
- No prerelease/PEP 440 versions in v1 (tags are `vX.Y.Z` final only).
- No changes to `ci.yml` or the existing `tests/` suite.

---

## Self-review (completed during plan authoring)

- **Spec coverage:** Deliverable 1 → Task 1 (Cargo.toml); Deliverable 2 → Task 1
  (pyproject.toml urls); Deliverable 3 (release.yml: triggers, least-privilege
  perms, concurrency, version-guard, 3-target build + abi3 + native/emulated smoke,
  dedicated sdist, two static-environment publish jobs with provenance + inventory
  gate, SHA-pinned publish action) → Tasks 2 (inventory checker) + 3 (workflow);
  Deliverable 4 (manual prereqs) → Task 5 + README (Task 4); Deliverable 5 (README
  "Releasing") → Task 4. Testing-strategy items (abi3/import smoke, version guard,
  provenance+inventory, TestPyPI dry-run) all map to Task 3 + Task 5.
- **Placeholder scan:** none — every step has concrete file content and exact
  commands with expected output.
- **Type consistency:** the workflow invokes `python3 .github/scripts/check_release_inventory.py dist`;
  the script's `main` takes the dir as `argv[1]` and the test imports `check_inventory`
  — names match across Tasks 2 and 3. The pinned publish-action SHA
  (`cef221092ed1bacb1cc03d23a2d87d1d172e277b`) is identical in both publish jobs and
  is re-confirmed in Task 3 Step 1.
```
