# pygrit Bindings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `pygrit`, native Python bindings to the `grit-lib` Rust crate, exposing a read-core Git API (open/discover, object read, refs, revwalk, diff, config) packaged as an abi3 wheel with maturin.

**Architecture:** A thin PyO3 binding layer (one Rust file per subsystem) wraps `grit-lib` and exposes a documented Python façade. No domain logic lives in the binding layer — it converts arguments, calls grit-lib, and converts results/errors. The Python package re-exports the native module `pygrit._pygrit`. Tests are differential ("oracle") tests against the real `git` CLI plus mirrored grit-lib unit tests.

**Tech Stack:** Rust (PyO3 `abi3-py311`, `grit-lib` exact-pinned), maturin (mixed Rust+Python layout), Python 3.11+, uv, pytest, mypy + stubtest, ruff, cargo fmt/clippy. Spec: `docs/superpowers/specs/2026-06-13-pygrit-bindings-design.md`.

---

## How to read this plan

The spec (§5) marks the Python API as **provisional pending the spike's API matrix** (Task 1.7). This plan resolves that tension as follows:

- **The pygrit Python API is the stable contract.** I define those names. Every test asserts against the Python surface and against real `git` output (the oracle). Those tests are concrete and do not change when grit-lib's internal signatures turn out different.
- **Each Rust implementation step that calls grit-lib carries a reconciliation instruction:** "Verify this call against the API matrix from Task 1.7; if grit-lib's real signature differs, adapt the *call*, not the test." This is not a placeholder — the verifiable contract (the test) is fully specified; only the internal call site may shift.
- **Phase 1 (the spike) is a hard gate.** Do not start Phase 2 until Tasks 1.1–1.9 are committed, including the API matrix and the exact version pin.

## Shared conventions (read once)

**Dev loop (TDD cycle for every binding task):**
1. Write the failing pytest against the pygrit Python API.
2. Build + install the extension into the dev venv: `uv run maturin develop --uv`
3. Run the test, confirm it fails for the expected reason (missing attribute / wrong value).
4. Implement the Rust binding.
5. `uv run maturin develop --uv` again.
6. Run the test, confirm it passes.
7. `cargo fmt`, `cargo clippy --all-targets -- -D warnings`, `ruff format`.
8. Commit.

**Run commands from the project root** `/home/sean/aix/pygrit`.

**Test runner:** `uv run pytest tests/ -v` (single test: `uv run pytest tests/test_x.py::test_y -v`).

**Never** weaken a test to make it pass. If a test reveals a grit-lib limitation, record it in the README compatibility note and mark the test `xfail` with a reason referencing the limitation — do not silently delete it.

**Commit message style:** Conventional Commits (`feat:`, `test:`, `docs:`, `build:`, `ci:`, `chore:`). End commit messages with the Co-Authored-By trailer this environment requires.

---

## File structure (target end state)

```
pygrit/
├── Cargo.toml                  # crate "pygrit": cdylib; pyo3 abi3-py311; grit-lib = pin
├── Cargo.lock                  # committed; all builds use --locked
├── pyproject.toml              # build-backend = maturin; PEP 621 metadata; requires-python >=3.11
├── rust-toolchain.toml         # pin toolchain channel for reproducibility
├── README.md                   # usage + pygrit↔grit-lib version-compat note
├── src/
│   ├── lib.rs                  # #[pymodule] _pygrit — registers classes + exceptions
│   ├── error.rs                # grit_lib::Error -> exception hierarchy (table-driven)
│   ├── repository.rs           # Repository: discover/open, refs, config, odb accessors
│   ├── odb.rs                  # Odb.read(oid) -> Object; exists(oid)
│   ├── objects.rs              # ObjectId, ObjectKind, Object, Commit, Tree, TreeEntry, Blob, Tag, Signature
│   ├── refs.rs                 # Reference + listing/resolution
│   ├── revwalk.rs              # revision walk / log iteration (owns traversal state)
│   └── diff.rs                 # tree/content diff -> Diff / DiffEntry
├── python/
│   └── pygrit/
│       ├── __init__.py         # re-exports _pygrit public symbols
│       ├── __init__.pyi        # hand-written type stubs
│       └── py.typed            # PEP 561 marker
├── tests/
│   ├── conftest.py             # hermetic git fixtures (isolated HOME, TZ=UTC, LC_ALL=C, deterministic dates)
│   ├── gitlib.py               # helpers: run git, build fixture repos, oracle queries
│   ├── test_smoke.py           # spike smoke test
│   ├── test_objectid.py        # mirrored grit-lib unit tests (oid round-trip etc.)
│   ├── test_objects.py         # object model oracle tests
│   ├── test_odb.py             # odb read/exists oracle tests
│   ├── test_refs.py            # references + resolve oracle tests
│   ├── test_revwalk.py         # revwalk oracle tests
│   ├── test_diff.py            # diff oracle tests
│   ├── test_config.py          # config oracle tests
│   ├── test_ffi_lifetime.py    # use-after-parent-drop safety tests
│   └── test_concurrency.py     # GIL-release / threaded read tests
├── docs/superpowers/
│   ├── specs/2026-06-13-pygrit-bindings-design.md
│   ├── plans/2026-06-13-pygrit-bindings.md   # this file
│   └── api-matrix.md           # Rust->Python API matrix (produced by the spike)
└── .github/workflows/ci.yml    # mandatory CI matrix
```

---

# Phase 1 — Build spike (de-risk first)

**This phase is a hard gate.** Its committed outputs (API matrix, exact version pin, feature flags, license, working wheel) are inputs to every later phase. Spec ref: §8.1.

### Task 1.1: Install maturin and confirm the toolchain

**Files:** none (environment)

- [ ] **Step 1: Confirm Rust + Python toolchain**

Run:
```bash
rustc --version && cargo --version && uv --version && git --version && python3 --version
```
Expected: `rustc 1.94.x`, `cargo 1.94.x`, `uv 0.11.x`, `git 2.53.x`, Python 3.x. (Spec §10.)

- [ ] **Step 2: Install maturin as a uv tool**

Run:
```bash
uv tool install maturin
uv tool run maturin --version
```
Expected: maturin prints a version (>= 1.7). If `uv tool run maturin` is awkward in the dev loop, maturin is also added as a dev dependency in Task 1.3 so `uv run maturin ...` works inside the project venv.

- [ ] **Step 3: Record toolchain versions**

Capture `maturin --version` and `pyo3` (to be pinned in 1.3) into a scratch note for the API-matrix doc. No commit yet.

### Task 1.2: Initialize the git-ignored build scaffolding

**Files:**
- Create: `.gitignore`
- Create: `rust-toolchain.toml`

- [ ] **Step 1: Write `.gitignore`**

```gitignore
/target
/.venv
__pycache__/
*.pyc
*.so
/dist
/build
.pytest_cache/
.mypy_cache/
.ruff_cache/
*.egg-info/
```

- [ ] **Step 2: Pin the Rust toolchain channel**

`rust-toolchain.toml`:
```toml
[toolchain]
channel = "1.94.1"
components = ["rustfmt", "clippy"]
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore rust-toolchain.toml
git commit -m "build: add gitignore and pin rust toolchain"
```

### Task 1.3: Scaffold the maturin mixed-layout crate

**Files:**
- Create: `pyproject.toml`
- Create: `Cargo.toml`
- Create: `src/lib.rs`
- Create: `python/pygrit/__init__.py`
- Create: `python/pygrit/py.typed`

- [ ] **Step 1: Discover the latest published grit-lib version, then pin it exactly**

Run:
```bash
cargo search grit-lib
```
Note the latest published version `X.Y.Z`. The spike pins this **exactly**; if read-core turns out unavailable in it, Task 1.8 records the Strategy-B fallback decision.

- [ ] **Step 2: Write `Cargo.toml`** (replace `=X.Y.Z` with the version from Step 1)

```toml
[package]
name = "pygrit"
version = "0.1.0"
edition = "2021"
license = "MIT"
publish = false

[lib]
name = "_pygrit"
crate-type = ["cdylib"]

[dependencies]
pyo3 = { version = "=0.23.3", features = ["abi3-py311", "extension-module"] }
grit-lib = "=X.Y.Z"
```
Reconciliation: if `cargo build` (Task 1.5) reports a newer pyo3 is required for the installed rustc, bump the exact pyo3 pin to the lowest version that builds and record it in the API matrix.

- [ ] **Step 3: Write `pyproject.toml`**

```toml
[build-system]
requires = ["maturin>=1.7,<2.0"]
build-backend = "maturin"

[project]
name = "pygrit"
description = "Python bindings for grit-lib (a Rust reimplementation of Git)"
readme = "README.md"
license = { text = "MIT" }
requires-python = ">=3.11"
classifiers = [
    "Programming Language :: Python :: 3 :: Only",
    "Programming Language :: Rust",
    "License :: OSI Approved :: MIT License",
    "Topic :: Software Development :: Version Control :: Git",
]
dynamic = ["version"]

[tool.maturin]
module-name = "pygrit._pygrit"
python-source = "python"
features = ["pyo3/extension-module"]

[dependency-groups]
dev = ["maturin>=1.7,<2.0", "pytest>=8", "mypy>=1.11", "ruff>=0.6"]
```

- [ ] **Step 4: Write a minimal `src/lib.rs`**

