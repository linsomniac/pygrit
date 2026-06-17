# pylibgrit Phase C — Networking & Clone (read-path) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `ls_remote`, `fetch`, and `clone` over git:// and https to pylibgrit, assembled from grit-lib 0.4.1 networking plumbing (no clone porcelain upstream).

**Architecture:** A thin Rust transport layer dispatches by URL scheme. git:// uses `GitDaemonTransport` + `fetch_remote` (the binding applies the returned ref updates); https uses a bundled `UreqHttpClient` + `http_fetch` (self-applies). `ls_remote` reads the v0/v1 ref advertisement off a `Connection`. `clone` = init + write `origin` config + fetch + create local branch/HEAD + checkout. Credentials are an in-Rust `CredentialProvider` (explicit/userinfo creds chained to grit's git-credential-helper provider). Progress is an optional `bytes` callback bridged to grit's `fetch::Progress`.

**Tech Stack:** Rust + PyO3 0.23 (abi3), grit-lib 0.4.1 with the `http-ureq` feature, maturin, pytest with a hermetic `git daemon` fixture (git://) and a `git http-backend` fixture (https).

**Spec:** `docs/superpowers/specs/2026-06-17-pylibgrit-networking-clone-design.md`

## Build & gates (run after every code change)

```bash
uv run maturin develop --uv --locked          # rebuild the extension (compiles http-ureq in)
uv run pytest -q                              # tests
uv run mypy python tests                      # type-check
uv run python -m mypy.stubtest pylibgrit      # stub matches runtime (NO allowlist)
cargo fmt --check
cargo clippy --all-targets --locked -- -D warnings
uv run ruff format --check
uv run ruff check
```

If `uv run` reinstalls a stale cached build, force a rebuild: `uv pip install -e . --reinstall-package pylibgrit`.

**Imports note:** `cargo clippy -- -D warnings` denies unused imports and dead code. Each task's code blocks list exactly the symbols that task uses; when a later task first uses another symbol from a module already imported (e.g. `crate::error::network_err`, first used by `clone_impl` in Task 5), widen that task's `use` line accordingly. Do not pre-import symbols a task does not yet use.

## File structure

| File | Responsibility |
| --- | --- |
| `Cargo.toml` (modify) | enable grit-lib `http-ureq` feature; bump version to 0.3.0 (Task 9) |
| `src/error.rs` (modify) | add `NetworkError` + `AuthenticationError`; route `Error::Auth`; `net_map_err`/`network_err` |
| `src/net_transport.rs` (new) | URL scheme classification + userinfo split + git:// connect helper |
| `src/net_progress.rs` (new) | `PyProgress`: optional Python `bytes` callback → `grit_lib::fetch::Progress` |
| `src/net_credentials.rs` (new) | `StaticCredentialProvider` (explicit/userinfo) chained to `HelperCredentialProvider`; https client builder |
| `src/remote.rs` (new) | `RemoteRef`/`RefUpdate`/`FetchReport` pyclasses; `ls_remote` pyfunction; `fetch_raw`/`fetch_method`/`clone_impl`; `UpdateMode`→str |
| `src/repository.rs` (modify) | `Repository.clone` staticmethod + `Repository.fetch` method (thin delegators) |
| `src/lib.rs` (modify) | `mod` new modules; register classes + `ls_remote` function |
| `python/pylibgrit/__init__.py` (modify) | export new symbols |
| `python/pylibgrit/__init__.pyi` (modify) | stubs for new symbols |
| `tests/conftest.py` (modify) | `git_daemon` fixture + free-port/wait helpers; `seeded_source` helper |
| `tests/githttp.py` (new) | `git http-backend` HTTP server (anonymous + Basic-auth) for https tests |
| `tests/test_*.py` (new) | ls_remote / fetch / clone / https / credentials tests |

---

## Task 1: Packaging (http-ureq) + network exceptions

**Files:**
- Modify: `Cargo.toml:16-20`
- Modify: `src/error.rs`
- Modify: `python/pylibgrit/__init__.py`
- Modify: `python/pylibgrit/__init__.pyi`
- Test: `tests/test_net_errors.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_net_errors.py`:

```python
"""The two networking exception types exist and subclass GritError."""

import pylibgrit


def test_network_error_is_griterror_subclass() -> None:
    assert issubclass(pylibgrit.NetworkError, pylibgrit.GritError)


def test_authentication_error_is_griterror_subclass() -> None:
    assert issubclass(pylibgrit.AuthenticationError, pylibgrit.GritError)


def test_exceptions_are_distinct() -> None:
    assert pylibgrit.NetworkError is not pylibgrit.AuthenticationError
    assert not issubclass(pylibgrit.NetworkError, pylibgrit.AuthenticationError)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_net_errors.py -q`
Expected: FAIL with `AttributeError: module 'pylibgrit' has no attribute 'NetworkError'`.

- [ ] **Step 3: Enable the http-ureq feature**

In `Cargo.toml`, change the grit-lib dependency (line 20) to:

```toml
grit-lib = { version = "=0.4.1", features = ["http-ureq"] }
```

- [ ] **Step 4: Add the exceptions and network error mapping**

In `src/error.rs`, after the `RefMismatchError` `create_exception!` block (line 43), add:

```rust
create_exception!(
    _pylibgrit,
    NetworkError,
    GritError,
    "A transport, protocol, or transfer failure while talking to a remote."
);
create_exception!(
    _pylibgrit,
    AuthenticationError,
    GritError,
    "The remote rejected the supplied (or absent) credentials."
);
```

In `map_err`, route `Error::Auth` before the catch-all. Change the final two arms:

```rust
        // Bad path argument shape.
        Error::PathError(_) => PyValueError::new_err(msg),

        // Remote authentication failure (HTTP 401, helper rejected, etc.).
        Error::Auth(_) => AuthenticationError::new_err(msg),

        // Everything else (index, cache-tree, signing, push-options, generic
        // message) plus any future `#[non_exhaustive]` variant.
        _ => GritError::new_err(msg),
```

After the `invalid_ref` helper (line 98), add the network-context mapper:

```rust
// AIDEV-NOTE: Network-context error mapping for the fetch/clone/ls_remote paths. grit's broad
// `Error::Message` (transport/protocol failures) and transfer-time `Error::Io` (connection
// refused, reset, …) become NetworkError; every other variant — including `Error::Auth` →
// AuthenticationError — defers to `map_err`, so object/ref/repo faults keep their normal class.
pub fn net_map_err(e: grit_lib::error::Error) -> PyErr {
    use grit_lib::error::Error;
    match e {
        Error::Message(_) | Error::Io(_) => NetworkError::new_err(format!("{e}")),
        other => map_err(other),
    }
}

// AIDEV-NOTE: Construct a NetworkError directly from a binding-layer message (e.g. an
// unsupported URL scheme) that does not originate from a `grit_lib::error::Error`.
pub fn network_err(msg: &str) -> PyErr {
    NetworkError::new_err(msg.to_owned())
}
```

In `register`, add the two new types (after the `RefMismatchError` line):

```rust
    m.add("NetworkError", m.py().get_type::<NetworkError>())?;
    m.add(
        "AuthenticationError",
        m.py().get_type::<AuthenticationError>(),
    )?;
```

- [ ] **Step 5: Export from Python**

In `python/pylibgrit/__init__.py`, add `AuthenticationError,` and `NetworkError,` to BOTH the `from pylibgrit._pylibgrit import (...)` block and `__all__` (keep alphabetical order — `AuthenticationError` after `import enum`/before `Blob`; `NetworkError` after `MergeResult`).

In `python/pylibgrit/__init__.pyi`, add to `__all__` (same positions) and add the stub classes after `RefMismatchError` (line 56):

```python
class NetworkError(GritError):
    """Raised for transport/protocol/transfer failures talking to a remote."""

class AuthenticationError(GritError):
    """Raised when a remote rejects the supplied (or absent) credentials."""
```

- [ ] **Step 6: Build and run all gates**

Run:
```bash
uv run maturin develop --uv --locked
uv run pytest tests/test_net_errors.py -q
uv run mypy python tests && uv run python -m mypy.stubtest pylibgrit
cargo fmt --check && cargo clippy --all-targets --locked -- -D warnings
uv run ruff format --check && uv run ruff check
```
Expected: test PASSES; all gates green. (The first build now compiles `ureq`+`rustls`; this is expected and slower.)

- [ ] **Step 7: Commit**

```bash
git add Cargo.toml Cargo.lock src/error.rs python/pylibgrit/__init__.py python/pylibgrit/__init__.pyi tests/test_net_errors.py
git commit -m "feat: bundle http-ureq; add NetworkError + AuthenticationError"
```

---

## Task 2: Hermetic `git daemon` fixture (git://)

**Files:**
- Modify: `tests/conftest.py`
- Test: `tests/test_git_daemon_fixture.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_git_daemon_fixture.py`:

```python
"""The git_daemon fixture serves a bare repo reachable over git:// (oracle check)."""

from __future__ import annotations

from tests.gitlib import run_git


def test_daemon_serves_refs(git_daemon, tmp_path) -> None:
    # `git ls-remote` (the oracle) can reach the served repo and see refs/heads/main.
    out = run_git(tmp_path, "ls-remote", git_daemon.repo_url).decode()
    assert "refs/heads/main" in out
    assert git_daemon.head_oid in out
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_git_daemon_fixture.py -q`
Expected: FAIL with `fixture 'git_daemon' not found`.

- [ ] **Step 3: Implement the fixture**

In `tests/conftest.py`, add imports at the top (after the existing imports):

```python
import socket
import time
from types import SimpleNamespace
```

Append to `tests/conftest.py`:

```python
def _free_port() -> int:
    """Grab an ephemeral port by binding to :0 and releasing it."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_port(host: str, port: int, proc: subprocess.Popen, timeout: float) -> bool:
    """Poll until `host:port` accepts a connection or `proc` dies / `timeout` elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False  # daemon exited (e.g. `git daemon` unavailable)
        try:
            with socket.create_connection((host, port), timeout=0.25):
                return True
        except OSError:
            time.sleep(0.05)
    return False


@pytest.fixture
def git_daemon(tmp_path: Path, git_env: dict[str, str]):
    """Serve a seeded bare repo over git:// on localhost. Skips if `git daemon` is unavailable.

    Yields a namespace with `repo_url`, `server_path` (the bare repo), and `head_oid`.
    """
    base = tmp_path / "srv"
    base.mkdir()
    # Seed a source repo, then make the served bare repo a clone of it.
    src = tmp_path / "src"
    src.mkdir()
    _git(src, git_env, "init", "-q", "-b", "main")
    (src / "a.txt").write_text("hello\n")
    (src / "dir").mkdir()
    (src / "dir" / "b.txt").write_text("world\n")
    _git(src, git_env, "add", "-A")
    _git(src, git_env, "commit", "-q", "-m", "initial commit")
    _git(src, git_env, "tag", "v1")
    server = base / "server.git"
    _git(tmp_path, git_env, "clone", "-q", "--bare", str(src), str(server))
    head_oid = run_git(src, "rev-parse", "HEAD").decode().strip()

    port = _free_port()
    proc = subprocess.Popen(
        [
            "git", "daemon",
            "--reuseaddr",
            "--listen=127.0.0.1",
            f"--port={port}",
            f"--base-path={base}",
            "--export-all",
            str(base),
        ],
        env=git_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not _wait_port("127.0.0.1", port, proc, timeout=5.0):
        proc.terminate()
        pytest.skip("git daemon unavailable")
    try:
        yield SimpleNamespace(
            repo_url=f"git://127.0.0.1:{port}/server.git",
            server_path=server,
            src=src,
            head_oid=head_oid,
            env=git_env,
        )
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
```

Note: `run_git` is already imported in the test from `tests.gitlib`; in `conftest.py` add `from tests.gitlib import run_git` near the top imports.

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/test_git_daemon_fixture.py -q`
Expected: PASS (or SKIP if the CI image lacks `git daemon`).

- [ ] **Step 5: Run gates and commit**

```bash
uv run mypy python tests && uv run ruff format --check && uv run ruff check
git add tests/conftest.py tests/test_git_daemon_fixture.py
git commit -m "test: hermetic git daemon fixture (git://)"
```

---

## Task 3: `ls_remote` over git:// (+ transport scaffolding + RemoteRef)

**Files:**
- Create: `src/net_transport.rs`
- Create: `src/remote.rs`
- Modify: `src/lib.rs`
- Modify: `python/pylibgrit/__init__.py`, `python/pylibgrit/__init__.pyi`
- Test: `tests/test_ls_remote.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_ls_remote.py`:

```python
"""ls_remote over git:// matches `git ls-remote` and supports filters."""

from __future__ import annotations

import pytest

import pylibgrit
from tests.gitlib import run_git


def _oracle_refs(repo_dir, url) -> dict[str, str]:
    # name -> oid for non-peeled rows of `git ls-remote`.
    out = run_git(repo_dir, "ls-remote", url).decode()
    refs = {}
    for line in out.splitlines():
        oid, name = line.split("\t")
        if name.endswith("^{}"):
            continue
        refs[name] = oid
    return refs


def test_ls_remote_matches_oracle(git_daemon, tmp_path) -> None:
    oracle = _oracle_refs(tmp_path, git_daemon.repo_url)
    got = {r.name.decode(): r.oid.hex for r in pylibgrit.ls_remote(git_daemon.repo_url)}
    # Both must agree on the real refs (HEAD + refs/heads/main + refs/tags/v1).
    assert got["refs/heads/main"] == oracle["refs/heads/main"]
    assert got["refs/tags/v1"] == oracle["refs/tags/v1"]
    assert "HEAD" in got


def test_ls_remote_head_symref(git_daemon) -> None:
    head = next(r for r in pylibgrit.ls_remote(git_daemon.repo_url) if r.name == b"HEAD")
    assert head.symref_target == b"refs/heads/main"


def test_ls_remote_heads_filter(git_daemon) -> None:
    names = {r.name for r in pylibgrit.ls_remote(git_daemon.repo_url, heads=True)}
    assert names == {b"refs/heads/main"}


def test_ls_remote_tags_filter(git_daemon) -> None:
    names = {r.name for r in pylibgrit.ls_remote(git_daemon.repo_url, tags=True)}
    assert names == {b"refs/tags/v1"}


def test_ls_remote_unsupported_scheme_raises() -> None:
    with pytest.raises(pylibgrit.NetworkError):
        pylibgrit.ls_remote("ssh://example.com/repo.git")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_ls_remote.py -q`
Expected: FAIL with `AttributeError: module 'pylibgrit' has no attribute 'ls_remote'`.

- [ ] **Step 3: Create the transport scaffolding**

Create `src/net_transport.rs` (this task adds `classify` + `git_connect`; `split_userinfo` is added in Task 4, where it is first used, to keep every task free of dead code under `clippy -D warnings`):

```rust
//! URL-scheme dispatch for the read-path network surface: classify a remote URL and connect git://.
//! (`split_userinfo` is added in Task 4.)

use grit_lib::transport::{Connection, ConnectOptions, GitDaemonTransport, Service, Transport};
use pyo3::prelude::*;

use crate::error::network_err;

// AIDEV-NOTE: Supported read-path schemes. ssh, file://, and scp-like `git@host:path` are out of
// scope (spec §1) and are reported as a clear NetworkError rather than a deep transport failure.
pub(crate) enum Scheme {
    Git,
    Http,
}

pub(crate) fn classify(url: &str) -> PyResult<Scheme> {
    if url.starts_with("git://") {
        Ok(Scheme::Git)
    } else if url.starts_with("https://") || url.starts_with("http://") {
        Ok(Scheme::Http)
    } else {
        Err(network_err(&format!(
            "unsupported transport for URL {url:?}; supported schemes: git://, http://, https://"
        )))
    }
}

// AIDEV-NOTE: Connect a git:// service. `protocol_version` is forced to 1 for ls_remote (so the
// server sends a v0/v1 ref advertisement we can read off the Connection); fetch passes 0 (let grit
// pick). The returned `Box<dyn Connection>` is `!Send`, so callers MUST construct + consume it inside
// one `allow_threads` closure (never cross the boundary with it).
pub(crate) fn git_connect(
    url: &str,
    protocol_version: u8,
) -> Result<Box<dyn Connection>, grit_lib::error::Error> {
    let opts = ConnectOptions {
        protocol_version,
        server_options: Vec::new(),
    };
    GitDaemonTransport::new().connect(url, Service::UploadPack, &opts)
}
```

- [ ] **Step 4: Create the remote porcelain with `ls_remote` + `RemoteRef`**

Create `src/remote.rs`:

```rust
//! Read-path network porcelain: ls_remote / fetch / clone, plus the value-object pyclasses.

use std::path::Path;

use grit_lib::transport::Connection;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

use crate::error::net_map_err;
use crate::net_transport::{classify, git_connect, Scheme};

// AIDEV-NOTE: One advertised remote ref. `name`/`symref_target` are bytes (house style: ref names
// are bytes everywhere in the binding); `oid` is an ObjectId. HEAD is synthesized from the
// connection's head_symref + the symref target's advertised oid (advertised_refs excludes HEAD).
#[pyclass(module = "pylibgrit._pylibgrit")]
pub struct RemoteRef {
    name: Vec<u8>,
    oid: grit_lib::objects::ObjectId,
    symref_target: Option<Vec<u8>>,
}

#[pymethods]
impl RemoteRef {
    #[getter]
    fn name<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.name)
    }
    #[getter]
    fn oid(&self) -> crate::objects::ObjectId {
        crate::objects::ObjectId::from_inner(self.oid)
    }
    #[getter]
    fn symref_target<'py>(&self, py: Python<'py>) -> Option<Bound<'py, PyBytes>> {
        self.symref_target.as_ref().map(|t| PyBytes::new(py, t))
    }
    fn __repr__(&self) -> String {
        format!(
            "RemoteRef(name={:?}, oid='{}')",
            String::from_utf8_lossy(&self.name),
            self.oid.to_hex()
        )
    }
}

// AIDEV-NOTE: Read the v0/v1 ref advertisement from a freshly-opened connection. Returns owned
// (name, oid) pairs plus the HEAD symref target — everything is cloned out so the `!Send` connection
// is dropped inside the caller's allow_threads closure. `protocol_version: 1` forces the
// advertisement (v2 advertises nothing on connect).
fn read_advertisement(url: &str) -> Result<(Vec<(String, grit_lib::objects::ObjectId)>, Option<String>), grit_lib::error::Error> {
    let conn = git_connect(url, 1)?;
    let refs = conn.advertised_refs().to_vec();
    let head = conn.head_symref().map(str::to_owned);
    Ok((refs, head))
}

// AIDEV-NOTE: List remote refs (== `git ls-remote`), built from the connection advertisement (grit's
// `ls_remote` is local-only). `heads`/`tags` restrict to those namespaces and drop the synthesized
// HEAD row (matching `git ls-remote --heads/--tags`). Peeled `^{}` rows are not surfaced (grit's
// advertised_refs omits them) — a documented limitation.
#[pyfunction]
#[pyo3(signature = (url, *, username=None, password=None, use_credential_helpers=true, heads=false, tags=false))]
pub fn ls_remote(
    py: Python<'_>,
    url: String,
    username: Option<String>,
    password: Option<String>,
    use_credential_helpers: bool,
    heads: bool,
    tags: bool,
) -> PyResult<Vec<RemoteRef>> {
    let (advertised, head_target) = match classify(&url)? {
        Scheme::Git => py
            .allow_threads(|| read_advertisement(&url))
            .map_err(net_map_err)?,
        Scheme::Http => {
            crate::net_credentials::http_advertisement(py, &url, username, password, use_credential_helpers)?
        }
    };

    let mut out: Vec<RemoteRef> = Vec::new();

    // Synthesized HEAD row (only in the unfiltered default, like `git ls-remote`).
    if !heads && !tags {
        if let Some(target) = &head_target {
            if let Some((_, oid)) = advertised.iter().find(|(n, _)| n == target) {
                out.push(RemoteRef {
                    name: b"HEAD".to_vec(),
                    oid: *oid,
                    symref_target: Some(target.clone().into_bytes()),
                });
            }
        }
    }

    for (name, oid) in advertised {
        let keep = if heads {
            name.starts_with("refs/heads/")
        } else if tags {
            name.starts_with("refs/tags/")
        } else {
            true
        };
        if keep {
            out.push(RemoteRef {
                name: name.into_bytes(),
                oid,
                symref_target: None,
            });
        }
    }
    Ok(out)
}
```

Add a TEMPORARY stub so the crate compiles before Task 7 adds the real https client. At the bottom of `src/net_credentials.rs` (created in this task as a stub, fully implemented in Task 7/8) — create `src/net_credentials.rs`:

```rust
//! HTTPS credential wiring (filled in by Tasks 7-8). For now: a placeholder advertisement reader
//! so git:// ls_remote compiles; https is wired in Task 7.

use pyo3::prelude::*;

use crate::error::network_err;

// AIDEV-NOTE: PLACEHOLDER (replaced in Task 7). https read-path is not wired until the http client +
// credential provider land; until then an http(s) URL is a clear NetworkError.
#[allow(clippy::type_complexity)]
pub(crate) fn http_advertisement(
    _py: Python<'_>,
    url: &str,
    _username: Option<String>,
    _password: Option<String>,
    _use_credential_helpers: bool,
) -> PyResult<(Vec<(String, grit_lib::objects::ObjectId)>, Option<String>)> {
    Err(network_err(&format!(
        "https transport not yet available for {url:?} (implemented in a later task)"
    )))
}
```

- [ ] **Step 5: Register the module + function**

In `src/lib.rs`, add the module declarations (after `mod merge;`):

```rust
mod net_credentials;
mod net_transport;
mod remote;
```

In the `_pylibgrit` function, register the class and the free function (after the `MergeResult` class registration):

```rust
    m.add_class::<remote::RemoteRef>()?;
    m.add_function(wrap_pyfunction!(remote::ls_remote, m)?)?;
```

- [ ] **Step 6: Export from Python**

In `python/pylibgrit/__init__.py`: add `RemoteRef,` to the import block and `__all__`, and add `ls_remote,` to the import block and `__all__` (alphabetical: `RemoteRef` near the R's; `ls_remote` sorts after the capitalized names — append it and keep the list sorted case-insensitively, i.e. place `"ls_remote"` after `"InvalidObjectError"`/before `"MergeResult"` is wrong case-insensitively; put it where your sorter agrees with ruff — run `uv run ruff check` and follow its ordering).

In `python/pylibgrit/__init__.pyi`: add `RemoteRef` and `ls_remote` to `__all__`; add the class stub (after the exception stubs / near the value types):

```python
@final
class RemoteRef:
    @property
    def name(self) -> bytes: ...
    @property
    def oid(self) -> ObjectId: ...
    @property
    def symref_target(self) -> bytes | None: ...
```

and the module-level function stub (near the bottom, after the `Repository` class):

```python
def ls_remote(
    url: str,
    *,
    username: str | None = None,
    password: str | None = None,
    use_credential_helpers: bool = True,
    heads: bool = False,
    tags: bool = False,
) -> list[RemoteRef]: ...
```

- [ ] **Step 7: Build, test, gates**

Run:
```bash
uv run maturin develop --uv --locked
uv run pytest tests/test_ls_remote.py -q
uv run mypy python tests && uv run python -m mypy.stubtest pylibgrit
cargo fmt --check && cargo clippy --all-targets --locked -- -D warnings
uv run ruff format --check && uv run ruff check
```
Expected: tests PASS (or SKIP without `git daemon`); gates green.

- [ ] **Step 8: Commit**

```bash
git add src/net_transport.rs src/remote.rs src/net_credentials.rs src/lib.rs python/pylibgrit/ tests/test_ls_remote.py
git commit -m "feat: ls_remote over git:// (advertisement-based) + RemoteRef"
```

---

## Task 4: `repo.fetch` over git:// (+ FetchReport / RefUpdate)

**Files:**
- Modify: `src/remote.rs`
- Create: `src/net_progress.rs`
- Modify: `src/repository.rs`, `src/lib.rs`
- Modify: `python/pylibgrit/__init__.py`, `python/pylibgrit/__init__.pyi`
- Test: `tests/test_fetch.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_fetch.py`:

```python
"""repo.fetch over git:// writes tracking refs + objects and reports updates."""

from __future__ import annotations

import pylibgrit


def test_fetch_writes_tracking_refs_and_objects(git_daemon, tmp_path) -> None:
    dst = tmp_path / "dst"
    repo = pylibgrit.Repository.init(dst)
    report = repo.fetch(git_daemon.repo_url)

    # The remote main tip is now an object in our odb under refs/remotes/origin/main.
    head = pylibgrit.ObjectId.from_hex(git_daemon.head_oid)
    assert repo.odb.exists(head)
    track = repo.resolve("refs/remotes/origin/main")
    assert track.hex == git_daemon.head_oid

    modes = {u.remote_ref: u.mode for u in report.updates}
    assert modes[b"refs/heads/main"] == "new"
    assert report.default_branch == b"refs/heads/main"


def test_fetch_idempotent_second_is_not_new(git_daemon, tmp_path) -> None:
    dst = tmp_path / "dst"
    repo = pylibgrit.Repository.init(dst)
    repo.fetch(git_daemon.repo_url)
    report = repo.fetch(git_daemon.repo_url)
    modes = {u.remote_ref: u.mode for u in report.updates}
    # Nothing changed on the second fetch.
    assert modes[b"refs/heads/main"] in {"up-to-date", "no-change-needed"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_fetch.py -q`
Expected: FAIL with `AttributeError: 'Repository' object has no attribute 'fetch'`.

- [ ] **Step 3: Add the progress bridge**

Create `src/net_progress.rs`:

```rust
//! Bridge an optional Python `bytes` callable to grit's `fetch::Progress` (side-band-2 stream).

use pyo3::prelude::*;
use pyo3::types::PyBytes;

// AIDEV-NOTE: `grit_lib::fetch::Progress` has a single infallible method `message(&mut self, &[u8])`.
// `PyProgress` wraps an optional Python callable invoked once per side-band-2 chunk. The transfer
// runs under allow_threads (GIL released); `message` re-acquires the GIL via `Python::with_gil` for
// just the callback, so the callback never holds the GIL across the transfer. A Python exception is
// CAPTURED (grit's `message` cannot return an error / unwind through FFI) and re-raised by the caller
// via `take_error()` after the transfer returns. `Py<PyAny>` + `Option<PyErr>` are both Send, so
// `&mut PyProgress` may cross into allow_threads.
pub(crate) struct PyProgress {
    callback: Option<Py<PyAny>>,
    error: Option<PyErr>,
}

impl PyProgress {
    pub(crate) fn new(callback: Option<Py<PyAny>>) -> Self {
        Self { callback, error: None }
    }
    pub(crate) fn take_error(&mut self) -> Option<PyErr> {
        self.error.take()
    }
}

impl grit_lib::fetch::Progress for PyProgress {
    fn message(&mut self, bytes: &[u8]) {
        if self.error.is_some() {
            return; // already failed; ignore further chunks
        }
        let Some(cb) = &self.callback else {
            return;
        };
        Python::with_gil(|py| {
            let arg = PyBytes::new(py, bytes);
            if let Err(e) = cb.call1(py, (arg,)) {
                self.error = Some(e);
            }
        });
    }
}
```

- [ ] **Step 4a: Add `split_userinfo` to `src/net_transport.rs`**

Append to `src/net_transport.rs` (no new imports — std only):

```rust
// AIDEV-NOTE: Split optional `user[:pass]@` userinfo out of an http(s) authority. ureq's client does
// NOT honor URL userinfo, so we extract it for the credential provider and return the URL with
// userinfo removed for the actual request. Only the authority right after `scheme://` is examined (a
// later '@' in the path is left alone). Userinfo is used LITERALLY — not percent-decoded; callers
// with reserved characters in a token should pass `password=` instead. Returns
// (clean_url, Some((user, Option<pass>))) when userinfo is present.
pub(crate) fn split_userinfo(url: &str) -> (String, Option<(String, Option<String>)>) {
    let Some((scheme, rest)) = url.split_once("://") else {
        return (url.to_owned(), None);
    };
    let auth_end = rest.find(['/', '?', '#']).unwrap_or(rest.len());
    let (authority, tail) = rest.split_at(auth_end);
    let Some((userinfo, host)) = authority.rsplit_once('@') else {
        return (url.to_owned(), None);
    };
    let creds = match userinfo.split_once(':') {
        Some((u, p)) => (u.to_owned(), Some(p.to_owned())),
        None => (userinfo.to_owned(), None),
    };
    (format!("{scheme}://{host}{tail}"), Some(creds))
}
```

- [ ] **Step 4: Add FetchReport/RefUpdate + fetch_raw + fetch_method to `src/remote.rs`**

Append to `src/remote.rs` (add `use` lines at the top: `use grit_lib::transfer::{FetchOptions, FetchOutcome, TagMode, UpdateMode};`, `use std::sync::Arc;`, `use crate::net_progress::PyProgress;`):

```rust
// AIDEV-NOTE: One applied ref update from a fetch. Ref names are bytes; oids are ObjectId; `mode` is
// the lower-kebab `UpdateMode` name; `note` is grit's human-readable annotation.
#[pyclass(module = "pylibgrit._pylibgrit")]
pub struct RefUpdate {
    remote_ref: Vec<u8>,
    local_ref: Option<Vec<u8>>,
    old_oid: Option<grit_lib::objects::ObjectId>,
    new_oid: Option<grit_lib::objects::ObjectId>,
    mode: String,
    note: Option<String>,
}

#[pymethods]
impl RefUpdate {
    #[getter]
    fn remote_ref<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.remote_ref)
    }
    #[getter]
    fn local_ref<'py>(&self, py: Python<'py>) -> Option<Bound<'py, PyBytes>> {
        self.local_ref.as_ref().map(|r| PyBytes::new(py, r))
    }
    #[getter]
    fn old_oid(&self) -> Option<crate::objects::ObjectId> {
        self.old_oid.map(crate::objects::ObjectId::from_inner)
    }
    #[getter]
    fn new_oid(&self) -> Option<crate::objects::ObjectId> {
        self.new_oid.map(crate::objects::ObjectId::from_inner)
    }
    #[getter]
    fn mode(&self) -> &str {
        &self.mode
    }
    #[getter]
    fn note(&self) -> Option<&str> {
        self.note.as_deref()
    }
}

