# pygrit — Python bindings for grit-lib (design)

- **Date:** 2026-06-13
- **Status:** Approved (design); ready for implementation planning
- **Author:** Sean Reifschneider (with Claude Code)

## 1. Summary

`pygrit` provides native Python bindings to [`grit-lib`](https://crates.io/crates/grit-lib),
the core Rust library of [gitbutlerapp/grit](https://github.com/gitbutlerapp/grit)
(a from-scratch reimplementation of Git in Rust). The bindings are built with
**PyO3** and packaged as a wheel with **maturin**. The first version is a
**thin, 1:1 mapping** of grit-lib's **read-core** API and is tested with pytest
using a combination of differential ("oracle") tests against the real `git` CLI
and a set of mirrored grit-lib unit tests.

## 2. Goals and non-goals

### Goals (MVP / read-core)

- Open or discover a repository.
- Read objects by id: commit, tree, blob, tag.
- List and resolve references.
- Basic revision walk / log.
- Produce diffs (tree/content).
- Read configuration.
- Robust, well-isolated, well-tested code with type stubs for mypy.

### Non-goals (deferred to later milestones)

- Index / staging mutation.
- Creating commits / writing objects.
- Merge, rebase, cherry-pick.
- Networking: fetch / push / transport.
- Blame, notes, reflog editing, hooks.

## 3. Decisions (settled)

| Question | Decision |
| --- | --- |
| Binding mechanism | **Native PyO3 FFI** to `grit-lib` (in-process, no external binary at runtime) |
| Initial scope | **Read-core MVP** (see §2) |
| API style | **Thin 1:1 mapping** of grit-lib names/types (not a high-level pygit2-style API) |
| Testing | **Oracle (vs real `git`) + mirrored grit-lib unit tests** |
| grit-lib dependency | **Strategy A** — pin the published `grit-lib` crate from crates.io |
| Python ABI | Build with **abi3** (target 3.9+) so one wheel covers many CPython versions |
| License | Match grit-lib's license (confirm during spike; default to the same) |

### Dependency strategy A (chosen), with fallback

Depend on the **published `grit-lib` crate** from crates.io, pinned to a specific
version recorded in `Cargo.toml`. If the build spike (§8.1) shows the published
crate is too old to expose the read-core API we need, fall back to pinning a
specific **git revision** of `gitbutlerapp/grit` (strategy B). The fallback is a
one-line `Cargo.toml` change and does not affect the rest of the design.

## 4. Architecture and repository layout

Standard maturin **mixed** (Rust + Python) layout. The Rust binding layer is split
into one file per bound subsystem so each file stays small and focused, mirroring
grit-lib's own module boundaries.

```
pygrit/
├── Cargo.toml              # crate "pygrit": cdylib; deps: pyo3 (abi3), grit-lib (pinned)
├── pyproject.toml          # build-backend = maturin; uv-managed dev deps
├── src/                    # Rust binding layer (thin wrappers, no business logic)
│   ├── lib.rs              # #[pymodule] — registers classes/exceptions
│   ├── error.rs            # grit_lib::Error -> Python exception hierarchy
│   ├── repository.rs       # Repository: discover/open, refs, config, odb accessors
│   ├── odb.rs              # Odb.read(oid) -> Object; exists(oid)
│   ├── objects.rs          # ObjectId, ObjectKind, Object + Commit/Tree/Blob/Tag views
│   ├── refs.rs             # reference listing and resolution
│   ├── revwalk.rs          # revision walk / log iteration
│   └── diff.rs             # tree/content diff -> structured results
├── python/
│   └── pygrit/
│       ├── __init__.py     # re-exports the native module's public symbols
│       └── __init__.pyi    # hand-written type stubs (mypy coverage)
└── tests/                  # pytest: oracle + mirrored units + fixtures
```

- The native extension is imported as `pygrit._pygrit`; `python/pygrit/__init__.py`
  re-exports it so users write `import pygrit`.
- Each Rust binding file is a *thin* wrapper: convert arguments, call grit-lib,
  convert results/errors. No domain logic lives in the binding layer.

## 5. Python API surface (thin 1:1, read-core)

Names mirror grit-lib directly.

### Repository
- `Repository.discover(path) -> Repository` — walk upward to find a repo.
- `Repository.open(path) -> Repository` — open an exact repo/git dir.
- Properties: `.git_dir`, `.work_dir`.
- Accessors: `.odb -> Odb`, `.config -> ConfigSet`.
- `.references() -> Iterable[Reference]`.
- `.resolve(spec: str) -> ObjectId` — resolve a refspec/revision to an id.
- `.revwalk(start, ...) -> Iterable[ObjectId | Commit]`.
- `.diff(a, b) -> Diff`.

### Objects
- `ObjectId` — hex parse/format, `__eq__`, `__hash__`, `__repr__`.
- `ObjectKind` — enum: `COMMIT`, `TREE`, `BLOB`, `TAG`.
- `Object` — generic, with kind-specific views:
  - `Commit`: `tree`, `parents`, `author`, `committer`, `message`.
  - `Tree`: iterable of entries `(mode, name, ObjectId, kind)`.
  - `Blob`: `data -> bytes` (no forced UTF-8 decoding).
  - `Tag`: `target`, `name`, `tagger`, `message`.

### Odb
- `Odb.read(oid: ObjectId) -> Object`.
- `Odb.exists(oid: ObjectId) -> bool`.

### Config
- `ConfigSet.get_str(key) -> str | None`
- `ConfigSet.get_bool(key) -> bool | None`
- `ConfigSet.get_int(key) -> int | None`

> Exact grit-lib method signatures are pinned during the build spike (§8.1) once
> `cargo doc` is available locally. The names above reflect grit-lib's documented
> public surface; any rename to match the real API will be a mechanical update.

## 6. Error handling

- A base exception `pygrit.GritError` with a small subclass tree:
  - `NotFoundError` — object/ref/repo not found.
  - `InvalidObjectError` — malformed id or object.
  - `RepositoryError` — discovery/open/config failures.
- `src/error.rs` maps `grit_lib::Error` variants onto these exceptions.
- **No panics cross the FFI boundary.** Every grit-lib `Result` is converted to a
  Python return value or exception; `catch_unwind` guards any code that could panic.

## 7. Testing strategy (oracle + mirrored units)

- **Fixtures:** build temporary git repositories with the real `git` CLI
  (present: `git 2.53.0`), covering loose and packed objects.
- **Oracle / differential tests:** for each binding operation, run the equivalent
  `git` command and assert equality of results:
  - `resolve` vs `git rev-parse`
  - `odb.read` vs `git cat-file -p` / `-t`
  - `revwalk` vs `git log --format=...`
  - `diff` vs `git diff` (and `git diff-tree`)
  - `config.get_*` vs `git config --get`
- **Mirrored unit tests:** port a representative handful of grit-lib's own Rust
  unit tests into pytest (e.g. object-id hex parsing round-trip, object-kind
  classification, ref-name validation), exercising the same behavior through the
  bindings.
- **Edge cases:** empty repo, detached HEAD, packed vs loose objects, binary
  blobs, non-UTF-8 paths/messages.
- **Note on grit's shell suite:** grit's headline test suite (`git/t/`) drives the
  *CLI*, not the library API, so it is not ported directly; its behaviors are
  reflected indirectly via the oracle tests above.
- **Runner & env:** `pytest`; Python dev deps managed by `uv`; the extension is
  built into the uv venv via `maturin develop` for local iteration.

## 8. Milestones

### 8.1 Build spike (de-risk first)
Install `maturin` (`uv tool install maturin`); add the pinned `grit-lib`
dependency (disabling transport/default features where possible to stay
pure-Rust); build a minimal `#[pymodule]` that does `Repository.discover()` and
reads the `HEAD` commit. **Exit criteria:** wheel builds and the read works from
Python. This validates the dependency choice and the real API before committing to
the full surface. If `pkg-config`/`-sys` deps are required, install `pkg-config`.

### 8.2 Object model + odb read (with tests)
`ObjectId`, `ObjectKind`, `Object`/`Commit`/`Tree`/`Blob`/`Tag`, `Odb.read/exists`.

### 8.3 References + resolve
`references()`, `resolve(spec)`.

### 8.4 Revwalk / log
`revwalk(...)`.

### 8.5 Diff
`diff(a, b)`.

### 8.6 Config + stubs + CI polish
`ConfigSet`, finalize `__init__.pyi`, mypy clean, optional GitHub Actions wheel
matrix.

## 9. Tooling and conventions

- **Python:** `ruff format`; type annotations everywhere; `mypy` clean against the
  stubs (`uv` for env/deps — no pip/poetry/requirements.txt).
- **Rust:** `cargo fmt`, `cargo clippy`.
- **Build:** maturin (mixed layout, abi3).
- **CI (optional, if a remote is desired):** GitHub Actions building wheels with
  maturin across a Python matrix, cargo cache, running pytest.

## 10. Toolchain status (as of 2026-06-13)

- ✅ `rustc 1.94.1`, `cargo 1.94.0` (source-tarball install; no `rustup` — not required).
- ✅ `gcc 15.2.0` (linker).
- ✅ `uv 0.11.14`, Python 3.13.12, `git 2.53.0`.
- ⚠️ `maturin` — to be installed via `uv tool install maturin` (spike step).
- ⚠️ `pkg-config` — install only if grit-lib pulls a C-backed `-sys` dependency.

## 11. Open items / defaults

- **License:** confirm grit-lib's license during the spike; default `pygrit` to the same.
- **Python support:** abi3 targeting 3.9+ (revisit if a grit-lib dependency forbids it).
- **grit-lib version pin:** exact version recorded in `Cargo.toml` after the spike.