```rust
use pyo3::prelude::*;

/// Returns the pygrit version string. Smoke-test entry point for the spike.
#[pyfunction]
fn _hello() -> &'static str {
    "pygrit"
}

#[pymodule]
fn _pygrit(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(_hello, m)?)?;
    Ok(())
}
```
Reconciliation: PyO3 0.23 uses the `Bound` API. If the pinned pyo3 differs, adapt the `#[pymodule]` signature to that version's idiom.

- [ ] **Step 5: Write the Python re-export shim `python/pygrit/__init__.py`**

```python
"""pygrit — Python bindings for grit-lib."""

from pygrit._pygrit import _hello

__all__ = ["_hello"]
```

- [ ] **Step 6: Create the PEP 561 marker**

`python/pygrit/py.typed` — empty file.

- [ ] **Step 7: Create the dev venv and sync dev deps**

Run:
```bash
uv venv
uv sync --group dev
```
Expected: `.venv` created, dev tools installed.

- [ ] **Step 8: Commit** (Cargo.lock is generated in Task 1.5; not yet committed here)

```bash
git add pyproject.toml Cargo.toml src/lib.rs python/pygrit/__init__.py python/pygrit/py.typed
git commit -m "build: scaffold maturin mixed-layout crate"
```

### Task 1.4: Smoke-test the build end-to-end

**Files:**
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Write the smoke test**

```python
def test_native_module_imports():
    import pygrit

    assert pygrit._hello() == "pygrit"
```

- [ ] **Step 2: Build and install the extension**

Run:
```bash
uv run maturin develop --uv
```
Expected: compiles, installs `pygrit` into `.venv`.

- [ ] **Step 3: Run the smoke test**

Run: `uv run pytest tests/test_smoke.py -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_smoke.py
git commit -m "test: add native module import smoke test"
```

### Task 1.5: Pin Cargo.lock and verify a locked build

**Files:**
- Create: `Cargo.lock` (generated)

- [ ] **Step 1: Generate and lock**

Run:
```bash
cargo generate-lockfile
cargo build --locked
```
Expected: `Cargo.lock` exists; build succeeds with `--locked`.

- [ ] **Step 2: Record the resolved grit-lib version**

Run:
```bash
cargo tree -p grit-lib --depth 0
```
Confirm the resolved version equals the exact `=X.Y.Z` pin from Task 1.3. Note it for Task 1.7/1.8.

- [ ] **Step 3: Commit the lockfile**

```bash
git add Cargo.lock
git commit -m "build: commit Cargo.lock for reproducible builds"
```

### Task 1.6: Real read smoke — discover + read HEAD commit

This proves the actual grit-lib read path works before we design the surface. Spec §8.1.

**Files:**
- Modify: `src/lib.rs`
- Modify: `python/pygrit/__init__.py`
- Modify: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing test**

```python
import subprocess


def test_discover_and_read_head(tmp_path):
    import pygrit

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "a.txt").write_text("hello\n")
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"}
    subprocess.run(["git", "add", "a.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True,
                   env={**__import__("os").environ, **env})

    head_hex = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path,
                              check=True, capture_output=True, text=True).stdout.strip()

    repo = pygrit._discover_head_hex(str(tmp_path))
    assert repo == head_hex
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `uv run pytest tests/test_smoke.py::test_discover_and_read_head -v`
Expected: FAIL — `_discover_head_hex` does not exist.

- [ ] **Step 3: Implement the spike read in `src/lib.rs`**

Add a function that discovers the repo, resolves HEAD, and returns its hex. Use grit-lib's documented entry points (`Repository::discover` and HEAD resolution).

```rust
use pyo3::exceptions::PyRuntimeError;

/// Spike-only: discover a repo at `path` and return HEAD's commit id as hex.
#[pyfunction]
fn _discover_head_hex(path: &str) -> PyResult<String> {
    // Reconciliation: confirm these grit-lib calls against the API matrix (Task 1.7).
    // The documented surface is: Repository::discover(path) and a HEAD-resolution
    // path that yields an ObjectId with a hex/to_hex() representation.
    let repo = grit_lib::repo::Repository::discover(path)
        .map_err(|e| PyRuntimeError::new_err(format!("discover failed: {e}")))?;
    let oid = grit_lib::revision::resolve(&repo, "HEAD")
        .map_err(|e| PyRuntimeError::new_err(format!("resolve failed: {e}")))?;
    Ok(oid.to_hex().to_string())
}
```
Reconciliation: the exact module path for `resolve` and the `ObjectId` hex accessor are confirmed in Task 1.7. Adjust the two `grit_lib::...` call lines to match; the test assertion is the fixed contract.

- [ ] **Step 4: Register the function and re-export it**

In `src/lib.rs` `#[pymodule]`: `m.add_function(wrap_pyfunction!(_discover_head_hex, m)?)?;`
In `python/pygrit/__init__.py`: add `_discover_head_hex` to the import and `__all__`.

- [ ] **Step 5: Build, run, confirm pass**

Run:
```bash
uv run maturin develop --uv
uv run pytest tests/test_smoke.py -v
```
Expected: both smoke tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/lib.rs python/pygrit/__init__.py tests/test_smoke.py
git commit -m "feat: spike discover + read HEAD commit id"
```

### Task 1.7: Produce and commit the Rust→Python API matrix

This is the required spike artifact that reconciles §5 to grit-lib's real surface. Spec §5, §8.1.

**Files:**
- Create: `docs/superpowers/api-matrix.md`

- [ ] **Step 1: Inspect grit-lib's real API**

Run:
```bash
cargo doc -p grit-lib --no-deps
```
Open `target/doc/grit_lib/index.html` (or read the crate source under `~/.cargo/registry/src/`). For each pygrit operation in §5, record the **exact** grit-lib item: its module path, signature, return type, and error type.

- [ ] **Step 2: Write the matrix**

`docs/superpowers/api-matrix.md` — a table with columns: `pygrit symbol | grit-lib item (exact path + signature) | return type | error type | notes`. Cover at minimum: discover, open, git_dir/work_tree/is_bare, odb read/exists, ObjectId hex/raw/hash-algorithm, object kind, commit/tree/treeentry/blob/tag field access, signature fields, references listing, resolve, revwalk, diff, config get. Mark any §5 symbol with **no grit-lib equivalent** as "binding-layer constructed" or "deferred — not available".

- [ ] **Step 3: Record the hash-algorithm and SHA-256 capability**

In the matrix, note how grit-lib exposes the object hash algorithm (SHA-1 vs SHA-256) and whether SHA-256 repos are readable. Drives the §6/§11 SHA-256 tests.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/api-matrix.md
git commit -m "docs: add Rust->Python API matrix from spike"
```

### Task 1.8: Record features, license, and the version pin decision

**Files:**
- Modify: `docs/superpowers/api-matrix.md`
- Create: `README.md`

- [ ] **Step 1: Capture feature flags**

Run:
```bash
cargo tree -e features -p grit-lib
```
Append a "Feature flags" section to `api-matrix.md` listing grit-lib's actual features and which (if any) can be disabled. Do **not** assume a `transport`/`default` toggle exists (spec §8.1 item 2).

- [ ] **Step 2: Capture any `-sys`/pkg-config dependencies**

Run:
```bash
cargo tree -p grit-lib | grep -i -E 'sys|pkg' || echo "no -sys deps found"
```
Record whether `pkg-config`/system libs are required. If a `-sys` dep appears, note the install step (`pkg-config` + the C lib) as a build prerequisite.

- [ ] **Step 3: Confirm grit-lib's license**

Inspect the crate's `license` field (from `cargo metadata` or the registry source). Record it in `api-matrix.md`. If it is **not** MIT, stop and flag to the user before continuing — `pygrit`'s license must be compatible (spec §3, §11).

Run:
```bash
cargo metadata --format-version=1 --no-deps >/dev/null && \
cargo metadata --format-version=1 | python3 -c "import sys,json; d=json.load(sys.stdin); print([p['license'] for p in d['packages'] if p['name']=='grit-lib'])"
```

- [ ] **Step 4: Record the version-pin decision (Strategy A vs B)**

Append a decision note: confirm the exact `=X.Y.Z` crates.io pin exposes read-core (Strategy A holds). If it does **not**, record the Strategy-B git-revision fallback and its consequences (sdist needs network, weaker provenance, no PyPI sdist publish) per spec §3 — and stop to confirm with the user before adopting it.

- [ ] **Step 5: Write `README.md` with the compatibility note**

