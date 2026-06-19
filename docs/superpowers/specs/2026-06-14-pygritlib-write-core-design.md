# pygritlib Write-Core v2 — Phase A Design (Local Write-Core)

**Date:** 2026-06-14
**Type:** Design spec (drives an implementation plan)
**Status:** Approved — ready for writing-plans
**Phase:** A of A→B→C (see §8 Roadmap)

## Goal

Add a local object/ref **write** surface to pygritlib, which today is read-only.
Phase A delivers a scriptable "build commits in a (bare or non-bare) repository" API
— write objects, stage an index, write trees, create commit/tag objects, and mutate
refs — all as thin wrappers over grit-lib 0.4.1 plumbing, with no working-tree
mutation, no merge, and no network. It is working, testable software on its own.

## Background

The read-surface spike (`docs/superpowers/specs/2026-06-15-grit-lib-write-surface-spike.md`)
established the controlling fact: grit-lib 0.4.1 is substantially write-capable but
ships **no porcelain** — there is no `repo.commit()`/`repo.checkout()`/`repo.tag()`.
Every multi-step workflow must be assembled in the binding, exactly as grit-lib's own
`examples/commit_tree.rs` does
(blob → index → write_tree → serialize_commit → odb.write → write_ref → append_reflog).
This design owns that porcelain at the binding layer.

The read-core is an OO façade (`Repository`, `Odb`, `Commit`, `Tree`, `Signature`,
`Reference`, …) built over grit-lib's free-function/data-struct API, with a `GritError`
exception hierarchy and GIL-releasing operations. Phase A extends that same façade so
the write surface is stylistically identical to the read surface.

## Scope and phasing

"Everything" (read + write + networking) is the documented destination, built in three
stacked phases because each is an independent subsystem with a distinct dependency and
risk profile. Phase A is specced here; B and C each get their own spec → plan →
implementation cycle later (§8).

**In scope (Phase A):** object writing, index/staging, write-tree-from-index,
commit-object creation, annotated-tag-object creation, ref mutation (create/update/
delete, symbolic refs/HEAD), opt-in reflog, opt-in compare-and-swap on ref updates.

**Out of scope (Phase A):** working-tree checkout, repo `init`, three-way merge, the
combined "commit-and-advance-branch" porcelain, fetch/push/clone, signing, and any
Cargo feature beyond the current default set.

## Design decisions

These five decisions were settled during brainstorming and are binding for the plan:

| Decision | Choice | Rationale |
| --- | --- | --- |
| **Architecture** | Methods on `Repository` and its sub-objects (`repo.odb.write`, `repo.index()`, `repo.create_commit`, `repo.update_ref`, …); binding assembles workflows in Rust. | Identical in style to the read-core façade; one coherent object model; most Pythonic; the boring, maintainable choice. |
| **Index API** | High-level `add`/`stage`/`remove`/`write`/`write_tree` **and** a constructable raw `IndexEntry` (`add_entry`). | Convenience for the common synthetic-commit path plus full 15-field fidelity for power users. |
| **Identity** | Constructable `Signature(name, email, when)` for the common case **and** a raw `author_raw`/`committer_raw`/`tagger_raw` byte escape-hatch on the create-* builders. | Symmetric with the read-side `Signature`; the raw bytes guarantee byte-identical OIDs for unusual identities. |
| **Reflog** | Opt-in: a reflog entry is appended only when `message=` (and `signer=`) is passed to a ref op; a standalone `append_reflog()` is also exposed. | Honest to grit-lib plumbing (`write_ref` does not auto-log); no hidden config reads or identity lookups. |
| **Ref safety** | Default overwrite (plumbing-faithful), opt-in `expected_old=<oid>` compare-and-swap, and a `create=True` flag for create-only. | Race-aware and create-only semantics when wanted, without paternalism; mirrors `git update-ref <ref> <new> <old>`. See the best-effort caveat in §6. |

## 1. Architecture & module layout

Each Python write method assembles a grit-lib plumbing workflow in Rust. No new
dependencies, no Cargo features, no network.

