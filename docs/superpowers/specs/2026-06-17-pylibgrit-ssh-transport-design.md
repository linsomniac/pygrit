# pylibgrit SSH Transport — Design

**Status:** Approved (2026-06-17)

**Goal:** Add SSH as a fourth transport (alongside git:// and http(s)://) for all
network operations — `ls_remote`, `fetch`, `clone`, and `push` — supporting
`ssh://`, `git+ssh://`, and scp-style (`user@host:path`) URLs. Staged as release
**0.5.0**.

---

## 1. Background & key enabling fact

grit-lib 0.4.1 already ships a complete SSH transport in `src/transport.rs`:

- **`SshTransport`** spawns an `ssh` subprocess
  (`ssh [-p port] <host> git-upload-pack '<path>'`, or `git-receive-pack` for
  push) and exposes the child's stdin/stdout as a `Box<dyn Connection>` — the
  **same `Connection` trait** that the git:// transport produces and that
  `fetch_remote` / `push_remote` / the advertisement reader already consume.
- **`is_ssh_url(url) -> bool`** recognizes `ssh://`, `git+ssh://`, and scp-style
  `host:path` (a faithful port of Git's `connect.c` `url_is_local_not_ssh`).
- **`parse_ssh_url(url) -> SshUrl { ssh_host, path, scp_style, port }`** — Git's
  URL parsing (bracketed IPv6, `user@host:port`, `~`-home tweak, percent-decode).
- **Pluggable ssh invocation** via the `ssh_command: SshCommand` field:
  - `SshCommand::Auto` (default, `SshTransport::new()`): resolves
    `$GIT_SSH_COMMAND` (a shell command line run via `sh -c`), else `$GIT_SSH`
    (a program, no shell), else the `ssh` program — matching Git's precedence.
  - `SshTransport::with_shell_command(cmd)`: pin a shell command line (`sh -c`).
  - `SshTransport::with_program(prog)`: pin a bare program (direct argv).

Because SSH yields the same `Connection` as git://, **every downstream piece is
reused unchanged**: fetch negotiation, push (`build_pack` + `report-status`
parsing), advertisement parsing, and the `FetchReport` / `PushReport` mapping.
Adding SSH is therefore almost entirely *wiring*: each `match classify(url)` site
gains a `Scheme::Ssh` arm that mirrors its existing `Scheme::Git` arm.

**Consequence for the FFI pattern:** `SshConnection` holds a `Child` + pipes, so
it is `!Send` — exactly like the git:// `Box<dyn Connection>`. It MUST be
constructed and consumed inside **one** `py.allow_threads(...)` closure (never
crossing the GIL-release boundary), identical to the existing git:// arms.

---

## 2. Scope

**In scope (all four operations over SSH, for parity with git:// + https):**

- `ls_remote(url, …, ssh_command=None)`
- `Repository.fetch(url, …, ssh_command=None)`
- `Repository.clone(url, path, …, ssh_command=None)`
- `Repository.push(url, refspecs, …, ssh_command=None)`

**URL forms:** `ssh://[user@]host[:port]/path`, `git+ssh://…`, and scp-style
`[user@]host:path` — all via grit's `is_ssh_url` / `parse_ssh_url`.

**Out of scope (deferred, each its own future cycle if wanted):**

- Real-sshd integration tests (the shim fully exercises our wiring; a real sshd
  would mostly test ssh itself).
- SSH signed push, plink/PuTTY variant detection, the `ssh -G` probe.
- An argv-list form of `ssh_command` (a single shell-command string already
  covers `GIT_SSH_COMMAND` semantics; YAGNI).
- file:// and bare local-path transports (still unsupported — they fall through
  `classify` to the existing "unsupported transport" `NetworkError`).

---

## 3. Authentication & credentials model

SSH authentication (keys, ssh-agent, `known_hosts`, `~/.ssh/config`) is entirely
the **ssh subprocess's** responsibility. pylibgrit never handles ssh auth. The
remote user is carried in the URL (`ssh://user@host/…` or `user@host:…`).

The http-only `username=` / `password=` kwargs do **not** apply to ssh URLs.
Passing either with an ssh URL **raises `ValueError`** (fail loud) with a message
pointing the user to put `user@` in the URL and rely on ssh keys/agent. The
`use_credential_helpers` kwarg (default `True`) is http-only and is silently
ignored for ssh URLs — rejecting its default would break every ssh call, and it
carries no secret.

The guard fires at the **public entry point**, before any filesystem or network
side effect — in particular `clone` checks it at its fail-fast `classify`, before
it inits the target repo directory.

---

## 4. Components (file by file)

### `src/net_transport.rs`

- Add `Scheme::Ssh` to the `Scheme` enum.
- `classify(url)`: dispatch order is `git://` → `http(s)://` →
  `grit_lib::transport::is_ssh_url(url)` → else the existing "unsupported
  transport" `NetworkError`. (Order matters only in that the explicit-scheme
  checks run first; `is_ssh_url` returns false for any `://` URL that is not
  `ssh://`/`git+ssh://`, and false for local paths.)
- `build_ssh_transport(ssh_command: Option<&str>) -> SshTransport`: `Some(cmd)` →
  `SshTransport::with_shell_command(cmd)`; `None` → `SshTransport::new()` (Auto).
- `ssh_connect(url, protocol_version: u8, ssh_command: Option<&str>) ->
  Result<Box<dyn Connection>>`: `build_ssh_transport(...).connect(url,
  Service::UploadPack, &ConnectOptions { protocol_version, server_options:
  Vec::new() })`. Mirrors `git_connect`. The returned connection is `!Send`.
- `ssh_connect_receive(url, ssh_command: Option<&str>) ->
  Result<Box<dyn Connection>>`: same but `Service::ReceivePack` and
  `protocol_version: 0` (grit's push rejects v2). Mirrors `git_connect_receive`.
- `reject_creds_for_ssh(username: &Option<String>, password: &Option<String>) ->
  PyResult<()>`: returns `Err(PyValueError)` if either is `Some`, with the
  guidance message; `Ok(())` otherwise.

### `src/remote.rs`

- A read-advertisement path for ssh. The existing `read_advertisement(url)`
  hardcodes `git_connect(url, 1)`; add a sibling `read_advertisement_ssh(url,
  ssh_command)` using `ssh_connect(url, 1, ssh_command)` (read
  `advertised_refs()` + `head_symref()` exactly as the git path does).
- `ls_remote` (`#[pyfunction]`): add `ssh_command: Option<String>` to the
  signature; call `reject_creds_for_ssh` after `classify`; add the `Scheme::Ssh`
  arm: `py.allow_threads(|| read_advertisement_ssh(&url,
  ssh_command.as_deref())).map_err(net_map_err)?`.
- `fetch_raw`: add `ssh_command: Option<String>` param; add the `Scheme::Ssh`
  arm mirroring the `Scheme::Git` arm —
  `py.allow_threads(|| { let mut conn = ssh_connect(url, 0,
  ssh_command.as_deref())?; let mut np = NoProgress;
  fetch_remote(git_dir, &mut *conn, opts, &mut np) }).map_err(net_map_err)?`.
  (No fetch progress over ssh either — grit forces `no-progress` on the
  upload-pack request regardless of transport; the `progress=` param was already
  dropped from fetch in Phase C.)
- `fetch_method`: add `ssh_command` param; call `reject_creds_for_ssh`; thread
  `ssh_command` into `fetch_raw`.
- `clone_impl`: add `ssh_command` param; call `reject_creds_for_ssh` at the
  fail-fast `classify` (before init); thread `ssh_command` into the internal
  `fetch_raw` call. The origin URL stored by `write_origin_config` is the ssh URL
  verbatim. All post-fetch steps (branch resolution, ref/HEAD writes, checkout)
  are transport-agnostic and unchanged.

### `src/push.rs`

- `push_method`: add `ssh_command: Option<String>` param; call
  `reject_creds_for_ssh` after `classify`; add the `Scheme::Ssh` arm mirroring
  the `Scheme::Git` arm —
  `py.allow_threads(|| { let mut conn = ssh_connect_receive(&url,
  ssh_command.as_deref())?; push_remote(&git_dir, &mut *conn, &specs, &opts,
  &mut prog) })`, then the same `prog.take_error()` re-raise and
  `result.map_err(net_map_err)?`. Push progress (remote hook / side-band-2
  output) flows to the callback exactly as for git:// — ssh demuxes side-band the
  same way. The empty-refspecs short-circuit (from the polish pass) still applies
  before any connection.

### `src/repository.rs`

- `clone`, `fetch`, `push` methods: add `ssh_command=None` to each `#[pyo3(signature
  = …)]` and forward it to `clone_impl` / `fetch_method` / `push_method`.

### `python/pylibgrit/__init__.pyi` (type stubs)

- Add `ssh_command: str | None = None` to the stubs for `ls_remote`,
  `Repository.clone`, `Repository.fetch`, and `Repository.push`. (stubtest runs
  with no allowlist, so the stubs must match exactly.)

---

## 5. Protocol versions (matching the git:// transport)

| Operation  | protocol_version | Service       | Rationale                                   |
|------------|------------------|---------------|---------------------------------------------|
| ls_remote  | 1                | UploadPack    | force a v0/v1 ref advertisement to read refs |
| fetch/clone| 0                | UploadPack    | let the server pick; v0 advertisement parses |
| push       | 0                | ReceivePack   | grit's push rejects v2                       |

For ssh, `protocol_version > 0` causes grit to export `GIT_PROTOCOL=version=N`
into the ssh process environment (OpenSSH forwards it). v0 leaves it unset.

---

## 6. Error handling

All failures surface through grit's `Error` → `net_map_err` →
`NetworkError` / `AuthenticationError`, the same model as Phases C/D:

- **ssh spawn failure** (e.g. `ssh` not found): grit returns
  `Error::Message("failed to spawn ssh for <host>: …")` → `NetworkError`.
- **malformed ssh URL** (empty host/path, host starting with `-`, bad
  percent-escape): `parse_ssh_url` errors inside `connect` → `NetworkError`.
- **remote/auth failure** (ssh exits non-zero, permission denied): the
  advertisement read fails → `NetworkError`. (ssh prints its own diagnostics to
  inherited stderr.)
- **`username=`/`password=` with an ssh URL**: `ValueError` (Section 3), raised
  before any side effect.

Push rejections remain **data** (`PushReport.results[*].status`), not raised —
unchanged from Phase D.

---

## 7. Testing — hermetic fake-ssh shim

The shim approach exercises the full binding path (URL classification, transport
construction, connect, advertisement read, fetch/push over the `Connection`,
report mapping) **without a real sshd** — it needs only `sh` and `git`, both
always present, so the tests RUN (never skip).

**Fixture (`tests/conftest.py`), e.g. `ssh_server`:**

1. Build a bare "server" repo with one commit and a local non-bare pusher clone
   (same shape as `git_daemon_push`: `server_path`, `local_path`, `base_oid`).
2. Write an executable POSIX shim script to `tmp_path`. grit (via
   `with_shell_command`) runs `sh -c "<shim> [-p <port>] <host> <remote_cmd>"`,
   so the shim receives the host (and optional `-p port`) followed by the remote
   git command as its **last** argument. The shim ignores everything but the last
   arg and execs it locally:

   ```sh
   #!/bin/sh
   # Fake ssh for hermetic tests: ignore host/-p options; run the remote git
   # command (always the last argument, e.g. git-upload-pack '/abs/repo.git')
   # locally against the bare repo.
   for last; do :; done
   exec sh -c "$last"
   ```

3. Yield a namespace: `repo_url = f"ssh://localhost{server_path}"` (absolute
   path), `ssh_command = <shim path>`, plus `server_path`, `local_path`, `env`.

**Tests:**

- `ls_remote(url, ssh_command=shim)` → advertised refs match the server oracle.
- `clone(url, dest, ssh_command=shim)` → worktree + refs match; origin URL is the
  ssh URL.
- fetch: advance the server, `fetch(url, ssh_command=shim)` → tracking refs
  updated.
- push: advance `local_path`, `push(url, ["main"], ssh_command=shim)` → server
  refs updated (oracle = `git rev-parse` in `server_path`).
- one **scp-style** URL test (`localhost:{abs_path}`) proving `parse_ssh_url`'s
  scp branch works through the binding.
- **creds rejection**: `ValueError` when `username=`/`password=` is passed with an
  ssh URL — on ls_remote, fetch, clone, and push.
- one **Auto** test: set `GIT_SSH_COMMAND=<shim>` in the env and call with
  `ssh_command=None`, exercising the env-resolution branch.

(The shim handles both `git-upload-pack` and `git-receive-pack` — push to a local
bare repo via `git-receive-pack` needs no daemon `--enable` flag.)

---

## 8. Quality gates (all must stay green)

`pytest -q`; `mypy python tests`; `python -m mypy.stubtest pylibgrit` (no
allowlist); `cargo fmt --check`; `cargo clippy --all-targets --locked -- -D
warnings`; `ruff format --check`; `ruff check`. Build with
`uv run maturin develop --uv --locked` before pytest.

---

## 9. Release 0.5.0

Bump version (`Cargo.toml` + `Cargo.lock`), add a README "SSH" subsection, and a
`CHANGELOG.md [0.5.0]` entry. Publishing (after merge + push) follows the same
OIDC `release.yml` flow as 0.2.0–0.4.0: a published GitHub Release `v0.5.0`.