Include: what pygrit is, install/build instructions (`uv`, `maturin develop --uv`), supported Python (3.11+) and platforms (Linux/Unix; macOS best-effort; Windows deferred), and a **pygrit ↔ grit-lib version-compatibility** table seeded with this pin.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/api-matrix.md README.md
git commit -m "docs: record grit-lib features, license, pin decision; add README"
```

### Task 1.9: Verify the shipped artifact (wheel + sdist)

The spec requires testing the built artifact, not just `maturin develop`. Spec §7.

**Files:** none (verification)

- [ ] **Step 1: Build wheel and sdist with --locked**

Run:
```bash
uv run maturin build --release --locked
uv run maturin sdist
ls -la target/wheels/
```
Expected: a `*.whl` and a `*.tar.gz` are produced.

- [ ] **Step 2: Verify wheel ABI/platform tags**

Run:
```bash
ls target/wheels/ | grep -E 'abi3' && echo "abi3 tag present"
```
Expected: the wheel filename contains `abi3` and a Linux platform tag.

- [ ] **Step 3: Install the wheel into a clean throwaway venv and smoke it**

Run:
```bash
uv venv /tmp/pygrit-wheeltest
VIRTUAL_ENV=/tmp/pygrit-wheeltest uv pip install target/wheels/pygrit-*.whl
VIRTUAL_ENV=/tmp/pygrit-wheeltest uv run --no-project python -c "import pygrit; print(pygrit._hello())"
```
Expected: prints `pygrit`. Clean up `/tmp/pygrit-wheeltest` after.

- [ ] **Step 4: Record exit-criteria completion**

Confirm all §8.1 exit criteria are met and committed: (1) API matrix, (2) features, (3) platform/pkg-config scope, (4) exact version + Cargo.lock + license, plus a working wheel. No code change; this is the gate sign-off. If any item is unmet, do not proceed to Phase 2.

---

# Phase 2 — Object model + odb read

Spec §8.2. Builds the test harness, then `ObjectId`, `ObjectKind`, the exception hierarchy, `Odb.read/exists`, and the typed object views with the byte/text policy. **Prerequisite:** Phase 1 committed, API matrix in hand.

### Task 2.1: Hermetic git fixtures and oracle helpers

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/gitlib.py`

- [ ] **Step 1: Write `tests/gitlib.py` — git runner + oracle queries**

```python
"""Helpers to build hermetic git fixture repos and query git as an oracle."""
from __future__ import annotations

import subprocess
from pathlib import Path


def run_git(repo: Path, *args: str, env: dict[str, str] | None = None) -> bytes:
    """Run a git command in `repo`, returning raw stdout bytes."""
    result = subprocess.run(
        ["git", *args], cwd=repo, env=env, check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return result.stdout


def git_text(repo: Path, *args: str) -> str:
    return run_git(repo, *args).decode("utf-8", "surrogateescape").strip()


def rev_parse(repo: Path, spec: str) -> str:
    return git_text(repo, "rev-parse", spec)


def cat_file_data(repo: Path, oid: str) -> bytes:
    """Return the raw object payload via `git cat-file <type> <oid>` style batch read."""
    # `--batch` emits: "<oid> <type> <size>\n<payload>\n"
    proc = subprocess.run(
        ["git", "cat-file", "--batch"], cwd=repo, input=f"{oid}\n".encode(),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )
    out = proc.stdout
    header, _, rest = out.partition(b"\n")
    _oid, _type, size = header.split(b" ")
    return rest[: int(size)]


def cat_file_type(repo: Path, oid: str) -> str:
    return git_text(repo, "cat-file", "-t", oid)
```

- [ ] **Step 2: Write `tests/conftest.py` — isolation + a base fixture repo**

```python
"""Pytest fixtures: hermetic, deterministic git environment."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

DETERMINISTIC_DATE = "2005-04-07T22:13:13"


@pytest.fixture
def git_env(tmp_path: Path) -> dict[str, str]:
    """Isolated git environment: no user/system config, fixed identity, UTC, C locale."""
    home = tmp_path / "home"
    home.mkdir()
    return {
        "HOME": str(home),
        "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "TZ": "UTC",
        "LC_ALL": "C",
        "PATH": __import__("os").environ["PATH"],
        "GIT_AUTHOR_NAME": "Test Author",
        "GIT_AUTHOR_EMAIL": "author@example.com",
        "GIT_AUTHOR_DATE": DETERMINISTIC_DATE,
        "GIT_COMMITTER_NAME": "Test Committer",
        "GIT_COMMITTER_EMAIL": "committer@example.com",
        "GIT_COMMITTER_DATE": DETERMINISTIC_DATE,
    }


def _git(repo: Path, env: dict[str, str], *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, env=env, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


@pytest.fixture
def simple_repo(tmp_path: Path, git_env: dict[str, str]) -> Path:
    """A repo with one commit: a.txt='hello\\n', plus a dir/b.txt."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, git_env, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("hello\n")
    (repo / "dir").mkdir()
    (repo / "dir" / "b.txt").write_text("world\n")
    _git(repo, git_env, "add", "-A")
    _git(repo, git_env, "commit", "-q", "-m", "initial commit")
    return repo
```

- [ ] **Step 3: Confirm fixtures load**

Add a throwaway check and run it:
```bash
uv run pytest tests/ -q -k smoke
```
Expected: existing smoke tests still pass (fixtures import cleanly).

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py tests/gitlib.py
git commit -m "test: add hermetic git fixtures and oracle helpers"
```

### Task 2.2: Exception hierarchy

Spec §7. Mutually-exclusive subclasses with `GritError` as base/fallback.

**Files:**
- Create: `src/error.rs`
- Modify: `src/lib.rs`
- Create: `tests/test_errors.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest


def test_exception_hierarchy():
    import pygrit

    assert issubclass(pygrit.RepositoryError, pygrit.GritError)
    assert issubclass(pygrit.ObjectNotFoundError, pygrit.GritError)
    assert issubclass(pygrit.InvalidObjectError, pygrit.GritError)
    assert pygrit.GritError is not pygrit.RepositoryError
    # subclasses are mutually exclusive (no diamond except via GritError base)
    assert not issubclass(pygrit.ObjectNotFoundError, pygrit.RepositoryError)


def test_discover_missing_repo_raises_repository_error(tmp_path):
    import pygrit

    with pytest.raises(pygrit.RepositoryError):
        pygrit.Repository.discover(str(tmp_path))
```
(The second test will fully pass once Task 2.5 lands `Repository.discover`; after this task it should fail on a missing `Repository`, which is expected — keep it and let it go green in 2.5. To keep the cycle clean, mark it `@pytest.mark.xfail(reason="Repository lands in Task 2.5", strict=False)` now and remove the marker in Task 2.5.)

- [ ] **Step 2: Run it, confirm the hierarchy test fails**

Run: `uv run pytest tests/test_errors.py::test_exception_hierarchy -v`
Expected: FAIL — exceptions not defined.

- [ ] **Step 3: Implement `src/error.rs`**

```rust
use pyo3::prelude::*;
use pyo3::{create_exception, exceptions::PyException};

create_exception!(_pygrit, GritError, PyException, "Base class for all pygrit errors.");
create_exception!(_pygrit, RepositoryError, GritError, "Repository discover/open/config failure.");
create_exception!(_pygrit, ObjectNotFoundError, GritError, "A requested object or ref id does not exist.");
create_exception!(_pygrit, InvalidObjectError, GritError, "Malformed id or corrupt/undecodable object.");

/// Register the exception types on the module.
pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("GritError", m.py().get_type::<GritError>())?;
    m.add("RepositoryError", m.py().get_type::<RepositoryError>())?;
    m.add("ObjectNotFoundError", m.py().get_type::<ObjectNotFoundError>())?;
    m.add("InvalidObjectError", m.py().get_type::<InvalidObjectError>())?;
    Ok(())
}

/// Map a grit-lib error to the appropriate pygrit exception.
///
/// Reconciliation: replace the match arms with grit-lib's real error variants
/// from the API matrix (Task 1.7). Until those are confirmed, every error maps
/// to the GritError fallback, which is always reachable per spec §7.
pub fn map_err(py: Python<'_>, e: impl std::fmt::Display) -> PyErr {
    GritError::new_err(format!("{e}"))
}
```

- [ ] **Step 4: Wire `error.rs` into `src/lib.rs`**

Add `mod error;` and call `error::register(m)?;` inside `#[pymodule]`.

- [ ] **Step 5: Re-export in `python/pygrit/__init__.py`**

```python
from pygrit._pygrit import (
    GritError,
    RepositoryError,
    ObjectNotFoundError,
    InvalidObjectError,
)
```
Add all four to `__all__`.

- [ ] **Step 6: Build and confirm pass**

Run:
```bash
uv run maturin develop --uv
uv run pytest tests/test_errors.py::test_exception_hierarchy -v
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/error.rs src/lib.rs python/pygrit/__init__.py tests/test_errors.py
git commit -m "feat: add mutually-exclusive exception hierarchy"
```

### Task 2.3: `ObjectId` — hex/raw round-trip (mirrored unit test)

Spec §5, §7 (mirrored grit-lib units).

**Files:**
- Create: `src/objects.rs`
- Modify: `src/lib.rs`
- Modify: `python/pygrit/__init__.py`
- Create: `tests/test_objectid.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

HEX = "0123456789abcdef0123456789abcdef01234567"  # 40 hex chars = SHA-1


def test_objectid_from_hex_roundtrip():
    import pygrit

    oid = pygrit.ObjectId.from_hex(HEX)
    assert oid.hex == HEX
    assert oid.raw == bytes.fromhex(HEX)
    assert oid.hash_algorithm == "sha1"


def test_objectid_equality_and_hash():
    import pygrit

    a = pygrit.ObjectId.from_hex(HEX)
    b = pygrit.ObjectId.from_hex(HEX)
    assert a == b
    assert hash(a) == hash(b)
    assert {a, b} == {a}


def test_objectid_repr():
    import pygrit

    assert HEX in repr(pygrit.ObjectId.from_hex(HEX))


def test_objectid_invalid_hex_raises():
    import pygrit

    with pytest.raises((ValueError, pygrit.InvalidObjectError)):
        pygrit.ObjectId.from_hex("xyz")
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `uv run pytest tests/test_objectid.py -v`
Expected: FAIL — `ObjectId` not defined.

- [ ] **Step 3: Implement `ObjectId` in `src/objects.rs`**

```rust
use pyo3::prelude::*;
use pyo3::exceptions::PyValueError;
use pyo3::basic::CompareOp;
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

