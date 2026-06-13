# pygrit ↔ grit-lib Rust→Python API matrix

> **Status:** Produced by the Phase 1 build spike (Task 1.7), verified against the
> real published crate source. This is the authoritative reference that drives
> every later phase. When a provisional pygrit symbol from the design spec (§5) has
> no direct grit-lib equivalent, it is marked **"binding-layer constructed"** (we
> build it in Rust over grit-lib primitives) or **"deferred — not available"**.

## Pinned versions (recorded for reproducibility)

| Component | Version | Notes |
| --- | --- | --- |
| grit-lib | `=0.4.1` | exact pin; license **MIT**; latest published on crates.io as of 2026-06-13 |
| pyo3 | `=0.23.3` | features `abi3-py311`, `extension-module`; license MIT OR Apache-2.0; compiles on rustc 1.94.1 (no bump needed) |
| maturin | `1.14.0` (constraint `>=1.7,<2.0`) | `uv tool` + dev dep |
| rustc / cargo | 1.94.1 / 1.94.0 | pinned via `rust-toolchain.toml` |
| Python (build/test) | CPython 3.13.13 in venv; wheel targets abi3 ≥ 3.11 | |

**Crate lib name is `grit_lib`** (package `grit-lib`). All paths below are
`grit_lib::...`. A convenience `grit_lib::prelude::*` re-exports
`ConfigSet, Error, Result, Index, Object, ObjectId, ObjectKind, Odb, Repository`.
Curated grouping modules also exist: `object_store`, `references`, `revision`,
`diffing`, `configuration`, `worktree_index`.

## Architectural shape (important — differs from the provisional design)

grit-lib 0.4.1 is **free-function / data-struct style**, not a method-heavy OO API:

- `Repository` exposes **public fields** (`repo.git_dir`, `repo.work_tree`,
  `repo.odb`) accessed directly — there are **no** `git_dir()`/`odb()` getter
  methods. `is_bare()` is a method.
- Most read operations are **free functions** taking `&Repository`, `&Odb`, or
  `git_dir: &Path` — e.g. `rev_parse::resolve_revision(&repo, spec)`,
  `refs::list_refs(git_dir, prefix)`, `diff::diff_trees(odb, ...)`.
- Parsed object views (`Commit`/`Tree`/`Tag`) are produced by **free `parse_*`
  functions over raw bytes** (`repo.odb.read(&oid)?.data`), returning plain data
  structs — NOT objects with rich method APIs.
- There is **no structured `Signature`/identity struct** and **no rich `Reference`
  struct**. Author/committer/tagger are raw `String`s in Git wire format
  (`Name <email> <unix> <+HHMM>`); references are a `(String, ObjectId)` tuple plus
  a 2-variant `Ref` enum.

Consequence for pygrit: the Python façade (`Repository.odb`, `Commit.author`,
`Reference.name`, `Signature`, typed `Tree`/`Commit` views, etc.) is **mostly
binding-layer constructed** over these primitives. This is explicitly in-scope per
design spec §5 ("thin Python façade, not a literal 1:1 re-export").

---

## Read-core API matrix

Columns: **pygrit symbol** (provisional, design §5) | **grit-lib item — exact path + signature** | **return type** | **error type** | **notes**.

All `Result<T>` below means `grit_lib::error::Result<T>` = `std::result::Result<T, grit_lib::error::Error>`.

### Repository / repo handle (`grit_lib::repo`)