// AIDEV-NOTE: The result of a fetch: the applied ref updates + the remote's default branch (HEAD
// symref). Shallow fields are intentionally omitted (shallow deferred).
#[pyclass(module = "pylibgrit._pylibgrit")]
pub struct FetchReport {
    updates: Vec<Py<RefUpdate>>,
    default_branch: Option<Vec<u8>>,
}

#[pymethods]
impl FetchReport {
    #[getter]
    fn updates(&self, py: Python<'_>) -> Vec<Py<RefUpdate>> {
        self.updates.iter().map(|u| u.clone_ref(py)).collect()
    }
    #[getter]
    fn default_branch<'py>(&self, py: Python<'py>) -> Option<Bound<'py, PyBytes>> {
        self.default_branch.as_ref().map(|b| PyBytes::new(py, b))
    }
}

// AIDEV-NOTE: grit's UpdateMode -> the lower-kebab string surfaced as RefUpdate.mode.
fn update_mode_str(m: UpdateMode) -> &'static str {
    match m {
        UpdateMode::New => "new",
        UpdateMode::FastForward => "fast-forward",
        UpdateMode::Forced => "forced",
        UpdateMode::UpToDate => "up-to-date",
        UpdateMode::NoChangeNeeded => "no-change-needed",
        UpdateMode::NonFastForwardRejected => "non-fast-forward-rejected",
        UpdateMode::TagUpdateRejected => "tag-update-rejected",
        UpdateMode::SourceObjectNotFound => "source-object-not-found",
        UpdateMode::Unborn => "unborn",
        UpdateMode::DeletedMissing => "deleted-missing",
    }
}