#[pyclass(frozen, module = "pygrit._pygrit")]
#[derive(Clone)]
pub struct ObjectId {
    raw: Vec<u8>,  // 20 bytes (SHA-1) or 32 bytes (SHA-256)
}

#[pymethods]
impl ObjectId {
    /// Construct from a hex string.
    #[staticmethod]
    fn from_hex(hex: &str) -> PyResult<Self> {
        // Reconciliation: prefer grit-lib's ObjectId::from_hex if it exists
        // (API matrix, Task 1.7). This local parse is a valid equivalent.
        let raw = (0..hex.len())
            .step_by(2)
            .map(|i| u8::from_str_radix(hex.get(i..i + 2)?, 16).ok())
            .collect::<Option<Vec<u8>>>()
            .ok_or_else(|| PyValueError::new_err("invalid hex object id"))?;
        if raw.len() != 20 && raw.len() != 32 {
            return Err(PyValueError::new_err("object id must be 20 or 32 bytes"));
        }
        Ok(Self { raw })
    }

    #[getter]
    fn hex(&self) -> String {
        self.raw.iter().map(|b| format!("{b:02x}")).collect()
    }

    #[getter]
    fn raw(&self) -> std::borrow::Cow<'_, [u8]> {
        std::borrow::Cow::Borrowed(&self.raw)
    }

    #[getter]
    fn hash_algorithm(&self) -> &'static str {
        if self.raw.len() == 32 { "sha256" } else { "sha1" }
    }

    fn __richcmp__(&self, other: &ObjectId, op: CompareOp) -> bool {
        match op {
            CompareOp::Eq => self.raw == other.raw,
            CompareOp::Ne => self.raw != other.raw,
            _ => false,
        }
    }

    fn __hash__(&self) -> u64 {
        let mut h = DefaultHasher::new();
        self.raw.hash(&mut h);
        h.finish()
    }

    fn __repr__(&self) -> String {
        format!("ObjectId('{}')", self.hex())
    }
}

impl ObjectId {
    pub fn from_raw(raw: Vec<u8>) -> Self {
        Self { raw }
    }
    pub fn raw_bytes(&self) -> &[u8] {
        &self.raw
    }
}
```
Note: `__richcmp__` returning `false` for unsupported ops is acceptable for an id type; equality/hash are what the tests require.

- [ ] **Step 4: Register and re-export**

In `src/lib.rs`: `mod objects;` and `m.add_class::<objects::ObjectId>()?;`
In `python/pygrit/__init__.py`: import `ObjectId`, add to `__all__`.

- [ ] **Step 5: Build and confirm pass**

Run:
```bash
uv run maturin develop --uv
uv run pytest tests/test_objectid.py -v
```
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/objects.rs src/lib.rs python/pygrit/__init__.py tests/test_objectid.py
git commit -m "feat: add ObjectId with hex/raw round-trip and equality"
```

### Task 2.4: `ObjectKind` enum

**Files:**
- Modify: `src/objects.rs`
- Modify: `src/lib.rs`
- Modify: `python/pygrit/__init__.py`
- Create: `tests/test_objectkind.py`

- [ ] **Step 1: Write the failing test**

```python
def test_objectkind_members():
    import pygrit

    assert {k.name for k in pygrit.ObjectKind} >= {"COMMIT", "TREE", "BLOB", "TAG"}


def test_objectkind_distinct():
    import pygrit

    assert pygrit.ObjectKind.COMMIT != pygrit.ObjectKind.TREE
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `uv run pytest tests/test_objectkind.py -v`
Expected: FAIL — `ObjectKind` not defined.

- [ ] **Step 3: Implement the enum in `src/objects.rs`**

```rust
#[pyclass(eq, eq_int, module = "pygrit._pygrit")]
#[derive(Clone, PartialEq)]
pub enum ObjectKind {
    COMMIT,
    TREE,
    BLOB,
    TAG,
}

#[pymethods]
impl ObjectKind {
    fn __repr__(&self) -> &'static str {
        match self {
            ObjectKind::COMMIT => "ObjectKind.COMMIT",
            ObjectKind::TREE => "ObjectKind.TREE",
            ObjectKind::BLOB => "ObjectKind.BLOB",
            ObjectKind::TAG => "ObjectKind.TAG",
        }
    }
}
```
Reconciliation: map to/from grit-lib's own `ObjectKind` (API matrix) in the conversion helper used by `Odb.read` (Task 2.6).

- [ ] **Step 4: Register and re-export**

In `src/lib.rs`: `m.add_class::<objects::ObjectKind>()?;`
In `python/pygrit/__init__.py`: import `ObjectKind`, add to `__all__`.

- [ ] **Step 5: Build and confirm pass**

Run:
```bash
uv run maturin develop --uv
uv run pytest tests/test_objectkind.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/objects.rs src/lib.rs python/pygrit/__init__.py tests/test_objectkind.py
git commit -m "feat: add ObjectKind enum"
```

### Task 2.5: `Repository.discover` / `open` and path properties

Spec §5. Replaces the spike's `_discover_head_hex` with the real handle. FFI ownership per §6 (Arc-wrapped).

**Files:**
- Create: `src/repository.rs`
- Modify: `src/lib.rs`
- Modify: `python/pygrit/__init__.py`
- Create: `tests/test_repository.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from tests.gitlib import git_text


def test_discover_returns_repository(simple_repo):
    import pygrit

    repo = pygrit.Repository.discover(str(simple_repo))
    assert repo.git_dir == bytes(simple_repo / ".git")
    assert repo.work_tree == bytes(simple_repo)
    assert repo.is_bare is False


def test_discover_missing_repo_raises(tmp_path):
    import pygrit

    with pytest.raises(pygrit.RepositoryError):
        pygrit.Repository.discover(str(tmp_path))


def test_open_explicit_dirs(simple_repo):
    import pygrit

    repo = pygrit.Repository.open(str(simple_repo / ".git"), str(simple_repo))
    assert repo.is_bare is False
```
Note: `bytes(Path)` requires `os.fsencode`; replace with `__import__("os").fsencode(simple_repo / ".git")` if `bytes(Path)` is unavailable. Use `os.fsencode` for clarity:
```python
import os
assert repo.git_dir == os.fsencode(simple_repo / ".git")
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `uv run pytest tests/test_repository.py -v`
Expected: FAIL — `Repository` not defined.

- [ ] **Step 3: Implement `src/repository.rs`**

```rust
use pyo3::prelude::*;
use pyo3::types::PyBytes;
use std::path::PathBuf;
use std::sync::Arc;

use crate::error::{map_err, RepositoryError};

#[pyclass(module = "pygrit._pygrit")]
pub struct Repository {
    pub(crate) inner: Arc<grit_lib::repo::Repository>,
}

#[pymethods]
impl Repository {
    /// Walk upward from `path` to find a repository.
    #[staticmethod]
    fn discover(py: Python<'_>, path: PathBuf) -> PyResult<Self> {
        // Reconciliation: confirm Repository::discover signature (API matrix).
        let repo = py
            .allow_threads(|| grit_lib::repo::Repository::discover(&path))
            .map_err(|e| RepositoryError::new_err(format!("{e}")))?;
        Ok(Self { inner: Arc::new(repo) })
    }

    /// Open a repository from explicit git_dir and optional work_tree.
    #[staticmethod]
    #[pyo3(signature = (git_dir, work_tree=None))]
    fn open(py: Python<'_>, git_dir: PathBuf, work_tree: Option<PathBuf>) -> PyResult<Self> {
        // Reconciliation: confirm Repository::open(git_dir, work_tree) signature.
        let repo = py
            .allow_threads(|| grit_lib::repo::Repository::open(&git_dir, work_tree.as_deref()))
            .map_err(|e| RepositoryError::new_err(format!("{e}")))?;
        Ok(Self { inner: Arc::new(repo) })
    }

    #[getter]
    fn git_dir<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        // Reconciliation: real accessor name for the git dir path (API matrix).
        let p = self.inner.git_dir();
        PyBytes::new(py, p.as_os_str().as_encoded_bytes())
    }

    #[getter]
    fn work_tree<'py>(&self, py: Python<'py>) -> Option<Bound<'py, PyBytes>> {
        self.inner
            .work_tree()
            .map(|p| PyBytes::new(py, p.as_os_str().as_encoded_bytes()))
    }

    #[getter]
    fn is_bare(&self) -> bool {
        self.inner.is_bare()
    }
}
```
Reconciliation: `git_dir()`, `work_tree()`, `is_bare()` accessor names and the `open` work_tree argument type come from the API matrix. `OsStr::as_encoded_bytes` preserves surrogate-escaped path bytes per the §5 byte policy.

- [ ] **Step 4: Register and re-export**

In `src/lib.rs`: `mod repository;` and `m.add_class::<repository::Repository>()?;`. Remove the spike `_discover_head_hex` function and its registration; drop it from `python/pygrit/__init__.py` and from `tests/test_smoke.py` (keep `test_native_module_imports`).
In `python/pygrit/__init__.py`: import `Repository`, add to `__all__`.