| File | Change | Adds |
| --- | --- | --- |
| `src/odb.rs` | extend | `Odb.write`, `Odb.hash` |
| `src/index.rs` | **new** | `Index` pyclass (wraps `Mutex<grit_lib::index::Index>` + `Arc<Repository>`); constructable `IndexEntry` pyclass |
| `src/objects.rs` | extend | make `Signature` constructable + `.raw`; `CommitData`/`TagData` build helpers used by the builders |
| `src/refs.rs` | extend | `update_ref`, `delete_ref`, `set_head`, `set_symbolic_ref`, `append_reflog` (binding-layer CAS lives here) |
| `src/repository.rs` | extend | wire `index()`, `create_commit()`, `create_tag()`, and the ref ops onto `Repository` |
| `src/lib.rs` | extend | register the new `Index`/`IndexEntry` pyclasses and the `RefMismatchError` exception |
| `python/pygritlib/__init__.py` | extend | re-export new symbols; define the `UNSET` sentinel |
| `python/pygritlib/__init__.pyi` | extend | stubs for everything in §2 (kept in sync; `stubtest` gate) |

**Concurrency model (unchanged from read-core):** `Odb` writes through `&self`
(grit-lib's interior `Arc<Mutex>`), so no `&mut Repository` is needed. The `Index` is a
binding-owned value behind a `Mutex`; mutating methods lock it, and `write_tree` reaches
the odb through the held `Arc<Repository>`. All write calls release the GIL via
`allow_threads`, matching the existing reads. On-disk effects are immediate and atomic
per object (temp-file + rename; loose objects `0o444`; ref writes use `.lock` + rename).

## 2. Public API surface (additions to `__init__.pyi`)

```python
# --- Odb: object writing -------------------------------------------------
class Odb:
    def write(self, kind: ObjectKind, data: bytes) -> ObjectId: ...   # writes loose obj, returns oid
    def hash(self, kind: ObjectKind, data: bytes) -> ObjectId: ...     # compute oid only, no write

# --- Signature: now constructable ---------------------------------------
class Signature:
    def __init__(self, name: bytes, email: bytes,
                 when: tuple[int, int]) -> None: ...   # when = (unix_seconds, tz_offset_seconds)
    # existing read props retained: name, email, when, name_str, email_str
    @property
    def raw(self) -> bytes: ...                        # formatted "Name <email> <unix> <+HHMM>"

# --- IndexEntry: constructable raw entry --------------------------------
@final
class IndexEntry:
    def __init__(self, path: bytes, oid: ObjectId, mode: int, *,
                 ctime: tuple[int, int] = ..., mtime: tuple[int, int] = ...,
                 dev: int = 0, ino: int = 0, uid: int = 0, gid: int = 0,
                 size: int = 0, flags: int = 0) -> None: ...
    # read-only props mirroring the settable fields (path, oid, mode, ctime, mtime,
    # dev, ino, uid, gid, size, flags); grit-lib's remaining derived IndexEntry
    # fields (e.g. flag sub-bits, name length) are computed by the binding.

# --- Index: staging ------------------------------------------------------
@final
class Index:
    def add(self, path: bytes, oid: ObjectId, mode: int) -> None: ...   # synthetic entry, zeroed stat
    def stage(self, path: bytes | os.PathLike[str]) -> None: ...        # real file (path relative to work_tree
                                                                        # root): hash->odb->entry_from_stat;
                                                                        # raises RepositoryError on a bare repo
    def add_entry(self, entry: IndexEntry) -> None: ...                  # raw entry (add_or_replace)
    def remove(self, path: bytes) -> bool: ...                          # True if an entry was removed
    def write(self, path: bytes | os.PathLike[str] | None = None) -> None: ...  # default: repo index path
    def write_tree(self) -> ObjectId: ...                               # write_tree_from_index(odb, idx, "")
    def __len__(self) -> int: ...
    def __iter__(self) -> Iterator[IndexEntry]: ...

# --- Repository: builders + ref ops -------------------------------------
class Repository:
    def index(self) -> Index: ...   # loads .git/index (empty Index if none exists)

    def create_commit(self, tree: ObjectId, parents: list[ObjectId], *,
                      message: bytes,
                      author: Signature | None = None, committer: Signature | None = None,
                      author_raw: bytes | None = None, committer_raw: bytes | None = None,
                      encoding: bytes | None = None) -> ObjectId: ...
        # Provide author XOR author_raw; same for committer. Pure: returns the new
        # commit oid and moves no ref.

    def create_tag(self, target: ObjectId, target_kind: ObjectKind, name: bytes, *,
                   message: bytes,
                   tagger: Signature | None = None, tagger_raw: bytes | None = None) -> ObjectId: ...
        # Creates the annotated-tag OBJECT and returns its oid. Provide tagger XOR
        # tagger_raw. Pointing refs/tags/<name> at it is a separate update_ref call.

    def update_ref(self, name: bytes, target: ObjectId, *,
                   expected_old: ObjectId | None = None,  # None=overwrite; oid=compare-and-swap
                   create: bool = False,                  # True=create-only (must not already exist)
                   message: bytes | None = None, signer: Signature | None = None) -> None: ...

    def delete_ref(self, name: bytes, *,
                   expected_old: ObjectId | None = None,  # None=delete unconditionally; oid=CAS-delete
                   message: bytes | None = None, signer: Signature | None = None) -> None: ...

    def set_head(self, target: bytes) -> None: ...               # symbolic HEAD -> b"refs/heads/main"
    def set_symbolic_ref(self, name: bytes, target: bytes) -> None: ...
    def append_reflog(self, name: bytes, old: ObjectId, new: ObjectId, *,
                      signer: Signature, message: bytes, force_create: bool = False) -> None: ...
```

`update_ref` expresses three states with two plain parameters (a native PyO3 method
cannot distinguish an omitted argument from an explicit `None`, and the strict
`stubtest` gate forbids a custom sentinel default): `expected_old=<oid>` is
compare-and-swap (write only if the ref currently equals `oid`), `create=True` is
create-only (fail if the ref already exists), and the default
(`expected_old=None, create=False`) overwrites. Passing both `create=True` and
`expected_old=<oid>` raises `ValueError`. `delete_ref` needs only two states: the default
deletes unconditionally, and `expected_old=<oid>` deletes only if the ref still points
there.

### grit-lib primitives each method wraps

| pygritlib method | grit-lib plumbing |
| --- | --- |
| `Odb.write` / `Odb.hash` | `Odb::write(&self, kind, data)` / `Odb::hash(&self, kind, data)` |
| `Index.add` | build `IndexEntry` (zeroed stat) → `Index::add_or_replace` |
| `Index.stage` | read file → `Odb::write(Blob, bytes)` → `index::entry_from_stat(worktree, rel, oid, mode)` → `add_or_replace` |
| `Index.add_entry` | `Index::add_or_replace(entry)` |
| `Index.remove` | `Index::remove(&[u8]) -> bool` |
| `Index.write` | `Index::write(path)` (default = repo index path via `Repository::write_index`) |
| `Index.write_tree` | `write_tree::write_tree_from_index(odb, index, "")` |
| `create_commit` | build `CommitData { tree, parents, author, committer, author_raw, committer_raw, encoding, message, raw_message }` → `objects::serialize_commit` → `Odb::write(Commit, raw)` |
| `create_tag` | build `TagData` → `objects::serialize_tag` → `Odb::write(Tag, raw)` |
| `update_ref` / `delete_ref` | `refs::write_ref` / `refs::delete_ref` (preceded by a binding-layer read-compare when `expected_old`/`create` is set) |
| `set_head` / `set_symbolic_ref` | `refs::write_symbolic_ref(git_dir, "HEAD"|name, target)` |
| `append_reflog` | `refs::append_reflog(git_dir, refname, old, new, identity, message, force_create)` |

## 3. Data flow — canonical commit-build

```python
repo = pygritlib.Repository.open(git_dir)
blob = repo.odb.write(ObjectKind.BLOB, b"hello\n")          # 1. write blob
idx  = repo.index()
idx.add(b"greeting.txt", blob, mode=0o100644)               # 2. stage
idx.write()                                                 #    persist .git/index
tree = idx.write_tree()                                     # 3. tree from index
sig  = pygritlib.Signature(b"Ada", b"ada@x.io", (1718000000, 0))
commit = repo.create_commit(tree, parents=[], author=sig,   # 4. serialize+write commit
                            committer=sig, message=b"init\n")
repo.update_ref(b"refs/heads/main", commit,                 # 5. move branch (create-only)
                create=True, message=b"commit: init", signer=sig)
```

Each numbered step is a single grit-lib call (or a short fixed sequence) wrapped with
GIL release and error mapping. `create_commit` builds
`CommitData → serialize_commit → odb.write(Commit, raw)` and moves no ref; the caller
advances the branch explicitly (step 5). The combined "commit-and-advance-HEAD"
porcelain — which must resolve HEAD's branch, CAS, and synthesize a reflog message — is
deferred to Phase B.

## 4. Error handling

The read-core hierarchy (`GritError` → `RepositoryError`, `ObjectNotFoundError`,
`InvalidObjectError`) is reused. Writes add exactly one new exception plus binding-layer
argument validation performed before any disk write:

- **`RefMismatchError(GritError)`** — *new*. Raised by `update_ref`/`delete_ref` when
  the `expected_old=` constraint is violated (CAS value differs, or create-only found an
  existing ref). The message carries the ref name and the expected vs actual oids.
  Registered in `src/lib.rs` and exported in `__all__`.
- **`ValueError`** (binding-layer, pre-write) — `create_commit`/`create_tag` require
  `author` XOR `author_raw` (committer/tagger likewise) and a non-optional `message`;
  `update_ref` rejects `create=True` combined with `expected_old=<oid>`. Validated up
  front so a misuse never half-writes.
- **`OSError`** — grit-lib `Error::Io` (unwritable path, disk full, `stage()` on a
  missing file) maps to `OSError` with errno, exactly as the read-core already does.
- **`GritError`** — grit-lib `IndexError` and the `#[non_exhaustive]` catch-all map
  here. We deliberately do **not** introduce a `pygritlib.IndexError`, to avoid
  shadowing Python's builtin. The existing `map_err` already handles the catch-all arm.

Because object writes are individually atomic (temp-file + rename), a mid-sequence
failure leaves already-written loose objects orphaned but harmless (reclaimed by
`git gc`) — never a corrupt ref or index.

## 5. Testing strategy

The read-core's **oracle approach** (mirror each operation against real `git`, reusing
the `tests/gitlib.py` helper) extends to writes, where the decisive assertion is
**byte-exact OID parity with git**. Determinism comes from pinned timestamps plus
`GIT_AUTHOR_DATE`/`GIT_COMMITTER_DATE` so git and pygritlib emit identical bytes. All
tests run in tempdirs (disk effects are immediate).