// AIDEV-NOTE: Apply the ref updates fetch_remote (git://) returns but does NOT write itself — exactly
// the New/FastForward/Forced cases, exactly as http_fetch does internally. Runs inside the same
// allow_threads closure as the fetch (plain loose/packed writes; no `!Send` connection here).
fn apply_ref_updates(git_dir: &Path, outcome: &FetchOutcome) -> Result<(), grit_lib::error::Error> {
    for u in &outcome.updates {
        if !matches!(u.mode, UpdateMode::New | UpdateMode::FastForward | UpdateMode::Forced) {
            continue;
        }
        if let (Some(local), Some(new)) = (&u.local_ref, &u.new_oid) {
            grit_lib::refs::write_ref(git_dir, local, new)?;
        }
    }
    Ok(())
}

// AIDEV-NOTE: Core fetch: dispatch by scheme, return the raw FetchOutcome. git:// connects+fetches
// inside one allow_threads closure (the `Box<dyn Connection>` is !Send) and applies ref updates
// itself; https uses http_fetch (self-applies). A captured progress-callback error is surfaced
// after the transfer returns.
pub(crate) fn fetch_raw(
    py: Python<'_>,
    git_dir: &Path,
    url: &str,
    opts: &FetchOptions,
    username: Option<String>,
    password: Option<String>,
    use_credential_helpers: bool,
    progress: Option<Py<PyAny>>,
) -> PyResult<FetchOutcome> {
    let mut prog = PyProgress::new(progress);
    let outcome = match classify(url)? {
        Scheme::Git => {
            let result = py.allow_threads(|| -> Result<FetchOutcome, grit_lib::error::Error> {
                let mut conn = git_connect(url, 0)?;
                let outcome = grit_lib::fetch::fetch_remote(git_dir, &mut *conn, opts, &mut prog)?;
                apply_ref_updates(git_dir, &outcome)?;
                Ok(outcome)
            });
            if let Some(e) = prog.take_error() {
                return Err(e);
            }
            result.map_err(net_map_err)?
        }
        Scheme::Http => {
            let (clean_url, userinfo) = crate::net_transport::split_userinfo(url);
            let client = crate::net_credentials::build_http_client(
                py,
                Some(git_dir),
                merge_user(username, &userinfo),
                merge_pass(password, &userinfo),
                use_credential_helpers,
            )?;
            let result = py.allow_threads(|| {
                grit_lib::transport::http::http_fetch(&client, git_dir, &clean_url, opts, &mut prog)
            });
            if let Some(e) = prog.take_error() {
                return Err(e);
            }
            result.map_err(net_map_err)?
        }
    };
    Ok(outcome)
}