- [ ] **Step 5: Build and confirm pass; un-xfail the 2.2 test**

Remove the `xfail` marker added in Task 2.2 `test_discover_missing_repo_raises_repository_error`.
Run:
```bash
uv run maturin develop --uv
uv run pytest tests/test_repository.py tests/test_errors.py -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/repository.rs src/lib.rs python/pygrit/__init__.py tests/test_repository.py tests/test_errors.py tests/test_smoke.py
git commit -m "feat: add Repository.discover/open with path properties"
```

### Task 2.6: `Odb.read` / `exists` returning a raw `Object`

Spec §5, §8.2. Object carries `.id`, `.kind`, `.data` (owned bytes). Oracle: `git cat-file`.

**Files:**
- Create: `src/odb.rs`
- Modify: `src/objects.rs` (add `Object`)
- Modify: `src/repository.rs` (add `.odb` accessor)
- Modify: `src/lib.rs`, `python/pygrit/__init__.py`
- Create: `tests/test_odb.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from tests.gitlib import cat_file_data, cat_file_type, rev_parse


def test_odb_read_blob_matches_git(simple_repo):
    import pygrit

    blob_oid = rev_parse(simple_repo, "HEAD:a.txt")
    repo = pygrit.Repository.discover(str(simple_repo))
    obj = repo.odb.read(pygrit.ObjectId.from_hex(blob_oid))

    assert obj.id.hex == blob_oid
    assert obj.kind == pygrit.ObjectKind.BLOB
    assert obj.data == cat_file_data(simple_repo, blob_oid)


def test_odb_read_commit_matches_git(simple_repo):
    import pygrit

    commit_oid = rev_parse(simple_repo, "HEAD")
    repo = pygrit.Repository.discover(str(simple_repo))
    obj = repo.odb.read(pygrit.ObjectId.from_hex(commit_oid))

    assert obj.kind == pygrit.ObjectKind.COMMIT
    assert obj.data == cat_file_data(simple_repo, commit_oid)


def test_odb_exists(simple_repo):
    import pygrit

    commit_oid = rev_parse(simple_repo, "HEAD")
    repo = pygrit.Repository.discover(str(simple_repo))
    assert repo.odb.exists(pygrit.ObjectId.from_hex(commit_oid)) is True


def test_odb_read_missing_raises(simple_repo):
    import pygrit

    repo = pygrit.Repository.discover(str(simple_repo))
    missing = pygrit.ObjectId.from_hex("0" * 40)
    with pytest.raises(pygrit.ObjectNotFoundError):
        repo.odb.read(missing)
```

- [ ] **Step 2: Run it, confirm it fails**

Run: `uv run pytest tests/test_odb.py -v`
Expected: FAIL — `repo.odb` / `Object` not defined.

- [ ] **Step 3: Add `Object` to `src/objects.rs`**

```rust
use pyo3::types::PyBytes;

#[pyclass(frozen, module = "pygrit._pygrit")]
pub struct Object {
    pub(crate) id: ObjectId,
    pub(crate) kind: ObjectKind,
    pub(crate) data: Arc<[u8]>,  // owned payload, shared with typed views
}

#[pymethods]
impl Object {
    #[getter]
    fn id(&self) -> ObjectId {
        self.id.clone()
    }
    #[getter]
    fn kind(&self) -> ObjectKind {
        self.kind.clone()
    }
    #[getter]
    fn data<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.data)
    }
}
```
Add `use std::sync::Arc;` at the top of `objects.rs` if not present.

- [ ] **Step 4: Implement `src/odb.rs`**

```rust
use pyo3::prelude::*;
use std::sync::Arc;

use crate::error::{ObjectNotFoundError, map_err};
use crate::objects::{Object, ObjectId, ObjectKind};

#[pyclass(module = "pygrit._pygrit")]
pub struct Odb {
    pub(crate) repo: Arc<grit_lib::repo::Repository>,
}

#[pymethods]
impl Odb {
    /// Read an object by id, returning its raw kind + data.
    fn read(&self, py: Python<'_>, oid: &ObjectId) -> PyResult<Object> {
        let raw = oid.raw_bytes().to_vec();
        // Reconciliation: confirm odb access + read signature and the returned
        // (kind, data) shape (API matrix). Map "not found" to ObjectNotFoundError.
        let (kind, data) = py
            .allow_threads(|| {
                let id = grit_lib::ObjectId::from_bytes(&raw)?;
                let obj = self.repo.odb().read(&id)?;
                Ok::<_, grit_lib::Error>((obj.kind(), obj.data().to_vec()))
            })
            .map_err(|e| ObjectNotFoundError::new_err(format!("{e}")))?;
        Ok(Object {
            id: oid.clone(),
            kind: map_kind(kind),
            data: Arc::from(data.into_boxed_slice()),
        })
    }

    /// True if an object with `oid` exists in the odb.
    fn exists(&self, py: Python<'_>, oid: &ObjectId) -> PyResult<bool> {
        let raw = oid.raw_bytes().to_vec();
        Ok(py.allow_threads(|| {
            grit_lib::ObjectId::from_bytes(&raw)
                .ok()
                .map(|id| self.repo.odb().exists(&id))
                .unwrap_or(false)
        }))
    }
}

/// Map grit-lib's object kind to pygrit's ObjectKind.
/// Reconciliation: match arms come from grit-lib's real ObjectKind (API matrix).
fn map_kind(_k: /* grit_lib::ObjectKind */ ()) -> ObjectKind {
    // Placeholder shape only; replace `()` with grit_lib::ObjectKind and match
    // its variants to ObjectKind::{COMMIT,TREE,BLOB,TAG} once confirmed.
    ObjectKind::BLOB
}
```
Reconciliation note: the `map_kind` body and the `obj.kind()/obj.data()` calls are the spike-confirmed seams. The **test** (kind + byte-exact data vs `git cat-file`) is the fixed contract; adjust these call sites until the test passes against real grit-lib. Distinguishing "not found" from "corrupt" uses grit-lib's error variants (Task 2.2 `map_err` table) — corrupt objects map to `InvalidObjectError`.

- [ ] **Step 5: Add the `.odb` accessor to `Repository`**

In `src/repository.rs` `#[pymethods]`:
```rust
    #[getter]
    fn odb(&self) -> crate::odb::Odb {
        crate::odb::Odb { repo: Arc::clone(&self.inner) }
    }
```

- [ ] **Step 6: Register and re-export**

In `src/lib.rs`: `mod odb;`, `m.add_class::<odb::Odb>()?;`, `m.add_class::<objects::Object>()?;`
In `python/pygrit/__init__.py`: import `Odb`, `Object`; add to `__all__`.

- [ ] **Step 7: Build and confirm pass**

Run:
```bash
uv run maturin develop --uv
uv run pytest tests/test_odb.py -v
```
Expected: PASS. If `test_odb_read_missing_raises` fails because grit-lib signals missing differently, adjust the error mapping in `map_err`/`read`, not the test.

- [ ] **Step 8: Commit**

```bash
git add src/odb.rs src/objects.rs src/repository.rs src/lib.rs python/pygrit/__init__.py tests/test_odb.py
git commit -m "feat: add Odb.read/exists returning raw Object"
```

### Task 2.7: Typed views — `Commit` (with byte/text policy)

Spec §5 byte/text policy. Parse the raw commit in the binding layer (the matrix may show grit-lib offers a parsed view; prefer it if so).

**Files:**
- Modify: `src/objects.rs` (add `Commit`, `Signature`)
- Modify: `src/repository.rs` or `src/odb.rs` (a way to obtain a typed view)
- Modify: `tests/test_objects.py` (create)

- [ ] **Step 1: Write the failing test**

```python
from tests.gitlib import git_text, rev_parse


def test_commit_fields_match_git(simple_repo):
    import pygrit

    oid = rev_parse(simple_repo, "HEAD")
    repo = pygrit.Repository.discover(str(simple_repo))
    commit = repo.commit(pygrit.ObjectId.from_hex(oid))

    tree_oid = rev_parse(simple_repo, "HEAD^{tree}")
    assert commit.tree.hex == tree_oid
    assert commit.parents == []  # first commit
    assert commit.message_bytes == b"initial commit\n"
    assert commit.message() == "initial commit\n"
    assert commit.author.name == b"Test Author"
    assert commit.author.email == b"author@example.com"
    assert commit.committer.name == b"Test Committer"


def test_commit_message_encoding_override(simple_repo):
    import pygrit

    oid = rev_parse(simple_repo, "HEAD")
    repo = pygrit.Repository.discover(str(simple_repo))
    commit = repo.commit(pygrit.ObjectId.from_hex(oid))
    # default utf-8/strict; explicit override is accepted
    assert commit.message(encoding="utf-8", errors="strict") == "initial commit\n"
```
Note on the message: git stores the commit message body; `git log -1 --format=%B` is the oracle. Replace the literal `b"initial commit\n"` with the oracle if trailing-newline handling differs:
```python
expected = git_text(simple_repo, "log", "-1", "--format=%B").encode() + b"\n"
```
Decide the exact trailing-newline contract when you see grit-lib's raw payload; keep the oracle, not the literal, as the source of truth.