| pygrit symbol | grit-lib item (exact path + signature) | return | error | notes |
| --- | --- | --- | --- | --- |
| `Repository.discover(path)` | `grit_lib::repo::Repository::discover(start: Option<&Path>) -> Result<Repository>` | `Repository` | `Error::NotARepository` | Walks upward. Also consults `GIT_DIR`/`GIT_WORK_TREE`/cwd env even when `start` is `Some` — see WARNING below. |
| `Repository.open(git_dir, work_tree=None)` | `grit_lib::repo::Repository::open(git_dir: &Path, work_tree: Option<&Path>) -> Result<Repository>` | `Repository` | `Error::NotARepository`, format-version/extension errors | Explicit open; validates repo format. |
| (open variant) | `grit_lib::repo::Repository::open_skipping_format_validation(git_dir: &Path, work_tree: Option<&Path>) -> Result<Repository>` | `Repository` | as above | skips format validation |
| `.git_dir` | `Repository::git_dir` — **public field** `pub git_dir: PathBuf` | `PathBuf` | — | field, not a method; absolute path |
| `.work_tree` | `Repository::work_tree` — **public field** `pub work_tree: Option<PathBuf>` | `Option<PathBuf>` | — | `None` for bare repos |
| `.is_bare` | `Repository::is_bare(&self) -> bool` | `bool` | — | reads `core.bare`, else `work_tree.is_none()` |
| `.odb` | `Repository::odb` — **public field** `pub odb: Odb` | `Odb` | — | use `repo.odb.read(...)` directly |
| `.config` | **binding-layer constructed** via `ConfigSet::load(Some(&repo.git_dir), include_system)` | `ConfigSet` | `Error` | no `repo.config()` method — see Config section |
| (head path) | `Repository::head_path(&self) -> PathBuf` | `PathBuf` | — | path to the `HEAD` file |
| (load index) | `Repository::load_index(&self) -> Result<Index>` | `Index` | `Error::IndexError` | for index/worktree diffs (later phase) |
| (replace-aware read) | `Repository::read_replaced(&self, oid: &ObjectId) -> Result<Object>` | `Object` | `Error::ObjectNotFound`, … | honors replace-refs |
| (fixture init — test only) | `grit_lib::repo::init_repository(path: &Path, bare: bool, initial_branch: &str, template_dir: Option<&Path>, ref_storage: &str) -> Result<Repository>` | `Repository` | `Error` | used by grit-lib's own examples; `ref_storage = "files"` |

> **WARNING (discover + env):** `Repository::discover(Some(path))` still reads
> `env::current_dir()` and `GIT_DIR`/`GIT_WORK_TREE` internally. For deterministic,
> env-independent opening, resolve the `.git` dir and use
> `Repository::open(git_dir, work_tree)`. The spike's `_discover_head_hex` uses
> `discover` because the test runs against a clean isolated `tmp_path`.

### HEAD resolution / rev-parse (`grit_lib::rev_parse`, `grit_lib::refs`)

| pygrit symbol | grit-lib item (exact path + signature) | return | error | notes |
| --- | --- | --- | --- | --- |
| `Repository.resolve(spec)` | `grit_lib::rev_parse::resolve_revision(repo: &Repository, spec: &str) -> Result<ObjectId>` | `ObjectId` | `Error::InvalidRef`, `Error::ObjectNotFound`, `Error::Message`, … | **THE resolver.** Handles `"HEAD"`, full/abbrev hex, branch names, `HEAD~2`, etc. Returns an `ObjectId` (not an enum). |
| (resolve a named ref) | `grit_lib::refs::resolve_ref(git_dir: &Path, refname: &str) -> Result<ObjectId>` | `ObjectId` | `Error::InvalidRef`, `Error::ObjectNotFound` | lower-level; follows symbolic refs to a final oid |
| (read HEAD symbolic) | `grit_lib::refs::read_head(git_dir: &Path) -> Result<Option<String>>` | `Option<String>` | `Error::Io` | `Some("refs/heads/main")` if symbolic; `None` if detached |
| (read any symbolic ref) | `grit_lib::refs::read_symbolic_ref(git_dir: &Path, refname: &str) -> Result<Option<String>>` | `Option<String>` | `Error::Io` | |
| (sibling resolvers) | `resolve_revision_as_commit`, `resolve_revision_for_verify`, `resolve_revision_for_range_end`, … (same `(repo, spec) -> Result<ObjectId>` shape) | `ObjectId` | `Error` | specialized variants if needed later |