// AIDEV-NOTE: Credentials precedence: explicit kwargs win, else fall back to URL userinfo.
fn merge_user(explicit: Option<String>, userinfo: &Option<(String, Option<String>)>) -> Option<String> {
    explicit.or_else(|| userinfo.as_ref().map(|(u, _)| u.clone()))
}
fn merge_pass(explicit: Option<String>, userinfo: &Option<(String, Option<String>)>) -> Option<String> {
    explicit.or_else(|| userinfo.as_ref().and_then(|(_, p)| p.clone()))
}

// AIDEV-NOTE: Build FetchOptions from the Python kwargs (default refspec fetches all heads into
// refs/remotes/origin/*). `tags` maps to grit's TagMode.
pub(crate) fn build_fetch_options(
    refspecs: Option<Vec<String>>,
    tags: &str,
    prune: bool,
) -> PyResult<FetchOptions> {
    let tagmode = match tags {
        "none" => TagMode::None,
        "following" => TagMode::Following,
        "all" => TagMode::All,
        other => {
            return Err(pyo3::exceptions::PyValueError::new_err(format!(
                "tags must be 'none', 'following', or 'all' (got {other:?})"
            )))
        }
    };
    let refspecs =
        refspecs.unwrap_or_else(|| vec!["+refs/heads/*:refs/remotes/origin/*".to_owned()]);
    Ok(FetchOptions {
        refspecs,
        tags: tagmode,
        prune,
        ..Default::default()
    })
}