| New test file | Asserts |
| --- | --- |
| `tests/test_odb_write.py` | `odb.write(BLOB, d)` oid == `git hash-object -w`; `odb.hash` matches without writing; round-trip write→read via the read-core |
| `tests/test_index_write.py` | `index.write_tree()` == `git write-tree` for the same entries; index persists (verified via `git ls-files --stage`); `add` vs `stage` vs `add_entry`; `remove` returns/erases correctly |
| `tests/test_create_commit.py` | `create_commit(...)` oid == `git commit-tree` with pinned dates; `author_raw` escape-hatch reproduces a known odd-identity oid byte-for-byte; multi-parent (merge-shaped) commit |
| `tests/test_create_tag.py` | annotated-tag oid == `git mktag` / `git cat-file` output |
| `tests/test_ref_write.py` | `update_ref` then `git rev-parse` agrees; CAS mismatch → `RefMismatchError`; `expected_old=None` refuses an existing ref; create-only succeeds when absent; `delete_ref` (+ its CAS); `set_head`/`set_symbolic_ref` |
| `tests/test_reflog.py` | `append_reflog` and the `message=` opt-in produce entries readable by `git reflog` / present in `.git/logs/<ref>` |
| `tests/test_write_concurrency.py` | parallel threaded writes are sound (mirrors existing `test_concurrency.py`; validates GIL release on the write path) |
| `tests/test_write_errors.py` | `ValueError` on author/author_raw misuse and missing message; `OSError` on an unwritable path |