### ObjectId / oid (`grit_lib::objects`)

| pygrit symbol | grit-lib item (exact path + signature) | return | error | notes |
| --- | --- | --- | --- | --- |
| `ObjectId` | `grit_lib::objects::ObjectId` (struct; fields private; derives `Clone, Copy, PartialEq, Eq, Ord, Hash`; impls `Display`, `FromStr`) | — | — | fixed 32-byte buffer + length byte; algo inferred from length |
| `.hex` | `ObjectId::to_hex(&self) -> String` | `String` (40 hex SHA-1, 64 SHA-256, lowercase) | — | `Display`/`to_string()`/`format!("{oid}")` produce the same |
| `.raw` | `ObjectId::as_bytes(&self) -> &[u8]` | `&[u8]` (20 or 32) | — | |
| construct from hex | `ObjectId::from_hex(s: &str) -> Result<ObjectId>` (also `s.parse::<ObjectId>()` via `FromStr`) | `ObjectId` | `Error::InvalidObjectId` | 40 or 64 hex chars |
| construct from bytes | `ObjectId::from_bytes(bytes: &[u8]) -> Result<ObjectId>` | `ObjectId` | `Error::InvalidObjectId` | len must be 20 or 32 |
| `.hash_algorithm` | `ObjectId::algo(&self) -> HashAlgo` | `HashAlgo` | — | inferred from digest length |
| (null/zero) | `ObjectId::zero() -> ObjectId` (const) ; `ObjectId::null(algo: HashAlgo) -> ObjectId` (const) ; `ObjectId::is_zero(&self) -> bool` | | — | |
| `ObjectKind` | `grit_lib::objects::ObjectKind { Blob, Tree, Commit, Tag }` (impls `Display`, `FromStr`) | — | — | |
| (kind from bytes) | `ObjectKind::from_bytes(b: &[u8]) -> Result<ObjectKind>` ; `ObjectKind::as_str(&self) -> &'static str` | | `Error::UnknownObjectType` | |

### Hash algorithm (`grit_lib::objects::HashAlgo`) — SHA-1 vs SHA-256

| Item | Signature | Notes |
| --- | --- | --- |
| enum | `grit_lib::objects::HashAlgo { Sha1, Sha256 }` (`Default = Sha1`) | **SHA-256 IS representable.** |
| len | `HashAlgo::len(self) -> usize` | 20 / 32 |
| hex_len | `HashAlgo::hex_len(self) -> usize` | 40 / 64 |
| name | `HashAlgo::name(self) -> &'static str` | `"sha1"` / `"sha256"` |
| from name/len | `HashAlgo::from_name(name: &str) -> Option<HashAlgo>` ; `HashAlgo::from_len(len: usize) -> Option<HashAlgo>` | |
| repo's algo | `Odb::hash_algo(&self) -> HashAlgo` | the active repo's algorithm |

**SHA-256 readability:** `ObjectId` holds a 32-byte buffer and `parse_tree` auto-detects
oid width (`parse_tree_with_oid_len` for explicit width), `to_hex` emits 64 chars for
SHA-256. The read-core types support SHA-256; end-to-end SHA-256 repo reading should be
exercised with a SHA-256 fixture in the test phase (design §7 edge cases). Mark as
**supported by types; verify with a fixture in Phase 8.2+**.

### Object database (`grit_lib::odb`)