// AIDEV-NOTE: Build a FetchReport (Python objects) from a raw FetchOutcome.
fn build_report(py: Python<'_>, outcome: FetchOutcome) -> PyResult<FetchReport> {
    let mut updates = Vec::with_capacity(outcome.updates.len());
    for u in outcome.updates {
        let ru = RefUpdate {
            remote_ref: u.remote_ref.into_bytes(),
            local_ref: u.local_ref.map(String::into_bytes),
            old_oid: u.old_oid,
            new_oid: u.new_oid,
            mode: update_mode_str(u.mode).to_owned(),
            note: u.note,
        };
        updates.push(Py::new(py, ru)?);
    }
    Ok(FetchReport {
        updates,
        default_branch: outcome.default_branch.map(String::into_bytes),
    })
}

// AIDEV-NOTE: Repository.fetch entry point (called from src/repository.rs).
#[allow(clippy::too_many_arguments)]
pub(crate) fn fetch_method(
    py: Python<'_>,
    repo: &Arc<grit_lib::repo::Repository>,
    url: String,
    refspecs: Option<Vec<String>>,
    tags: &str,
    prune: bool,
    username: Option<String>,
    password: Option<String>,
    use_credential_helpers: bool,
    progress: Option<Py<PyAny>>,
) -> PyResult<FetchReport> {
    let opts = build_fetch_options(refspecs, tags, prune)?;
    let git_dir = repo.git_dir.clone();
    let outcome = fetch_raw(
        py,
        &git_dir,
        &url,
        &opts,
        username,
        password,
        use_credential_helpers,
        progress,
    )?;
    build_report(py, outcome)
}
```

- [ ] **Step 5: Replace the net_credentials placeholder client builder**

In `src/net_credentials.rs`, add a placeholder `build_http_client` (real impl in Task 7) so this task compiles. Add to `src/net_credentials.rs`:

```rust
// AIDEV-NOTE: PLACEHOLDER (replaced in Task 7). Returns the NetworkError until the http client lands,
// keeping the git:// fetch path fully functional in the meantime.
pub(crate) fn build_http_client(
    _py: Python<'_>,
    _git_dir: Option<&std::path::Path>,
    _username: Option<String>,
    _password: Option<String>,
    _use_credential_helpers: bool,
) -> PyResult<grit_lib::transport::http::ureq_client::UreqHttpClient> {
    Err(network_err("https transport not yet available (implemented in a later task)"))
}
```

- [ ] **Step 6: Add `Repository.fetch` + register classes**

In `src/repository.rs`, inside `#[pymethods] impl Repository` (after `checkout_tree`, before the closing brace at line 1019), add:

```rust
    // AIDEV-NOTE: Fetch from `url` into this repo (== `git fetch`). Default refspec fetches all
    // heads into refs/remotes/origin/*. git:// applies the returned ref updates here; https
    // (http_fetch) self-applies. Optional progress= is a callable receiving side-band-2 bytes.
    #[pyo3(signature = (url, refspecs=None, *, tags="following", prune=false,
                        username=None, password=None, use_credential_helpers=true, progress=None))]
    #[allow(clippy::too_many_arguments)]
    fn fetch(
        &self,
        py: Python<'_>,
        url: String,
        refspecs: Option<Vec<String>>,
        tags: &str,
        prune: bool,
        username: Option<String>,
        password: Option<String>,
        use_credential_helpers: bool,
        progress: Option<Py<PyAny>>,
    ) -> PyResult<crate::remote::FetchReport> {
        crate::remote::fetch_method(
            py, &self.inner, url, refspecs, tags, prune, username, password,
            use_credential_helpers, progress,
        )
    }
```

In `src/lib.rs`, add `mod net_progress;` (with the other `mod` lines) and register the two new classes (after `RemoteRef`):

```rust
    m.add_class::<remote::RefUpdate>()?;
    m.add_class::<remote::FetchReport>()?;
```

- [ ] **Step 7: Export + stub**

In `python/pylibgrit/__init__.py`: add `FetchReport,` and `RefUpdate,` to the import block and `__all__`.

In `python/pylibgrit/__init__.pyi`: add both to `__all__`, add the stubs near `RemoteRef`:

```python
@final
class RefUpdate:
    @property
    def remote_ref(self) -> bytes: ...
    @property
    def local_ref(self) -> bytes | None: ...
    @property
    def old_oid(self) -> ObjectId | None: ...
    @property
    def new_oid(self) -> ObjectId | None: ...
    @property
    def mode(self) -> str: ...
    @property
    def note(self) -> str | None: ...

@final
class FetchReport:
    @property
    def updates(self) -> list[RefUpdate]: ...
    @property
    def default_branch(self) -> bytes | None: ...
```

and add `Callable` to the typing import (`from typing import Callable, Iterator, final`), then add the `fetch` method stub inside `class Repository` (after `checkout_tree`):

```python
    def fetch(
        self,
        url: str,
        refspecs: list[str] | None = None,
        *,
        tags: str = "following",
        prune: bool = False,
        username: str | None = None,
        password: str | None = None,
        use_credential_helpers: bool = True,
        progress: Callable[[bytes], None] | None = None,
    ) -> FetchReport: ...
```

- [ ] **Step 8: Build, test, gates, commit**

```bash
uv run maturin develop --uv --locked
uv run pytest tests/test_fetch.py -q
uv run mypy python tests && uv run python -m mypy.stubtest pylibgrit
cargo fmt --check && cargo clippy --all-targets --locked -- -D warnings
uv run ruff format --check && uv run ruff check
git add src/ python/pylibgrit/ tests/test_fetch.py
git commit -m "feat: repo.fetch over git:// (+ FetchReport/RefUpdate, progress bridge)"
```

---

## Task 5: `Repository.clone` over git:// (+ origin config + checkout)

**Files:**
- Modify: `src/remote.rs`, `src/repository.rs`
- Modify: `python/pylibgrit/__init__.pyi`
- Test: `tests/test_clone.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_clone.py`:

```python
"""Repository.clone over git:// produces a git-faithful worktree clone."""

from __future__ import annotations

from pathlib import Path

import pylibgrit
from tests.gitlib import run_git


def _all_refs(repo_dir: Path) -> dict[str, str]:
    # name -> oid; `%(refname) %(objectname)` rows split cleanly on the single space.
    out = run_git(repo_dir, "for-each-ref", "--format=%(refname) %(objectname)").decode()
    refs: dict[str, str] = {}
    for line in out.splitlines():
        name, oid = line.split(" ", 1)
        refs[name] = oid
    return refs


def test_clone_matches_git_clone(git_daemon, tmp_path) -> None:
    ours = tmp_path / "ours"
    theirs = tmp_path / "theirs"
    pylibgrit.Repository.clone(git_daemon.repo_url, ours)
    run_git(tmp_path, "clone", "-q", git_daemon.repo_url, str(theirs))

    # Same HEAD commit, same working files.
    assert run_git(ours, "rev-parse", "HEAD") == run_git(theirs, "rev-parse", "HEAD")
    assert (ours / "a.txt").read_text() == "hello\n"
    assert (ours / "dir" / "b.txt").read_text() == "world\n"

    # Same tracking refs + local branch.
    assert _all_refs(ours).get("refs/remotes/origin/main") == git_daemon.head_oid
    assert _all_refs(ours).get("refs/heads/main") == git_daemon.head_oid


def test_clone_writes_origin_config(git_daemon, tmp_path) -> None:
    ours = tmp_path / "ours"
    pylibgrit.Repository.clone(git_daemon.repo_url, ours)
    url = run_git(ours, "config", "remote.origin.url").decode().strip()
    fetch = run_git(ours, "config", "remote.origin.fetch").decode().strip()
    assert url == git_daemon.repo_url
    assert fetch == "+refs/heads/*:refs/remotes/origin/*"


def test_clone_head_is_on_branch(git_daemon, tmp_path) -> None:
    ours = tmp_path / "ours"
    repo = pylibgrit.Repository.clone(git_daemon.repo_url, ours)
    head = repo.head()
    assert head.is_symbolic
    assert head.symbolic_target == b"refs/heads/main"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_clone.py -q`
Expected: FAIL with `AttributeError: type object 'Repository' has no attribute 'clone'`.