Quality gates stay green: `ruff format`, `mypy`, and `stubtest pygritlib` (the `.pyi`
must keep matching the native module, as with the read-core).

## 6. Known limitations & risks

- **Best-effort compare-and-swap.** The spike found grit-lib 0.4.1 exposes **no atomic
  compare-and-swap** ref primitive — only `write_ref`, which takes its lockfile
  internally. Phase A therefore implements `expected_old=` CAS at the binding layer as
  read-current → compare → write. This reliably catches the non-concurrent "did this
  move since I read it?" case and create-only races, but is **not** a hard guarantee
  against another process writing inside the read-compare-write window. A truly atomic
  CAS needs an upstream primitive or a binding-held lockfile around the same `.lock`
  path grit-lib uses; that upgrade is tracked for Phase B. **The implementation plan
  must verify the exact grit-lib 0.4.1 ref-locking surface before finalizing this code**
  (confirm whether a held-lock read is reachable; if so, prefer it).
- **No transactional multi-ref update.** Consistent with the spike: each ref op is
  independent. Building a commit and advancing a branch are two calls; a crash between
  them leaves the (harmless) commit object written but the branch unmoved.
- **Mem-overlay dry-run not exposed in Phase A.** grit-lib's only dry-run is
  `Odb::enable_mem_overlay()`/`disable_mem_overlay()`. It is intentionally left out of
  the Phase A public surface (YAGNI); tests use tempdirs. It is a candidate ergonomic
  for a later phase.