| pygrit symbol | grit-lib item (exact path + signature) | return | error | notes |
| --- | --- | --- | --- | --- |
| `Odb.read(oid)` | `Odb::read(&self, oid: &ObjectId) -> Result<Object>` | `Object` (`{ kind, data }`) | `Error::ObjectNotFound`, `Error::CorruptObject`, `Error::Io`, `Error::Zlib`, `Error::LooseHashMismatch` | decompressed, header-stripped bytes; loose + packs + alternates |
| `Odb.exists(oid)` | `Odb::exists(&self, oid: &ObjectId) -> bool` | `bool` | — (infallible) | loose + packs + alternates |
| (local-only existence) | `Odb::exists_local(&self, oid: &ObjectId) -> bool` | `bool` | — | loose store only |
| (algo) | `Odb::hash_algo(&self) -> HashAlgo` | `HashAlgo` | — | |
| (objects dir / path) | `Odb::objects_dir(&self) -> &Path` ; `Odb::object_path(&self, oid) -> PathBuf` | | — | |
| (write — deferred, out of read-core) | `Odb::write(&self, kind: ObjectKind, data: &[u8]) -> Result<ObjectId>` ; `Odb::hash(&self, kind, data) -> ObjectId` | | `Error` | NOT in read-core MVP; used to build fixtures |
| `Object` | `grit_lib::objects::Object { pub kind: ObjectKind, pub data: Vec<u8> }` ; `Object::new(kind, data)` ; `Object::to_store_bytes(&self) -> Vec<u8>` | — | — | the value `Odb::read` returns; destructure as `let Object { kind, data } = ...` |

### Parsed object views (`grit_lib::objects`) — all from raw bytes

| pygrit symbol | grit-lib item (exact path + signature) | return | error | notes |
| --- | --- | --- | --- | --- |
| `Commit` (parse) | `grit_lib::objects::parse_commit(data: &[u8]) -> Result<CommitData>` | `CommitData` | `Error::CorruptObject` | input = `repo.odb.read(&oid)?.data` |
| `Commit.tree` | `CommitData::tree: ObjectId` (field) | `ObjectId` | — | |
| `Commit.parents` | `CommitData::parents: Vec<ObjectId>` (field) | `Vec<ObjectId>` | — | |
| `Commit.author` | `CommitData::author: String` + `author_raw: Vec<u8>` (fields) | `String` / `Vec<u8>` | — | **raw single string** `Name <email> <unix> <+HHMM>`; NOT split. `author_raw` = exact bytes for non-UTF-8. |
| `Commit.committer` | `CommitData::committer: String` + `committer_raw: Vec<u8>` | | — | as above |
| `Commit.message_bytes` / `.message()` | `CommitData::message: String` + `raw_message: Option<Vec<u8>>` + `encoding: Option<String>` | | — | `raw_message` set for non-UTF-8 messages |
| `Tree` (parse) | `grit_lib::objects::parse_tree(data: &[u8]) -> Result<Vec<TreeEntry>>` ; `parse_tree_with_oid_len(data, oid_len) -> Result<Vec<TreeEntry>>` | `Vec<TreeEntry>` | `Error::CorruptObject` | auto-detects SHA-1/256 width |
| `TreeEntry.name` | `TreeEntry::name: Vec<u8>` (field) | `Vec<u8>` (**bytes**) | — | name only, no separators |
| `TreeEntry.mode` | `TreeEntry::mode: u32` (field) ; `TreeEntry::mode_str(&self) -> String` | `u32` / `String` | — | `mode_str` is git-style (`"40000"`, `"100644"`) |
| `TreeEntry.id` | `TreeEntry::oid: ObjectId` (field) | `ObjectId` | — | |
| `TreeEntry.kind` | **binding-layer constructed** from `mode` (compare to `grit_lib::index::MODE_TREE = 0o040000`) | — | — | no `kind` field; derive from mode |
| `Blob.data` | **none needed** — blob bytes are `repo.odb.read(&oid)?.data` where `kind == ObjectKind::Blob` | `Vec<u8>` | `Error` | no dedicated blob parser |
| `Tag` (parse) | `grit_lib::objects::parse_tag(data: &[u8]) -> Result<TagData>` | `TagData` | `Error::CorruptObject` | |
| `Tag.target` | `TagData::object: ObjectId` + `object_type: String` (fields) | | — | |
| `Tag.name` | `TagData::tag: String` (field) | `String` | — | short name, no `refs/tags/` |
| `Tag.tagger` | `TagData::tagger: Option<String>` (field) | `Option<String>` | — | raw Git ident format |
| `Tag.message_bytes` | `TagData::message: String` (field) | `String` | — | |