- [ ] **Step 3: Add clone_impl + origin-config writer to `src/remote.rs`**

First widen the top-of-file import to `use crate::error::{net_map_err, network_err};` (clone_impl is the first user of `network_err`). Then append to `src/remote.rs`:

```rust
// AIDEV-NOTE: Write the `[remote "origin"]` stanza into a freshly-init'd repo's .git/config (url +
// the standard fetch refspec), so the result is a git-recognized clone. Uses grit's round-trip
// ConfigFile editor (preserves existing entries). The config file exists post-init.
fn write_origin_config(git_dir: &Path, url: &str) -> Result<(), grit_lib::error::Error> {
    let path = git_dir.join("config");
    let mut cf = grit_lib::config::ConfigFile::from_path(&path, grit_lib::config::ConfigScope::Local)?
        .ok_or_else(|| {
            grit_lib::error::Error::Message(format!("config missing at {}", path.display()))
        })?;
    cf.set("remote.origin.url", url)?;
    cf.set("remote.origin.fetch", "+refs/heads/*:refs/remotes/origin/*")?;
    cf.write()?;
    Ok(())
}

// AIDEV-NOTE: clone = init (non-bare) + origin config + fetch all heads + materialize ONE branch
// (explicit `branch=`, else the remote default) as refs/heads/<name> + HEAD + checkout. Reuses Phase
// A init/refs and Phase B checkout_tree (empty worktree ⇒ overlay == full checkout). Bare clone is
// deferred (spec §1).
#[allow(clippy::too_many_arguments)]
pub(crate) fn clone_impl(
    py: Python<'_>,
    url: String,
    path: std::path::PathBuf,
    branch: Option<String>,
    username: Option<String>,
    password: Option<String>,
    use_credential_helpers: bool,
    progress: Option<Py<PyAny>>,
) -> PyResult<crate::repository::Repository> {
    classify(&url)?; // fail fast on an unsupported scheme before touching the filesystem

    // 1. init a non-bare repo.
    let repo = py
        .allow_threads(|| grit_lib::repo::init_repository(&path, false, "main", None, "files"))
        .map_err(net_map_err)?;
    let repo = Arc::new(repo);
    let git_dir = repo.git_dir.clone();
    let work_tree = repo
        .work_tree
        .clone()
        .ok_or_else(|| network_err("clone target has no work tree (internal error)"))?;

    // 2. origin config.
    py.allow_threads(|| write_origin_config(&git_dir, &url))
        .map_err(net_map_err)?;

    // 3. fetch all heads into refs/remotes/origin/*.
    let opts = build_fetch_options(None, "following", false)?;
    let outcome = fetch_raw(
        py,
        &git_dir,
        &url,
        &opts,
        username,
        password,
        use_credential_helpers,
        progress,
    )?;

    // 4. resolve which branch to check out.
    let name = match branch {
        Some(b) => b.strip_prefix("refs/heads/").unwrap_or(&b).to_owned(),
        None => {
            let db = outcome.default_branch.as_deref().ok_or_else(|| {
                network_err("remote did not advertise a default branch; pass branch=")
            })?;
            db.strip_prefix("refs/heads/").unwrap_or(db).to_owned()
        }
    };
    let local_head = format!("refs/heads/{name}");
    let tracking = format!("refs/remotes/origin/{name}");

    // 5. create local branch = tracking oid; point HEAD at it.
    let tip = py
        .allow_threads(|| grit_lib::refs::resolve_ref(&git_dir, &tracking))
        .map_err(|_| network_err(&format!("branch {name:?} not found on remote")))?;
    py.allow_threads(|| grit_lib::refs::write_ref(&git_dir, &local_head, &tip))
        .map_err(net_map_err)?;
    py.allow_threads(|| grit_lib::refs::write_symbolic_ref(&git_dir, "HEAD", &local_head))
        .map_err(net_map_err)?;

    // 6. checkout the tip commit's tree (overlay == full checkout into the empty worktree).
    let tree_oid = py
        .allow_threads(|| -> Result<grit_lib::objects::ObjectId, grit_lib::error::Error> {
            let obj = repo.odb.read(&tip)?;
            let commit = grit_lib::objects::parse_commit(&obj.data)?;
            Ok(commit.tree)
        })
        .map_err(net_map_err)?;
    py.allow_threads(|| crate::checkout::checkout_tree(&repo, &work_tree, &tree_oid, false, true))
        .map_err(crate::checkout::to_pyerr)?;

    Ok(crate::repository::Repository { inner: repo })
}
```

- [ ] **Step 4: Add the `Repository.clone` staticmethod**

In `src/repository.rs`, inside `#[pymethods] impl Repository`, after `init` (line 118), add:

```rust
    // AIDEV-NOTE: Clone `url` into `path` (== `git clone`, worktree only). Assembles init + origin
    // config + fetch + branch/HEAD + checkout (grit has no clone porcelain). bare/shallow deferred
    // (spec §1). Returns the opened Repository.
    #[staticmethod]
    #[pyo3(signature = (url, path, *, branch=None, username=None, password=None,
                        use_credential_helpers=true, progress=None))]
    #[allow(clippy::too_many_arguments)]
    fn clone(
        py: Python<'_>,
        url: String,
        path: &Bound<'_, PyAny>,
        branch: Option<String>,
        username: Option<String>,
        password: Option<String>,
        use_credential_helpers: bool,
        progress: Option<Py<PyAny>>,
    ) -> PyResult<Self> {
        let path = extract_path(path)?;
        crate::remote::clone_impl(
            py, url, path, branch, username, password, use_credential_helpers, progress,
        )
    }
```

- [ ] **Step 5: Add the `clone` stub**

In `python/pylibgrit/__init__.pyi`, inside `class Repository`, after the `open` staticmethod (line 298), add:

```python
    @staticmethod
    def clone(
        url: str,
        path: str | bytes | os.PathLike[str],
        *,
        branch: str | None = None,
        username: str | None = None,
        password: str | None = None,
        use_credential_helpers: bool = True,
        progress: Callable[[bytes], None] | None = None,
    ) -> Repository: ...
```

- [ ] **Step 6: Build, test, gates, commit**

```bash
uv run maturin develop --uv --locked
uv run pytest tests/test_clone.py -q
uv run mypy python tests && uv run python -m mypy.stubtest pylibgrit
cargo fmt --check && cargo clippy --all-targets --locked -- -D warnings
uv run ruff format --check && uv run ruff check
git add src/ python/pylibgrit/ tests/test_clone.py
git commit -m "feat: Repository.clone over git:// (origin config + checkout)"
```

---

## Task 6: Progress callback wiring (git://)

**Files:**
- Test: `tests/test_progress.py` (create)