## 7. File/responsibility summary

- **Object writing** lives in `src/odb.rs` — smallest, purely additive.
- **Index/staging** is the one genuinely new unit (`src/index.rs`): owns the
  `Index`/`IndexEntry` pyclasses and the `add`/`stage`/`add_entry`/`remove`/`write`/
  `write_tree` surface.
- **Object construction** (`create_commit`/`create_tag`, constructable `Signature`)
  lives with the object types in `src/objects.rs`; the two builders are surfaced as
  `Repository` methods in `src/repository.rs`.
- **Ref mutation** (including binding-layer CAS and reflog) is isolated in `src/refs.rs`.

Each unit has one clear responsibility and a well-defined Python-facing interface, and
can be tested independently against the git oracle.

## 8. Roadmap appendix (recorded; not built in Phase A)

- **Phase B — Worktree & merge.** `repo::init_repository`, checkout-tree-into-worktree
  primitives (`porcelain::checkout::{write_to_worktree, apply_index_file_mode, …}`),
  three-way tree merge (`merge_trees::merge_trees_three_way`), lightweight/annotated
  tag-ref porcelain, the combined "commit-and-advance-branch" convenience, bare-repo
  worktree guards, and the atomic-CAS upgrade. Depends on Phase A.
- **Phase C — Networking & clone.** fetch/push over a caller-supplied `dyn Connection`
  (`fetch::fetch_remote`, `push::push_remote`), the off-by-default `http-ureq` feature, a
  transport abstraction, and a `clone` assembled from init + fetch + checkout (grit-lib
  has no clone porcelain). Depends on Phases A and B.

## 9. Load-bearing references

grit-lib 0.4.1 write API as cataloged in the spike (§Capability map) and the read↔write
gaps in `docs/superpowers/api-matrix.md` ("write functions … deferred — not in read-core
MVP"). Canonical assembly pattern: grit-lib's `examples/commit_tree.rs`. Key signatures:
`Odb::{write,hash}` (`src/odb.rs`); `objects::{serialize_commit,serialize_tag,
serialize_tree}`, `CommitData`/`TagData`/`TreeEntry` (`src/objects.rs`);
`refs::{write_ref,write_symbolic_ref,delete_ref,append_reflog}` (`src/refs.rs`);
`Index::{new,load,write,add_or_replace,stage_file,remove,sort}`,
`index::entry_from_stat`, `write_tree::write_tree_from_index` (`src/index.rs`,
`src/write_tree.rs`); `Error` is `#[non_exhaustive]` (`src/error.rs`).