### Signature / identity (`grit_lib::ident`)

| pygrit symbol | grit-lib item | status | notes |
| --- | --- | --- | --- |
| `Signature` (struct with `.name`/`.email`/`.when`/offset) | **deferred — not available** as a struct | **binding-layer constructed** | grit-lib stores author/committer/tagger as raw `String` (`Name <email> <unix> <+HHMM>`). pygrit must parse name/email/time itself. |
| `.when` / timestamp parsing | `grit_lib::ident::parse_signature_times(ident: &str) -> Option<ParsedSignatureTimes { unix_seconds: i64, tz_offset_secs: i64, tz_hhmm_range: Range<usize> }>` | available helper | parses the trailing time + tz |
| (tail parse) | `grit_lib::ident::parse_signature_tail(ident: &str) -> Option<SignatureTail>` ; `grit_lib::ident::SignatureTimestamp { Valid(i64), Sentinel }` | available | name/email must be split manually on `<`…`>` |

### References (`grit_lib::refs`)

| pygrit symbol | grit-lib item (exact path + signature) | return | error | notes |
| --- | --- | --- | --- | --- |
| `Repository.references()` | `grit_lib::refs::list_refs(git_dir: &Path, prefix: &str) -> Result<Vec<(String, ObjectId)>>` | `Vec<(String, ObjectId)>` | `Error::Io`, `Error::InvalidRef` | `prefix=""` lists all under `refs/`; sorted by name; resolves to oids |
| (glob/physical variants) | `list_refs_glob(git_dir, pattern)` ; `list_refs_physical(git_dir, prefix)` (same return) | | `Error` | |
| `Reference` | `grit_lib::refs::Ref { Direct(ObjectId), Symbolic(String) }` (2-variant enum) | — | — | **no rich `Reference` struct.** |
| `Reference.name` | the `String` from the `list_refs` tuple | — | — | **binding-layer constructed** (name comes from listing, not a method) |
| `Reference.target` | `Ref::Direct(ObjectId)` | `ObjectId` | — | |
| `Reference.symbolic_target` / `.is_symbolic` | `Ref::Symbolic(String)` / `matches!(r, Ref::Symbolic(_))` | | — | **binding-layer constructed** |
| `Reference.peel()` | `grit_lib::refs::resolve_ref(git_dir: &Path, refname: &str) -> Result<ObjectId>` | `ObjectId` | `Error::ObjectNotFound`, `Error::InvalidRef` | follows symbolics to a final oid |
| (read one ref file) | `grit_lib::refs::read_ref_file(path: &Path) -> Result<Ref>` | `Ref` | `Error::InvalidRef`, `Error::Io` | |
| (ref writes — deferred) | `write_ref`, `write_symbolic_ref`, `delete_ref` | | `Error` | NOT in read-core MVP |

### Revwalk / rev-list (`grit_lib::rev_list`)

| pygrit symbol | grit-lib item (exact path + signature) | return | error | notes |
| --- | --- | --- | --- | --- |
| `Repository.revwalk(start, *, order)` | `grit_lib::rev_list::rev_list(repo: &Repository, positive_specs: &[String], negative_specs: &[String], options: &RevListOptions) -> Result<RevListResult>` | `RevListResult` | `Error` | **batch, not a lazy iterator.** Returns `Vec<ObjectId>`. |
| (result) | `RevListResult { pub commits: Vec<ObjectId>, pub objects: Vec<(ObjectId, String)>, pub boundary_commits, pub missing_objects, … }` | — | — | `.commits` is the ancestor walk, in output order |
| (options) | `RevListOptions { pub output_mode: OutputMode, pub first_parent: bool, pub all_refs: bool, … }` ; `RevListOptions::default()` | — | — | |
| (ordering) | `grit_lib::rev_list::OutputMode { OidOnly, Parents, Format(String) }` | — | — | for a manual lazy walk, follow `CommitData.parents` yourself |