- [ ] **Step 2: Run it, confirm it fails**

Run: `uv run pytest tests/test_objects.py -v`
Expected: FAIL — `repo.commit` / `Commit` not defined.

- [ ] **Step 3: Add `Signature` and `Commit` to `src/objects.rs`**

```rust
#[pyclass(frozen, module = "pygrit._pygrit")]
pub struct Signature {
    name: Vec<u8>,
    email: Vec<u8>,
    when_secs: i64,
    when_offset_minutes: i32,
}

#[pymethods]
impl Signature {
    #[getter]
    fn name<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.name)
    }
    #[getter]
    fn email<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.email)
    }
    /// (unix_seconds, utc_offset_minutes)
    #[getter]
    fn when(&self) -> (i64, i32) {
        (self.when_secs, self.when_offset_minutes)
    }
    #[getter]
    fn name_str(&self) -> PyResult<String> {
        Ok(String::from_utf8_lossy(&self.name).into_owned())
    }
    #[getter]
    fn email_str(&self) -> PyResult<String> {
        Ok(String::from_utf8_lossy(&self.email).into_owned())
    }
}

#[pyclass(frozen, module = "pygrit._pygrit")]
pub struct Commit {
    tree: ObjectId,
    parents: Vec<ObjectId>,
    author: Py<Signature>,
    committer: Py<Signature>,
    message: Vec<u8>,
}

#[pymethods]
impl Commit {
    #[getter]
    fn tree(&self) -> ObjectId {
        self.tree.clone()
    }
    #[getter]
    fn parents(&self) -> Vec<ObjectId> {
        self.parents.clone()
    }
    #[getter]
    fn author(&self, py: Python<'_>) -> Py<Signature> {
        self.author.clone_ref(py)
    }
    #[getter]
    fn committer(&self, py: Python<'_>) -> Py<Signature> {
        self.committer.clone_ref(py)
    }
    #[getter]
    fn message_bytes<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.message)
    }
    #[pyo3(signature = (encoding="utf-8", errors="strict"))]
    fn message(&self, encoding: &str, errors: &str) -> PyResult<String> {
        decode_bytes(&self.message, encoding, errors)
    }
}
```
Add a `decode_bytes(data, encoding, errors)` helper that uses Python's codec via `PyBytes::decode` semantics (call into Python's `bytes.decode` for full codec/errors support):
```rust
fn decode_bytes(data: &[u8], encoding: &str, errors: &str) -> PyResult<String> {
    Python::with_gil(|py| {
        let b = PyBytes::new(py, data);
        let s = b.call_method1("decode", (encoding, errors))?;
        s.extract::<String>()
    })
}
```

- [ ] **Step 4: Add a `commit(oid)` accessor on `Repository`**

In `src/repository.rs`, add a method that reads the object via odb and constructs the typed `Commit`. Reconciliation: if grit-lib exposes a parsed commit view, build `Commit` from it; otherwise parse the raw commit payload (the `tree`/`parent`/`author`/`committer` headers then a blank line then the message) in the binding layer.

