# pygrit

Native Python bindings for [`grit-lib`](https://crates.io/crates/grit-lib) — the
core Rust library of [gitbutlerapp/grit](https://github.com/gitbutlerapp/grit), a
from-scratch reimplementation of Git in Rust.

pygrit is built with [PyO3](https://pyo3.rs) and packaged as an `abi3` wheel with
[maturin](https://maturin.rs). The first release is a thin, read-core Python façade
over grit-lib: open/discover repositories, read objects (commit/tree/blob/tag), list
and resolve references, walk history, diff trees, and read config — in-process, with
no external git binary at runtime.

> **Status:** early development. Phase 1 (build spike) is complete; the public Python
> API is still being built out. See `docs/superpowers/` for the design spec, plan,
> and the grit-lib API matrix.

## Requirements

- **Python 3.11+** (the wheel is `abi3-py311`; free-threaded/no-GIL CPython is not
  supported by standard abi3 wheels).
- **Platforms:** Linux/Unix (x86_64 verified; aarch64 expected). macOS is
  best-effort. **Windows is deferred** until grit-lib gains Windows support
  (grit-lib depends on `libc`/`nix` and is currently Unix-oriented).
- No system C libraries are required to build: grit-lib uses pure-Rust compression
  (`miniz_oxide`) and hashing (`sha1`/`sha2`); there are **no `-sys`/pkg-config
  dependencies**.

## Build / install (development)

This project uses [`uv`](https://docs.astral.sh/uv/) for Python environment and
dependency management (no pip/poetry/requirements.txt), maturin for the build, and a
pinned Rust toolchain (`rust-toolchain.toml`, channel 1.94.1).

```bash
# 1. Create the venv and install dev dependencies (maturin, pytest, mypy, ruff).
uv venv
uv sync --group dev

# 2. Build the native extension and install it editable into the venv.
uv run maturin develop --uv

# 3. Run the tests.
uv run pytest tests/ -v
```

Quick check:

```python
import pygrit
print(pygrit._hello())  # -> "pygrit"
```

### Building a wheel / sdist

```bash
uv run maturin build --release --locked   # wheel -> target/wheels/
uv run maturin sdist                       # sdist -> target/wheels/
```

The wheel is tagged `cp311-abi3-<platform>` and works on CPython 3.11+.

## How it maps to grit-lib

pygrit is a documented Python **façade** over grit-lib, not a literal 1:1 re-export.
grit-lib 0.4.1 exposes a free-function / data-struct style API (public fields, free
functions taking `&Repository`/`&Odb`/`git_dir`, and `parse_*` functions over raw
bytes); pygrit constructs the ergonomic Python classes (`Repository`, typed object
views, `Reference`, `Signature`) on top of those primitives. The complete, verified
mapping — exact module paths, signatures, return/error types, and the error →
exception table — lives in
[`docs/superpowers/api-matrix.md`](docs/superpowers/api-matrix.md).

## pygrit ↔ grit-lib version compatibility

pygrit pins grit-lib **exactly** (`=` pin) with a committed `Cargo.lock` and
`--locked` builds for reproducibility (Strategy A — the published crate fully exposes
read-core, so no git-revision fallback is used).

| pygrit | grit-lib | pyo3 | Rust toolchain | Python (abi3) | Notes |
| --- | --- | --- | --- | --- | --- |
| 0.1.0 (dev) | `=0.4.1` (MIT) | `=0.23.3` | 1.94.1 | ≥ 3.11 | Phase 1 spike pin |

## License

MIT — matching grit-lib (also MIT). See [`LICENSE`](LICENSE) if present, and the
license metadata in `pyproject.toml` / `Cargo.toml`.