### Diff (`grit_lib::diff`, `grit_lib::diffstat`)

| pygrit symbol | grit-lib item (exact path + signature) | return | error | notes |
| --- | --- | --- | --- | --- |
| `Repository.diff(a, b)` | `grit_lib::diff::diff_trees(odb: &Odb, old_tree_oid: Option<&ObjectId>, new_tree_oid: Option<&ObjectId>, prefix: &str) -> Result<Vec<DiffEntry>>` | `Vec<DiffEntry>` | `Error` | diff TREE oids (parse each commit's `.tree` first); `prefix=""` for root |
| (variants) | `diff_trees_show_tree_entries(...)` ; `diff_index_to_tree(odb, index, tree_oid, ignore_submodules)` ; `diff_index_to_worktree(...)` | | `Error` | |
| `DiffEntry` | `grit_lib::diff::DiffEntry { pub status: DiffStatus, pub old_path: Option<String>, pub new_path: Option<String>, pub old_mode: String, pub new_mode: String, pub old_oid: ObjectId, pub new_oid: ObjectId, pub score: Option<u32> }` | — | — | `path(&self) -> &str`, `display_path(&self) -> String` |
| `DiffEntry.status` | `grit_lib::diff::DiffStatus { Added, Deleted, Modified, Renamed, Copied, TypeChanged, Unmerged }` ; `DiffStatus::letter(&self) -> char` | — | — | A/D/M/R/C/T/U |
| (diffstat / patch) | `grit_lib::diffstat::*` ; `grit_lib::diff::unified_diff*` | | `Error` | text/patch output (later phase) |

> Note: `DiffEntry` paths are `Option<String>` (UTF-8), not raw bytes. For
> non-UTF-8 path fidelity (design §5 byte policy) the binding may need to confirm
> grit-lib's decoding behavior — flag for Phase 8.5.

### Config (`grit_lib::config`)

| pygrit symbol | grit-lib item (exact path + signature) | return | error | notes |
| --- | --- | --- | --- | --- |
| `Repository.config` | `grit_lib::config::ConfigSet::load(git_dir: Option<&Path>, include_system: bool) -> Result<ConfigSet>` | `ConfigSet` | `Error::ConfigError`, `Error::Io` | **binding-layer constructed** (no repo method). e.g. `ConfigSet::load(Some(&repo.git_dir), true)` |
| (repo-local only) | `ConfigSet::load_repo_local_only(git_dir: &Path) -> Result<ConfigSet>` ; `ConfigSet::new() -> ConfigSet` | | `Error` | |
| `ConfigSet.get_str(key)` | `ConfigSet::get(&self, key: &str) -> Option<String>` | `Option<String>` | — | last-wins; bare bool → `"true"` |
| (all values) | `ConfigSet::get_all(&self, key: &str) -> Vec<String>` | `Vec<String>` | — | |
| `ConfigSet.get_bool(key)` | `ConfigSet::get_bool(&self, key: &str) -> Option<Result<bool, String>>` | `Option<Result<bool, String>>` | — | `None`=absent; `Some(Err)`=present-but-unparseable |
| `ConfigSet.get_int(key)` | `ConfigSet::get_i64(&self, key: &str) -> Option<Result<i64, String>>` | `Option<Result<i64, String>>` | — | as above |
| (entry / regexp) | `ConfigSet::get_last_entry(key) -> Option<ConfigEntry>` ; `ConfigSet::get_regexp(pattern) -> Result<Vec<&ConfigEntry>, String>` | | | keys are case-folded/canonicalized (`"core.bare"`) |

---

## Error type → Python exception mapping (`grit_lib::error::Error`)

`grit_lib::error::Error` is `#[derive(Debug, thiserror::Error)]` and
**`#[non_exhaustive]`** — so any `From<Error> for PyErr` conversion **MUST** have a
catch-all arm (maps to base `GritError`). `grit_lib::error::Result<T> =
Result<T, Error>`. Suggested mapping to the design §7 exception hierarchy:

| grit-lib `Error` variant | shape | → pygrit exception (design §7) |
| --- | --- | --- |
| `NotARepository(String)` | tuple | `RepositoryError` |
| `ForbiddenBareRepository(String)` | tuple | `RepositoryError` |
| `DubiousOwnership(String)` | tuple | `RepositoryError` |
| `UnsupportedRepositoryFormatVersion(u32)` | tuple | `RepositoryError` |
| `UnsupportedRepositoryExtension(String)` | tuple | `RepositoryError` |
| `InvalidObjectId(String)` | tuple | `InvalidObjectError` (also consider `ValueError` for bad-arg shape) |
| `ObjectNotFound(String)` | tuple | `ObjectNotFoundError` |
| `CorruptObject(String)` | tuple | `InvalidObjectError` |
| `UnknownObjectType(String)` | tuple | `InvalidObjectError` |
| `ObjectHeaderTooLong { oid: String }` | struct | `InvalidObjectError` |
| `Io(std::io::Error)` (`#[from]`) | wraps io | `OSError` with `errno` where available |
| `Zlib(String)` | tuple | `InvalidObjectError` (decompress/corrupt) |
| `LooseHashMismatch { path, real_oid }` | struct | `InvalidObjectError` |
| `IndexError(String)` | tuple | `GritError` (index out of read-core MVP) |
| `CacheTreeCorrupt` | unit | `GritError` |
| `InvalidRef(String)` | tuple | `RepositoryError` (or a future `InvalidRefError`) |
| `PathError(String)` | tuple | `ValueError` / `GritError` |
| `ConfigError(String)` | tuple | `RepositoryError` (config load) / `GritError` |
| `Signing(String)` | tuple | `GritError` |
| `Auth(String)` | tuple | out of scope (networking) → `GritError` |
| `PushOptionsUnsupported` | unit | out of scope (networking) → `GritError` |
| `Message(String)` | tuple | `GritError` (generic fatal) |
| _(any future variant)_ | — | **`GritError` catch-all (required by `#[non_exhaustive]`)** |

Preserve the source message and offending path/OID; chain via `__cause__`.

---

## Minimal HEAD-hex call sequence (used by the spike `_discover_head_hex`)

```rust
use grit_lib::repo::Repository;
use grit_lib::rev_parse::resolve_revision;
use std::path::Path;

let repo = Repository::discover(Some(Path::new(path)))?;     // Result<Repository, Error>
let oid  = resolve_revision(&repo, "HEAD")?;                  // Result<ObjectId, Error>
let hex  = oid.to_hex();                                      // String (40 hex / 64 for SHA-256)
```

Verified end-to-end against `git rev-parse HEAD` in `tests/test_smoke.py`.

---

## Provisional symbols with NO direct grit-lib equivalent (summary)

| Provisional pygrit symbol | Status |
| --- | --- |
| `Repository.odb` / `.config` as method accessors | field (`repo.odb`) / binding-layer (`ConfigSet::load`) |
| `Signature` struct (name/email/when/offset) | **deferred — not available**; binding-layer parse of raw ident strings |
| `Reference` rich struct (`.name`/`.target`/`.symbolic_target`/`.peel`) | binding-layer constructed over `list_refs` + `Ref` enum + `resolve_ref` |
| `TreeEntry.kind` | binding-layer (derive from `mode`) |
| `Object` typed views (`Commit`/`Tree`/`Tag`/`Blob` classes) | binding-layer over `parse_commit`/`parse_tree`/`parse_tag` + raw blob bytes |
| `revwalk(...)` as lazy iterator | grit-lib `rev_list` is batch (`Vec<ObjectId>`); lazy iteration is binding-layer |
| `DiffEntry` byte-path fidelity | grit-lib uses `Option<String>` paths — verify non-UTF-8 behavior in Phase 8.5 |