(No new production code — Task 4's `PyProgress` is already wired into `fetch_raw`, which both `fetch` and `clone` call. This task adds behavioral coverage and confirms the callback + error-capture paths.)

- [ ] **Step 1: Write the failing test**

Create `tests/test_progress.py`:

```python
"""The optional progress callback is invoked with bytes and its errors propagate."""

from __future__ import annotations

import pytest

import pylibgrit


def test_progress_callback_receives_bytes_and_clone_succeeds(git_daemon, tmp_path) -> None:
    chunks: list[bytes] = []
    repo = pylibgrit.Repository.clone(
        git_daemon.repo_url, tmp_path / "ours", progress=chunks.append
    )
    # Clone still works with a callback attached...
    assert repo.resolve("HEAD").hex == git_daemon.head_oid
    # ...and any chunks delivered are bytes (a tiny transfer may deliver zero — server-dependent).
    assert all(isinstance(c, bytes) for c in chunks)


def test_progress_callback_exception_propagates(git_daemon, tmp_path) -> None:
    class Boom(Exception):
        pass

    def cb(_data: bytes) -> None:
        raise Boom("stop")

    # If the server emits at least one side-band chunk, the callback raises and the fetch fails with
    # our exception. If it emits none, the fetch succeeds — both are acceptable; assert we never get
    # a DIFFERENT error type.
    try:
        pylibgrit.Repository.clone(git_daemon.repo_url, tmp_path / "ours", progress=cb)
    except Boom:
        pass
```

- [ ] **Step 2: Run it to verify it passes (already wired)**

Run: `uv run pytest tests/test_progress.py -q`
Expected: PASS (or SKIP without `git daemon`). If `test_progress_callback_receives_bytes_and_clone_succeeds` fails because the callback was never accepted/typed, fix the `progress` plumbing in Task 4/5.

- [ ] **Step 3: Gates and commit**

```bash
uv run mypy python tests && uv run ruff format --check && uv run ruff check
git add tests/test_progress.py
git commit -m "test: progress callback over git:// (bytes + error propagation)"
```

---

## Task 7: HTTPS transport (anonymous) + `git http-backend` fixture

**Files:**
- Modify: `src/net_credentials.rs`
- Create: `tests/githttp.py`
- Modify: `tests/conftest.py`
- Test: `tests/test_http_clone.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_http_clone.py`:

```python
"""clone/fetch/ls_remote over anonymous smart-HTTP (git http-backend)."""

from __future__ import annotations

import pylibgrit


def test_http_ls_remote(http_server) -> None:
    refs = {r.name for r in pylibgrit.ls_remote(http_server.repo_url)}
    assert b"refs/heads/main" in refs


def test_http_clone(http_server, tmp_path) -> None:
    repo = pylibgrit.Repository.clone(http_server.repo_url, tmp_path / "ours")
    assert repo.resolve("HEAD").hex == http_server.head_oid
    assert (tmp_path / "ours" / "a.txt").read_text() == "hello\n"


def test_http_fetch(http_server, tmp_path) -> None:
    repo = pylibgrit.Repository.init(tmp_path / "dst")
    report = repo.fetch(http_server.repo_url)
    assert {u.remote_ref for u in report.updates} >= {b"refs/heads/main"}
    assert repo.resolve("refs/remotes/origin/main").hex == http_server.head_oid
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_http_clone.py -q`
Expected: FAIL with `fixture 'http_server' not found`.

- [ ] **Step 3: Implement the real https client builder**

Replace the **entire** `src/net_credentials.rs` (both placeholders) with the real implementation below:

```rust
//! HTTPS credential wiring: explicit/userinfo creds chained to git's credential helpers, plus the
//! UreqHttpClient builder and the http(s) ref-advertisement reader for ls_remote.

use std::path::Path;

use grit_lib::config::ConfigSet;
use grit_lib::credentials::{Credential, CredentialProvider, HelperCredentialProvider};
use grit_lib::transport::http::ureq_client::UreqHttpClient;
use grit_lib::transport::{Connection, ConnectOptions, Service, Transport};
use pyo3::prelude::*;

use crate::error::net_map_err;

// AIDEV-NOTE: A CredentialProvider that returns fixed username/password (from explicit kwargs or URL
// userinfo). `fill` supplies only the fields the input lacks; if still incomplete and a helper is
// present, it delegates to the helper (so a user's configured `credential.helper` fills the rest).
// approve/reject delegate to the helper (a successful login may be stored), else no-op. We build the
// Credential explicitly (not via Clone) so this does not depend on `Credential: Clone`.
pub(crate) struct StaticCredentialProvider {
    username: Option<String>,
    password: Option<String>,
    helper: Option<HelperCredentialProvider>,
}

impl StaticCredentialProvider {
    pub(crate) fn new(
        username: Option<String>,
        password: Option<String>,
        helper: Option<HelperCredentialProvider>,
    ) -> Self {
        Self { username, password, helper }
    }
}

impl CredentialProvider for StaticCredentialProvider {
    fn fill(&self, input: &Credential) -> grit_lib::error::Result<Credential> {
        let cred = Credential {
            protocol: input.protocol.clone(),
            host: input.host.clone(),
            path: input.path.clone(),
            username: input.username.clone().or_else(|| self.username.clone()),
            password: input.password.clone().or_else(|| self.password.clone()),
            url: input.url.clone(),
            extra: input.extra.clone(),
        };
        if (cred.username.is_none() || cred.password.is_none()) && self.helper.is_some() {
            return self.helper.as_ref().unwrap().fill(&cred);
        }
        Ok(cred)
    }
    fn approve(&self, cred: &Credential) -> grit_lib::error::Result<()> {
        match &self.helper {
            Some(h) => h.approve(cred),
            None => Ok(()),
        }
    }
    fn reject(&self, cred: &Credential) -> grit_lib::error::Result<()> {
        match &self.helper {
            Some(h) => h.reject(cred),
            None => Ok(()),
        }
    }
}

// AIDEV-NOTE: Build a UreqHttpClient configured from the repo's cascaded git config (proxy, cookies,
// extra headers via from_config), with our credential provider attached. `git_dir = None` loads
// global/system config only (ls_remote without a repo). Helpers are wired only when requested.
pub(crate) fn build_http_client(
    py: Python<'_>,
    git_dir: Option<&Path>,
    username: Option<String>,
    password: Option<String>,
    use_credential_helpers: bool,
) -> PyResult<UreqHttpClient> {
    let (client, helper) = py
        .allow_threads(|| -> Result<(UreqHttpClient, Option<HelperCredentialProvider>), grit_lib::error::Error> {
            let config = ConfigSet::load(git_dir, true)?;
            let client = UreqHttpClient::from_config(&config)?;
            let helper = if use_credential_helpers {
                Some(HelperCredentialProvider::new(ConfigSet::load(git_dir, true)?))
            } else {
                None
            };
            Ok((client, helper))
        })
        .map_err(net_map_err)?;
    let provider = StaticCredentialProvider::new(username, password, helper);
    Ok(client.with_credential_provider(Box::new(provider)))
}

// AIDEV-NOTE: Read the http(s) v0/v1 ref advertisement for ls_remote. Builds the client (with creds),
// connects via SmartHttpTransport forcing protocol v1, and copies the advertised refs + HEAD symref
// out before the `!Send` connection is dropped. Userinfo is split off the URL here too.
pub(crate) fn http_advertisement(
    py: Python<'_>,
    url: &str,
    username: Option<String>,
    password: Option<String>,
    use_credential_helpers: bool,
) -> PyResult<(Vec<(String, grit_lib::objects::ObjectId)>, Option<String>)> {
    let (clean_url, userinfo) = crate::net_transport::split_userinfo(url);
    let user = username.or_else(|| userinfo.as_ref().map(|(u, _)| u.clone()));
    let pass = password.or_else(|| userinfo.as_ref().and_then(|(_, p)| p.clone()));
    let client = build_http_client(py, None, user, pass, use_credential_helpers)?;
    py.allow_threads(|| -> Result<_, grit_lib::error::Error> {
        let transport = grit_lib::transport::http::SmartHttpTransport::new(client);
        let opts = ConnectOptions { protocol_version: 1, server_options: Vec::new() };
        let conn = transport.connect(&clean_url, Service::UploadPack, &opts)?;
        Ok((conn.advertised_refs().to_vec(), conn.head_symref().map(str::to_owned)))
    })
    .map_err(net_map_err)
}
```

This fully replaces the Task 3/4 placeholders (and their `network_err` import). `fetch_raw` (Task 4) and `ls_remote` (Task 3) already call `build_http_client`/`http_advertisement`, so the https paths light up with no caller changes.

- [ ] **Step 4: Implement the git-http-backend server**

Create `tests/githttp.py`:

```python
"""A minimal smart-HTTP server backed by `git http-backend`, for hermetic https tests.

AIDEV-NOTE: Python 3.13 removed CGIHTTPRequestHandler, so we run `git http-backend` ourselves as a
subprocess per request, translating HTTP <-> CGI. Supports optional HTTP Basic auth. Threaded so the
smart-HTTP multi-request dance does not deadlock. Listens on 127.0.0.1; not for production use.
"""

from __future__ import annotations

import base64
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def make_handler(project_root: Path, env: dict[str, str], auth: tuple[str, str] | None):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _denied(self) -> None:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="git"')
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _check_auth(self) -> bool:
            if auth is None:
                return True
            header = self.headers.get("Authorization", "")
            if not header.startswith("Basic "):
                return False
            try:
                user, _, pw = base64.b64decode(header[6:]).decode().partition(":")
            except Exception:
                return False
            return (user, pw) == auth

        def _run_backend(self, body: bytes) -> None:
            if not self._check_auth():
                self._denied()
                return
            path, _, query = self.path.partition("?")
            cgi_env = dict(env)
            cgi_env.update(
                {
                    "GIT_PROJECT_ROOT": str(project_root),
                    "GIT_HTTP_EXPORT_ALL": "1",
                    "REQUEST_METHOD": self.command,
                    "PATH_INFO": path,
                    "QUERY_STRING": query,
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                    "CONTENT_LENGTH": str(len(body)),
                    "REMOTE_USER": auth[0] if auth else "",
                    "REMOTE_ADDR": "127.0.0.1",
                    "GIT_PROTOCOL": self.headers.get("Git-Protocol", ""),
                }
            )
            proc = subprocess.run(
                ["git", "http-backend"],
                input=body,
                env=cgi_env,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            raw = proc.stdout
            head, _, payload = raw.partition(b"\r\n\r\n")
            status = 200
            headers: list[tuple[str, str]] = []
            for line in head.split(b"\r\n"):
                if not line:
                    continue
                key, _, value = line.decode("latin-1").partition(":")
                value = value.strip()
                if key.lower() == "status":
                    status = int(value.split()[0])
                else:
                    headers.append((key, value))
            self.send_response(status)
            for key, value in headers:
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802
            self._run_backend(b"")

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            self._run_backend(self.rfile.read(length))

        def log_message(self, *_args) -> None:
            pass

    return Handler


def serve(project_root: Path, env: dict[str, str], auth: tuple[str, str] | None) -> ThreadingHTTPServer:
    handler = make_handler(project_root, env, auth)
    return ThreadingHTTPServer(("127.0.0.1", 0), handler)
```

- [ ] **Step 5: Add the `http_server` fixture**

Append to `tests/conftest.py`:

```python
import threading

from tests import githttp


def _make_http_server(tmp_path: Path, git_env: dict[str, str], auth: tuple[str, str] | None):
    """Seed a bare server repo and serve it over smart-HTTP. Returns (namespace, shutdown)."""
    base = tmp_path / "httpsrv"
    base.mkdir()
    src = tmp_path / "httpsrc"
    src.mkdir()
    _git(src, git_env, "init", "-q", "-b", "main")
    (src / "a.txt").write_text("hello\n")
    _git(src, git_env, "add", "-A")
    _git(src, git_env, "commit", "-q", "-m", "initial commit")
    server = base / "server.git"
    _git(tmp_path, git_env, "clone", "-q", "--bare", str(src), str(server))
    head_oid = run_git(src, "rev-parse", "HEAD").decode().strip()

    try:
        httpd = githttp.serve(base, git_env, auth)
    except OSError:
        pytest.skip("could not start http server")
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    ns = SimpleNamespace(
        repo_url=f"http://127.0.0.1:{port}/server.git",
        head_oid=head_oid,
        server_path=server,
    )

    def shutdown() -> None:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)

    return ns, shutdown


@pytest.fixture
def http_server(tmp_path: Path, git_env: dict[str, str]):
    """Anonymous smart-HTTP server (git http-backend). Skips if git http-backend is unavailable."""
    if subprocess.run(["git", "http-backend"], env=git_env, input=b"",
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode not in (0, 1, 2):
        pytest.skip("git http-backend unavailable")
    ns, shutdown = _make_http_server(tmp_path, git_env, auth=None)
    try:
        yield ns
    finally:
        shutdown()
```

- [ ] **Step 6: Build, test, gates, commit**

```bash
uv run maturin develop --uv --locked
uv run pytest tests/test_http_clone.py -q
uv run mypy python tests && uv run python -m mypy.stubtest pylibgrit
cargo fmt --check && cargo clippy --all-targets --locked -- -D warnings
uv run ruff format --check && uv run ruff check
git add src/net_credentials.rs tests/githttp.py tests/conftest.py tests/test_http_clone.py
git commit -m "feat: anonymous https transport + git http-backend test fixture"
```

---

## Task 8: HTTPS credentials (auth) + AuthenticationError

**Files:**
- Modify: `tests/conftest.py` (auth fixture)
- Test: `tests/test_http_auth.py` (create)

(Production credential code already landed in Task 7's `StaticCredentialProvider` + `build_http_client`, which `fetch_raw`/`http_advertisement` use. This task adds an authenticating server and verifies every credential entry path.)

- [ ] **Step 1: Write the failing test**

Create `tests/test_http_auth.py`:

```python
"""Authenticated smart-HTTP: kwargs, URL userinfo, and rejection -> AuthenticationError."""

from __future__ import annotations

import pytest

import pylibgrit

USER, PW = "alice", "s3cret"


def test_auth_clone_with_kwargs(http_auth_server, tmp_path) -> None:
    repo = pylibgrit.Repository.clone(
        http_auth_server.repo_url, tmp_path / "ours",
        username=USER, password=PW, use_credential_helpers=False,
    )
    assert repo.resolve("HEAD").hex == http_auth_server.head_oid


def test_auth_clone_with_url_userinfo(http_auth_server, tmp_path) -> None:
    url = http_auth_server.repo_url.replace("http://", f"http://{USER}:{PW}@")
    repo = pylibgrit.Repository.clone(url, tmp_path / "ours", use_credential_helpers=False)
    assert repo.resolve("HEAD").hex == http_auth_server.head_oid


def test_auth_missing_credentials_raises(http_auth_server, tmp_path) -> None:
    with pytest.raises(pylibgrit.AuthenticationError):
        pylibgrit.Repository.clone(
            http_auth_server.repo_url, tmp_path / "ours", use_credential_helpers=False
        )


def test_auth_wrong_credentials_raises(http_auth_server) -> None:
    with pytest.raises(pylibgrit.AuthenticationError):
        pylibgrit.ls_remote(
            http_auth_server.repo_url, username=USER, password="wrong",
            use_credential_helpers=False,
        )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_http_auth.py -q`
Expected: FAIL with `fixture 'http_auth_server' not found`.

- [ ] **Step 3: Add the authenticating fixture**

Append to `tests/conftest.py`:

```python
@pytest.fixture
def http_auth_server(tmp_path: Path, git_env: dict[str, str]):
    """Basic-auth smart-HTTP server (user 'alice' / pass 's3cret'). Skips if unavailable."""
    if subprocess.run(["git", "http-backend"], env=git_env, input=b"",
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode not in (0, 1, 2):
        pytest.skip("git http-backend unavailable")
    ns, shutdown = _make_http_server(tmp_path, git_env, auth=("alice", "s3cret"))
    try:
        yield ns
    finally:
        shutdown()
```

- [ ] **Step 4: Build, test, gates, commit**

```bash
uv run maturin develop --uv --locked
uv run pytest tests/test_http_auth.py -q
uv run mypy python tests && uv run python -m mypy.stubtest pylibgrit
cargo fmt --check && cargo clippy --all-targets --locked -- -D warnings
uv run ruff format --check && uv run ruff check
git add tests/conftest.py tests/test_http_auth.py
git commit -m "test: https Basic-auth (kwargs, userinfo, AuthenticationError)"
```

---

## Task 9: Docs, CHANGELOG, and 0.3.0 release staging

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `Cargo.toml`, `Cargo.lock`
- Test: full suite + gates

- [ ] **Step 1: Add a "Networking" section to README.md**

After the existing "Writing" section, add a "Networking (clone / fetch / ls-remote)" section documenting:
- `pylibgrit.ls_remote(url, *, username=, password=, use_credential_helpers=, heads=, tags=)` → `list[RemoteRef]`.
- `Repository.clone(url, path, *, branch=, username=, password=, use_credential_helpers=, progress=)`.
- `repo.fetch(url, refspecs=None, *, tags=, prune=, username=, password=, use_credential_helpers=, progress=)` → `FetchReport`.
- Supported schemes (git://, https; ssh/shallow/push not yet); https bundled (rustls).
- A short runnable example:

````markdown
```python
import pylibgrit

# Clone a public repo over https.
repo = pylibgrit.Repository.clone("https://github.com/octocat/Hello-World.git", "/tmp/hello")
print(repo.head().peel().hex)

# List remote refs without cloning.
for ref in pylibgrit.ls_remote("https://github.com/octocat/Hello-World.git", heads=True):
    print(ref.oid.hex, ref.name.decode())

# Authenticated fetch (token via kwarg or https://<token>@host/...).
report = repo.fetch("https://github.com/me/private.git", username="x", password="TOKEN")
for u in report.updates:
    print(u.mode, u.remote_ref.decode())
```
````

- [ ] **Step 2: Add a CHANGELOG.md entry**

Add a `## 0.3.0` section above `## 0.2.0` summarizing: read-path networking (ls_remote, fetch, clone) over git:// and https; bundled http-ureq (rustls); credentials (explicit/userinfo/helpers); optional progress callback; new `RemoteRef`/`RefUpdate`/`FetchReport` types and `NetworkError`/`AuthenticationError`; deferred push/ssh/shallow/bare.

- [ ] **Step 3: Bump the version to 0.3.0**

In `Cargo.toml`, change `version = "0.2.0"` to `version = "0.3.0"`. Then refresh the lock:

```bash
cargo update -p pylibgrit --precise 0.3.0 2>/dev/null || cargo build
```
(Or simply run `uv run maturin develop --uv --locked` which updates `Cargo.lock`'s pylibgrit version.)

- [ ] **Step 4: Full suite + all gates**

```bash
uv run maturin develop --uv --locked
uv run pytest -q
uv run mypy python tests && uv run python -m mypy.stubtest pylibgrit
cargo fmt --check && cargo clippy --all-targets --locked -- -D warnings
uv run ruff format --check && uv run ruff check
```
Expected: entire suite green (network tests skip cleanly if `git daemon`/`git http-backend` are unavailable).

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md Cargo.toml Cargo.lock
git commit -m "docs: document read-path networking; stage 0.3.0"
```

---

## Definition of done

- `ls_remote`, `repo.fetch`, and `Repository.clone` work over git:// and https; ssh/push/shallow/bare cleanly absent.
- git:// tests parity-checked against `git clone`/`git ls-remote`; https tests cover anonymous + Basic auth; all skip-if-unavailable.
- `http-ureq` bundled by default; `NetworkError`/`AuthenticationError` raised appropriately.
- All 7 gates green; stub matches runtime with no allowlist; version staged at 0.3.0.
- Deferred (future Phase D / follow-ups): push, ssh, shallow/depth, bare/mirror clone, FETCH_HEAD, structured progress counters, `insteadOf`/submodules.