```rust
    fn commit(&self, py: Python<'_>, oid: &crate::objects::ObjectId) -> PyResult<crate::objects::Commit> {
        crate::objects::Commit::from_repo(py, &self.inner, oid)
    }
```
Implement `Commit::from_repo` in `objects.rs` to read the raw commit and parse it (or use grit-lib's parsed view). Map parse failure to `InvalidObjectError`.

- [ ] **Step 5: Register and re-export**

`m.add_class::<objects::Commit>()?;`, `m.add_class::<objects::Signature>()?;` in `lib.rs`; import both in `__init__.py` + `__all__`.

- [ ] **Step 6: Build and confirm pass**

Run:
```bash
uv run maturin develop --uv
uv run pytest tests/test_objects.py -v
```
Expected: PASS. Resolve the trailing-newline contract against the oracle here.

- [ ] **Step 7: Commit**

```bash
git add src/objects.rs src/repository.rs src/lib.rs python/pygrit/__init__.py tests/test_objects.py
git commit -m "feat: add Commit + Signature typed views with byte/text policy"
```

### Task 2.8: Typed views — `Tree`, `TreeEntry`, `Blob`, `Tag`

Spec §5. Oracle: `git ls-tree -z`, `git cat-file`, `git cat-file -p` for tags.

**Files:**
- Modify: `src/objects.rs`
- Modify: `src/repository.rs`
- Modify: `tests/test_objects.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_tree_entries_match_git(simple_repo):
    import pygrit
    from tests.gitlib import rev_parse, run_git

    tree_oid = rev_parse(simple_repo, "HEAD^{tree}")
    repo = pygrit.Repository.discover(str(simple_repo))
    tree = repo.tree(pygrit.ObjectId.from_hex(tree_oid))

    # git ls-tree -z: "<mode> <type> <oid>\t<name>\0"
    raw = run_git(simple_repo, "ls-tree", "-z", tree_oid)
    expected_names = {rec.split(b"\t", 1)[1] for rec in raw.split(b"\0") if rec}
    assert {e.name for e in tree} == expected_names

    a = next(e for e in tree if e.name == b"a.txt")
    assert a.mode == 0o100644
    assert a.kind == pygrit.ObjectKind.BLOB
    assert a.id.hex == rev_parse(simple_repo, "HEAD:a.txt")


def test_blob_data_matches_git(simple_repo):
    import pygrit
    from tests.gitlib import cat_file_data, rev_parse

    blob_oid = rev_parse(simple_repo, "HEAD:a.txt")
    repo = pygrit.Repository.discover(str(simple_repo))
    blob = repo.blob(pygrit.ObjectId.from_hex(blob_oid))
    assert blob.data == cat_file_data(simple_repo, blob_oid)


def test_tag_fields_match_git(tmp_path, git_env):
    import pygrit
    import subprocess
    from tests.gitlib import rev_parse

    repo = tmp_path / "tagrepo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, env=git_env, check=True)
    (repo / "f").write_text("x\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, env=git_env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "c"], cwd=repo, env=git_env, check=True)
    subprocess.run(["git", "tag", "-a", "v1", "-m", "release one"], cwd=repo, env=git_env, check=True)

    tag_oid = rev_parse(repo, "v1")  # annotated tag object
    pyrepo = pygrit.Repository.discover(str(repo))
    tag = pyrepo.tag(pygrit.ObjectId.from_hex(tag_oid))
    assert tag.name == b"v1"
    assert tag.message_bytes == b"release one\n"
    assert tag.target.hex == rev_parse(repo, "v1^{commit}")
```

- [ ] **Step 2: Run, confirm fail**

Run: `uv run pytest tests/test_objects.py -v -k "tree or blob or tag"`
Expected: FAIL — `repo.tree/blob/tag` not defined.

- [ ] **Step 3: Implement `Tree`, `TreeEntry`, `Blob`, `Tag`**

Add to `src/objects.rs`:
- `TreeEntry` (frozen pyclass): `name -> bytes`, `mode -> int`, `id -> ObjectId`, `kind -> ObjectKind`.
- `Tree` (pyclass): holds `Vec<TreeEntry>`; implement `__iter__`/`__len__` by returning an owning iterator (a `TreeIter` pyclass holding the `Vec` and a cursor — owns its state per §6).
- `Blob` (frozen): `data -> bytes` (Arc-shared).
- `Tag` (frozen): `target -> ObjectId`, `name -> bytes`, `tagger -> Optional<Signature>`, `message_bytes -> bytes`.

Reconciliation: build each from grit-lib's parsed view if available; otherwise parse the raw payload (tree entries: `<mode> <name>\0<20-or-32 raw oid bytes>` repeated; tag: header lines + blank + message). Mode `100644`→blob, `40000`→tree, etc.; map entry kind accordingly.

- [ ] **Step 4: Add `tree(oid)`, `blob(oid)`, `tag(oid)` accessors on `Repository`** (same pattern as `commit`).

- [ ] **Step 5: Register and re-export** all four classes; import in `__init__.py` + `__all__`.

- [ ] **Step 6: Build and confirm pass**

Run:
```bash
uv run maturin develop --uv
uv run pytest tests/test_objects.py -v
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/objects.rs src/repository.rs src/lib.rs python/pygrit/__init__.py tests/test_objects.py
git commit -m "feat: add Tree/TreeEntry/Blob/Tag typed views"
```

### Task 2.9: FFI lifetime safety test (child outlives parent)

Spec §6.

**Files:**
- Create: `tests/test_ffi_lifetime.py`

- [ ] **Step 1: Write the test**

```python
import gc

from tests.gitlib import rev_parse


def test_odb_outlives_repository(simple_repo):
    import pygrit

    oid = rev_parse(simple_repo, "HEAD:a.txt")
    repo = pygrit.Repository.discover(str(simple_repo))
    odb = repo.odb
    del repo
    gc.collect()
    # Arc keeps the underlying repo alive; this must not crash or raise.
    obj = odb.read(pygrit.ObjectId.from_hex(oid))
    assert obj.id.hex == oid


def test_tree_iter_outlives_tree(simple_repo):
    import pygrit

    tree_oid = rev_parse(simple_repo, "HEAD^{tree}")
    repo = pygrit.Repository.discover(str(simple_repo))
    tree = repo.tree(pygrit.ObjectId.from_hex(tree_oid))
    it = iter(tree)
    del tree
    gc.collect()
    names = {e.name for e in it}
    assert b"a.txt" in names
```

- [ ] **Step 2: Run and confirm pass**

Run: `uv run maturin develop --uv && uv run pytest tests/test_ffi_lifetime.py -v`
Expected: PASS (Arc + owning iterators). If it crashes, the ownership model is wrong — fix the binding (do not delete the test).

- [ ] **Step 3: Commit**

```bash
git add tests/test_ffi_lifetime.py
git commit -m "test: verify children outlive parent Repository (FFI safety)"
```

---

# Phase 3 — References + resolve

Spec §8.3. Oracle: `git for-each-ref -z`, `git symbolic-ref`, `git rev-parse`.

### Task 3.1: `references()` iterator

**Files:**
- Create: `src/refs.rs`
- Modify: `src/repository.rs`, `src/lib.rs`, `python/pygrit/__init__.py`
- Create: `tests/test_refs.py`

- [ ] **Step 1: Write the failing test**

```python
from tests.gitlib import run_git, rev_parse


def test_references_match_git(simple_repo):
    import pygrit

    # for-each-ref -z: records "<oid> <type> <refname>\0" with --format
    raw = run_git(simple_repo, "for-each-ref", "-z",
                  "--format=%(objectname) %(refname)")
    expected = {}
    for rec in raw.split(b"\0"):
        if not rec:
            continue
        oid, name = rec.split(b" ", 1)
        expected[name] = oid.decode()

    repo = pygrit.Repository.discover(str(simple_repo))
    got = {r.name: r.target.hex for r in repo.references() if r.target is not None}
    assert got == expected
```

- [ ] **Step 2: Run, confirm fail.** `uv run pytest tests/test_refs.py -v` → FAIL (`references` undefined).

- [ ] **Step 3: Implement `Reference` + an owning iterator in `src/refs.rs`**

`Reference` (frozen pyclass): `name -> bytes`, `target -> Optional<ObjectId>`, `symbolic_target -> Optional<bytes>`, `is_symbolic -> bool`, `peel() -> ObjectId`.
`ReferenceIter` (pyclass): owns a `Vec<Reference>` (or grit-lib's ref iterator collected into owned state) + cursor; `__iter__`/`__next__`.
Reconciliation: ref listing function from the API matrix (likely `grit_lib::references::...`).

- [ ] **Step 4: Add `references()` on `Repository`** returning `ReferenceIter`.

- [ ] **Step 5: Register + re-export** `Reference`; build; confirm pass.

```bash
uv run maturin develop --uv && uv run pytest tests/test_refs.py -v
```

- [ ] **Step 6: Commit.** `git commit -m "feat: add references() iterator"`

### Task 3.2: Symbolic refs (HEAD)

**Files:** Modify `src/refs.rs`, `tests/test_refs.py`

- [ ] **Step 1: Write the failing test**

```python
def test_head_symbolic(simple_repo):
    import pygrit
    from tests.gitlib import git_text

    branch = git_text(simple_repo, "symbolic-ref", "HEAD")  # e.g. refs/heads/main
    repo = pygrit.Repository.discover(str(simple_repo))
    head = next(r for r in repo.references() if r.name == b"HEAD")
    assert head.is_symbolic is True
    assert head.symbolic_target == branch.encode()
    assert head.peel().hex == git_text(simple_repo, "rev-parse", "HEAD")
```
Note: if grit-lib's ref iterator does not include `HEAD`, add a `repo.head()` accessor instead and adjust the test to call it (record the choice in the API matrix notes).

- [ ] **Step 2: Run, confirm fail; implement symbolic-ref fields + `peel()`; build; confirm pass.**

- [ ] **Step 3: Commit.** `git commit -m "feat: handle symbolic refs and peel()"`

### Task 3.3: `resolve(spec)`

**Files:** Modify `src/repository.rs`, `tests/test_refs.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest


def test_resolve_matches_rev_parse(simple_repo):
    import pygrit
    from tests.gitlib import rev_parse

    repo = pygrit.Repository.discover(str(simple_repo))
    for spec in ["HEAD", "HEAD^{tree}", "HEAD:a.txt"]:
        assert repo.resolve(spec).hex == rev_parse(simple_repo, spec)


def test_resolve_unknown_raises(simple_repo):
    import pygrit

    repo = pygrit.Repository.discover(str(simple_repo))
    with pytest.raises(pygrit.ObjectNotFoundError):
        repo.resolve("no-such-ref")
```

- [ ] **Step 2: Run, confirm fail; implement `resolve` using the matrix's revision function (`grit_lib::revision::resolve` per the spike). Build; confirm pass.**

If grit-lib resolves a narrower spec grammar than git (e.g. no `:path`), record the gap in the README compatibility note and `xfail` only the unsupported spec cases with that reason — keep `HEAD` working.

- [ ] **Step 3: Commit.** `git commit -m "feat: add resolve(spec) -> ObjectId"`

---

# Phase 4 — Revwalk / log

Spec §8.4. Owned traversal state (§6). Oracle: `git rev-list`.

### Task 4.1: `revwalk(start)` default order

**Files:** Create `src/revwalk.rs`; modify `src/repository.rs`, `src/lib.rs`, `python/pygrit/__init__.py`; create `tests/test_revwalk.py`

- [ ] **Step 1: Build a multi-commit fixture + write the failing test**

```python
import subprocess

import pytest


@pytest.fixture
def linear_repo(tmp_path, git_env):
    repo = tmp_path / "lin"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, env=git_env, check=True)
    for i in range(4):
        (repo / "f").write_text(f"{i}\n")
        subprocess.run(["git", "add", "-A"], cwd=repo, env=git_env, check=True)
        subprocess.run(["git", "commit", "-q", "-m", f"c{i}"], cwd=repo, env=git_env, check=True)
    return repo


def test_revwalk_matches_rev_list(linear_repo):
    import pygrit
    from tests.gitlib import git_text

    expected = git_text(linear_repo, "rev-list", "HEAD").split("\n")
    repo = pygrit.Repository.discover(str(linear_repo))
    head = repo.resolve("HEAD")
    got = [c.hex if hasattr(c, "hex") else c.id.hex for c in repo.revwalk(head)]
    assert got == expected
```
Decide whether `revwalk` yields `ObjectId` or `Commit` based on the API matrix; the test acccommodates both, but **fix the contract in the stub** (Task 6.x) once chosen. Prefer yielding `Commit` per §5 (`Iterator[Commit]`); if so, simplify to `c.id.hex`.

- [ ] **Step 2: Run, confirm fail; implement `RevWalk` owning iterator in `src/revwalk.rs` (holds `Arc<Repository>` + traversal state). Reconciliation: rev-list function from the matrix. Build; confirm pass.**

- [ ] **Step 3: Commit.** `git commit -m "feat: add revwalk default order"`

### Task 4.2: Ordering option

**Files:** Modify `src/revwalk.rs`, `src/repository.rs`, `tests/test_revwalk.py`

- [ ] **Step 1: Write the failing test** comparing `order="topo"` and `order="date"` against `git rev-list --topo-order` / `--date-order` for a branched fixture (add a fixture with a merge). If grit-lib exposes only one order, support that one, document the limitation, and `xfail` the unsupported order with a reason.

- [ ] **Step 2: Implement the `order` keyword; build; confirm pass.**

- [ ] **Step 3: Commit.** `git commit -m "feat: add revwalk ordering option"`

---

# Phase 5 — Diff

Spec §8.5. Oracle: `git diff --raw -z`, `git diff-tree`.

### Task 5.1: `diff(a, b)` → `DiffEntry` set (raw status)

**Files:** Create `src/diff.rs`; modify `src/repository.rs`, `src/lib.rs`, `python/pygrit/__init__.py`; create `tests/test_diff.py`

- [ ] **Step 1: Build a two-commit fixture with add/modify/delete + write the failing test**

```python
import subprocess

import pytest


@pytest.fixture
def diff_repo(tmp_path, git_env):
    repo = tmp_path / "diff"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, env=git_env, check=True)
    (repo / "keep").write_text("a\n")
    (repo / "gone").write_text("b\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, env=git_env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, env=git_env, check=True)
    (repo / "keep").write_text("a2\n")     # modify
    (repo / "gone").unlink()               # delete
    (repo / "added").write_text("c\n")     # add
    subprocess.run(["git", "add", "-A"], cwd=repo, env=git_env, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "change"], cwd=repo, env=git_env, check=True)
    return repo


def test_diff_status_matches_git(diff_repo):
    import pygrit
    from tests.gitlib import run_git, rev_parse

    a = rev_parse(diff_repo, "HEAD^")
    b = rev_parse(diff_repo, "HEAD")
    # diff --raw -z: "<meta>\0<path>\0[<path2>\0]" ; status letter is last meta field
    raw = run_git(diff_repo, "diff", "--raw", "-z", a, b)
    fields = [f for f in raw.split(b"\0") if f]
    # Parse status+path pairs (meta token starts with ':')
    expected = {}
    i = 0
    while i < len(fields):
        meta = fields[i]
        status = meta.split(b" ")[-1].decode()  # e.g. 'M','A','D'
        path = fields[i + 1]
        expected[path] = status[0]
        i += 2

    repo = pygrit.Repository.discover(str(diff_repo))
    d = repo.diff(repo.resolve("HEAD^"), repo.resolve("HEAD"))
    got = {e.new_path if e.status != "D" else e.old_path: e.status for e in d}
    assert got == expected
```
Reconciliation: confirm grit-lib diff status letters/enum (`A`/`M`/`D`/`R`/`C`) vs pygrit's `.status` string in the API matrix; normalize in the binding so the test's single-letter comparison holds.

- [ ] **Step 2: Run, confirm fail; implement `Diff` (owning iterator) + `DiffEntry` (frozen: `old_path`, `new_path`, `status`, `old_id`, `new_id`) in `src/diff.rs`. Build; confirm pass.**

- [ ] **Step 3: Commit.** `git commit -m "feat: add diff(a,b) -> DiffEntry with raw status"`

### Task 5.2: Diffstat summary

**Files:** Modify `src/diff.rs`, `tests/test_diff.py`

- [ ] **Step 1: Write the failing test** asserting `d.stats` (files changed, insertions, deletions) against `git diff --numstat` totals.

- [ ] **Step 2: Implement `.stats` (a small frozen struct or namedtuple-like pyclass); build; confirm pass.**

- [ ] **Step 3: Commit.** `git commit -m "feat: add diffstat summary"`

---

# Phase 6 — Config, stubs, concurrency, CI

Spec §8.6, §6, §7.

### Task 6.1: `ConfigSet` getters

**Files:** Modify `src/repository.rs` (add a `config.rs` if it grows); create `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
import subprocess


def test_config_get(simple_repo, git_env):
    import pygrit

    subprocess.run(["git", "config", "user.name", "Alice"], cwd=simple_repo, env=git_env, check=True)
    subprocess.run(["git", "config", "core.bare", "false"], cwd=simple_repo, env=git_env, check=True)
    subprocess.run(["git", "config", "core.repositoryformatversion", "0"], cwd=simple_repo, env=git_env, check=True)

    repo = pygrit.Repository.discover(str(simple_repo))
    cfg = repo.config
    assert cfg.get_str("user.name") == "Alice"
    assert cfg.get_bool("core.bare") is False
    assert cfg.get_int("core.repositoryformatversion") == 0
    assert cfg.get_str("no.such.key") is None
```

- [ ] **Step 2: Run, confirm fail; implement `ConfigSet` with `.config` accessor on `Repository` and `get_str/get_bool/get_int(key) -> ... | None`. Reconciliation: config API from the matrix. Build; confirm pass.**

- [ ] **Step 3: Commit.** `git commit -m "feat: add ConfigSet getters"`

### Task 6.2: Concurrency / GIL-release test

Spec §6.

**Files:** Create `tests/test_concurrency.py`

- [ ] **Step 1: Write the test**

```python
import threading

from tests.gitlib import rev_parse


def test_concurrent_reads(simple_repo):
    import pygrit

    repo = pygrit.Repository.discover(str(simple_repo))
    oid = pygrit.ObjectId.from_hex(rev_parse(simple_repo, "HEAD:a.txt"))
    errors: list[BaseException] = []

    def worker():
        try:
            for _ in range(200):
                assert repo.odb.read(oid).id == oid
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
```
This asserts thread-safety (no crash/corruption under concurrent reads). A measurable-speedup probe for actual GIL release is optional and environment-sensitive; if added, mark it non-blocking.

- [ ] **Step 2: Run and confirm pass** (`allow_threads` already used in odb read). If it deadlocks or crashes, fix the binding. Commit: `git commit -m "test: concurrent reads across threads"`.

### Task 6.3: Type stubs (`__init__.pyi`) + stubtest

Spec §4, §9.

**Files:** Create `python/pygrit/__init__.pyi`

- [ ] **Step 1: Write the stub** declaring every public symbol with exact signatures matching the final Python API: `Repository`, `Odb`, `ObjectId`, `ObjectKind`, `Object`, `Commit`, `Tree`, `TreeEntry`, `Blob`, `Tag`, `Signature`, `Reference`, `Diff`, `DiffEntry`, `ConfigSet`, and the four exceptions. Use `bytes` for git data getters and `str` for decoded accessors, per §5.

- [ ] **Step 2: Run stubtest**

```bash
uv run maturin develop --uv
uv run python -m mypy.stubtest pygrit
```
Expected: no errors. Fix mismatches between the stub and the real module until clean.

- [ ] **Step 3: Run mypy on the tests** to confirm the stubs are usable:
```bash
uv run mypy tests/
```
Fix typing issues.

- [ ] **Step 4: Commit.** `git commit -m "feat: add type stubs; stubtest clean"`

### Task 6.4: Lint/format gates green

**Files:** none (verification) — possibly small fixes across `src/` and `tests/`

- [ ] **Step 1: Run all gates**

```bash
uv run ruff format --check .
uv run ruff check .
cargo fmt --check
cargo clippy --all-targets -- -D warnings
```
Expected: all clean. Fix anything that fails (run `ruff format .` / `cargo fmt` to auto-fix formatting).

- [ ] **Step 2: Commit any fixes.** `git commit -m "chore: satisfy ruff/clippy/fmt gates"`

### Task 6.5: CI matrix

Spec §7 (mandatory CI).

**Files:** Create `.github/workflows/ci.yml`

- [ ] **Step 1: Write the workflow** with these jobs:
  - **lint:** `cargo fmt --check`, `cargo clippy -- -D warnings`, `ruff format --check`, `ruff check`.
  - **test:** matrix over Python `["3.11", "3.13"]` (oldest + current) on `ubuntu-latest`; steps: checkout, install uv, install the pinned Rust toolchain, cargo cache, `uv run maturin develop --uv`, `uv run pytest`, `uv run mypy tests/`, `uv run python -m mypy.stubtest pygrit`.
  - **build-wheels:** `ubuntu-latest` x86_64 and aarch64 (via `maturin-action` or cross), plus macOS best-effort; build wheel + sdist with `--locked`; verify the wheel has an `abi3` tag; install the wheel into a clean venv and run a smoke import; build-and-install from the sdist and smoke it.
  - All builds use `--locked`.

Provide the concrete YAML using `actions/checkout@v4`, `astral-sh/setup-uv@v3`, `dtolnay/rust-toolchain@1.94.1`, `Swatinem/rust-cache@v2`, and `PyO3/maturin-action@v1` for the wheel matrix.

- [ ] **Step 2: Validate locally** what can be validated:
```bash
uv run maturin build --release --locked
```
Expected: succeeds (mirrors the CI build step).

- [ ] **Step 3: Commit.** `git commit -m "ci: add mandatory build/test/lint matrix"`

### Task 6.6: README finalize + version-compatibility table

**Files:** Modify `README.md`

- [ ] **Step 1: Finalize the README:** quickstart (`uv`, build, a runnable read example), supported Python/platforms, the byte/text policy summary, the exception hierarchy, and the pygrit↔grit-lib version-compatibility table (pin recorded in Task 1.8).

- [ ] **Step 2: Commit.** `git commit -m "docs: finalize README with compatibility table"`

---

## Self-review (performed against the spec)

**Spec coverage check:**
- §2 read-core goals → Phases 2–6 (objects/odb, refs/resolve, revwalk, diff, config). ✓
- §3 decisions → PyO3/maturin scaffold (1.3), exact pin + Cargo.lock (1.3/1.5), abi3-py311 (1.3), license (1.8). ✓
- §4 layout → file structure map + per-subsystem Rust files created across tasks. ✓
- §5 API surface + byte/text policy → Tasks 2.x–6.1; bytes getters + `*_str`/`message(encoding=)` in 2.7. ✓
- §5 provisional/API-matrix → Task 1.7 produces the matrix; reconciliation notes on each grit-lib call site. ✓
- §6 ownership/lifetime → Arc in 2.5/2.6, owning iterators in 2.8/3.1/4.1/5.1, lifetime test 2.9; GIL/concurrency 6.2. ✓
- §7 error hierarchy → 2.2; error mapping refined per task; oracle + mirrored tests throughout; shipped-artifact test 1.9; CI 6.5. ✓
- §8 milestones → Phases 1–6 map 1:1 to §8.1–§8.6. ✓
- §9 tooling, §10 toolchain, §11 open items (license/Python floor/platforms/SHA-256/pin) → 1.1, 1.7, 1.8, 6.3–6.6. ✓

**Placeholder scan:** The `map_kind`/error-mapping/grit-lib-call seams are explicitly marked "Reconciliation" with a fixed test contract and a concrete adjustment instruction — not open-ended TODOs. The one literal placeholder body (`map_kind` `()`) is paired with the exact replacement instruction and a test that fails until it is correct. Acceptable given the spec mandates a matrix-first spike.

**Type/name consistency:** Python API names are fixed and reused consistently (`ObjectId.from_hex`, `.hex/.raw/.hash_algorithm`, `Repository.discover/open`, `repo.odb/.config/.references()/.resolve()/.revwalk()/.diff()`, `repo.commit/tree/blob/tag` accessors, `*_path`/`*_id`/`status` on `DiffEntry`). Stub task (6.3) is the single source of truth and stubtest enforces it.

**Open decision deferred to execution (flagged, not a gap):** whether `revwalk` yields `Commit` (spec §5 preference) or `ObjectId` — Task 4.1 fixes it at the stub in 6.3. The test tolerates both pre-decision but the stub locks it.
