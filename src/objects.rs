//! Python wrappers over grit-lib object-model primitives (`ObjectId`).

use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::sync::Arc;

use pyo3::basic::CompareOp;
use pyo3::prelude::*;
use pyo3::sync::GILOnceCell;
use pyo3::types::PyBytes;

use crate::error::map_err;

// AIDEV-NOTE: We wrap grit-lib's own `ObjectId` (which derives
// Clone/Copy/Eq/Ord/Hash and provides to_hex/as_bytes/from_hex/from_bytes/algo)
// rather than reimplementing hex parsing — grit-lib owns the canonical SHA-1/256
// width logic. `frozen` makes the Python object immutable, matching the Copy oid.
#[pyclass(frozen, module = "pygrit._pygrit")]
#[derive(Clone)]
pub struct ObjectId {
    pub(crate) inner: grit_lib::objects::ObjectId,
}

#[pymethods]
impl ObjectId {
    /// Parses an `ObjectId` from a 40- (SHA-1) or 64-char (SHA-256) hex string.
    #[staticmethod]
    fn from_hex(hex: &str) -> PyResult<Self> {
        grit_lib::objects::ObjectId::from_hex(hex)
            .map(|inner| Self { inner })
            .map_err(map_err)
    }

    /// The lowercase hex digest (40 chars for SHA-1, 64 for SHA-256).
    #[getter]
    fn hex(&self) -> String {
        self.inner.to_hex()
    }

    /// The raw digest bytes (20 for SHA-1, 32 for SHA-256).
    #[getter]
    fn raw<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, self.inner.as_bytes())
    }

    /// The hash algorithm name (`"sha1"` or `"sha256"`), inferred from length.
    #[getter]
    fn hash_algorithm(&self) -> &'static str {
        self.inner.algo().name()
    }

    fn __richcmp__(&self, other: &ObjectId, op: CompareOp) -> bool {
        match op {
            CompareOp::Eq => self.inner == other.inner,
            CompareOp::Ne => self.inner != other.inner,
            _ => false,
        }
    }

    fn __hash__(&self) -> u64 {
        let mut h = DefaultHasher::new();
        self.inner.hash(&mut h);
        h.finish()
    }

    fn __repr__(&self) -> String {
        format!("ObjectId('{}')", self.inner.to_hex())
    }
}

// AIDEV-NOTE: `inner()` is used by the odb read/exists bindings (task 2.6); `from_inner`
// is now consumed by `Commit` (tree/parents) in task 2.7. Both have callers, so no
// dead-code allow is needed.
impl ObjectId {
    pub fn from_inner(inner: grit_lib::objects::ObjectId) -> Self {
        Self { inner }
    }

    pub fn inner(&self) -> grit_lib::objects::ObjectId {
        self.inner
    }
}

// AIDEV-NOTE: Decode bytes using Python's own codec machinery (full encoding + errors
// support: utf-8/latin-1/.../strict/replace/surrogateescape) rather than reimplementing
// codecs in Rust. Shared by Signature.name_str/email_str and Commit.message().
fn decode_bytes(data: &[u8], encoding: &str, errors: &str) -> PyResult<String> {
    Python::with_gil(|py| {
        PyBytes::new(py, data)
            .call_method1("decode", (encoding, errors))?
            .extract::<String>()
    })
}

// AIDEV-NOTE: grit-lib has NO Signature struct — author/committer are raw Git-wire idents
// (`Name <email> <unix-seconds> <+HHMM>`). This binding-layer type splits name/email from
// the RAW header bytes (preserving non-UTF-8 fidelity, design §5) and derives the time via
// grit_lib::ident::parse_signature_times on the decoded String form.
#[pyclass(frozen, module = "pygrit._pygrit")]
pub struct Signature {
    name: Vec<u8>,
    email: Vec<u8>,
    when_secs: i64,
    when_offset_secs: i32,
}

#[pymethods]
impl Signature {
    /// The identity name as raw bytes (non-UTF-8 fidelity; design §5).
    #[getter]
    fn name<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.name)
    }

    /// The identity email as raw bytes.
    #[getter]
    fn email<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.email)
    }

    /// `(unix_seconds, utc_offset_seconds)`. Offset is signed (e.g. `+0530` → `19800`).
    #[getter]
    fn when(&self) -> (i64, i32) {
        (self.when_secs, self.when_offset_secs)
    }

    /// The name decoded as UTF-8 (strict). Raises `UnicodeDecodeError` on non-UTF-8.
    #[getter]
    fn name_str(&self) -> PyResult<String> {
        decode_bytes(&self.name, "utf-8", "strict")
    }

    /// The email decoded as UTF-8 (strict). Raises `UnicodeDecodeError` on non-UTF-8.
    #[getter]
    fn email_str(&self) -> PyResult<String> {
        decode_bytes(&self.email, "utf-8", "strict")
    }
}

impl Signature {
    // AIDEV-NOTE: Git ident wire format is `Name <email> <unix-seconds> <+HHMM>`. We split
    // name/email from the RAW bytes for non-UTF-8 fidelity; the time comes from
    // grit_lib::ident::parse_signature_times on the decoded String form (it parses the
    // trailing `<unix> <+HHMM>`, returning tz_offset_secs ALREADY in seconds). We use the
    // LAST `<`/`>` pair so a literal `<` inside a name does not fool the split. If the time
    // parse returns None (corrupt/missing/overflow date), we fall back to (0, 0) — a
    // non-fatal read of a malformed signature, matching Git's sentinel handling.
    pub fn parse(raw: &[u8], ident_str: &str) -> Self {
        let (name, email) = split_name_email(raw);
        let (when_secs, when_offset_secs) = match grit_lib::ident::parse_signature_times(ident_str)
        {
            Some(t) => (t.unix_seconds, t.tz_offset_secs as i32),
            None => (0, 0),
        };
        Self {
            name,
            email,
            when_secs,
            when_offset_secs,
        }
    }
}

// AIDEV-NOTE: Split `Name <email> ...` from raw ident bytes. We locate the LAST `<` and the
// FIRST `>` at-or-after it (robust to a literal `<` inside a name). name = bytes before that
// `<` with exactly one trailing space trimmed; email = bytes strictly between `<` and `>`.
// On a malformed ident with no `<`/`>` pair, name = full input, email = empty.
fn split_name_email(raw: &[u8]) -> (Vec<u8>, Vec<u8>) {
    if let Some(lt) = raw.iter().rposition(|&b| b == b'<') {
        if let Some(rel_gt) = raw[lt + 1..].iter().position(|&b| b == b'>') {
            let gt = lt + 1 + rel_gt;
            let mut name_end = lt;
            if name_end > 0 && raw[name_end - 1] == b' ' {
                name_end -= 1;
            }
            let name = raw[..name_end].to_vec();
            let email = raw[lt + 1..gt].to_vec();
            return (name, email);
        }
    }
    (raw.to_vec(), Vec::new())
}

// AIDEV-NOTE: `Commit` is a binding-layer typed view over grit_lib::objects::parse_commit.
// `frozen` (immutable). author/committer are wrapped Py<Signature>; message is the EXACT
// raw body bytes (see from_bytes). tree/parents are pygrit ObjectIds.
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
    /// The tree this commit points to.
    #[getter]
    fn tree(&self) -> ObjectId {
        self.tree.clone()
    }

    /// Parent commit ids (empty for a root commit, 1 normally, 2+ for merges).
    #[getter]
    fn parents(&self) -> Vec<ObjectId> {
        self.parents.clone()
    }

    /// The author `Signature`.
    #[getter]
    fn author(&self, py: Python<'_>) -> Py<Signature> {
        self.author.clone_ref(py)
    }

    /// The committer `Signature`.
    #[getter]
    fn committer(&self, py: Python<'_>) -> Py<Signature> {
        self.committer.clone_ref(py)
    }

    /// The raw commit message bytes (the object body after the header blank line).
    #[getter]
    fn message_bytes<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.message)
    }

    /// The commit message decoded to `str` (default UTF-8/strict; caller-overridable).
    #[pyo3(signature = (encoding="utf-8", errors="strict"))]
    fn message(&self, encoding: &str, errors: &str) -> PyResult<String> {
        decode_bytes(&self.message, encoding, errors)
    }
}

impl Commit {
    // AIDEV-NOTE: Parse a commit from the raw object payload (an odb read's `.data`).
    // tree/parents come straight from CommitData. author/committer Signatures are built
    // from the RAW header bytes (author_raw/committer_raw) for the name/email split, plus
    // the decoded String (author/committer) for time parsing.
    //
    // MESSAGE NEWLINE CONTRACT: CommitData.message is the EXACT decoded body after the
    // header blank line, INCLUDING its trailing newline. grit-lib sets raw_message to the
    // verbatim body bytes whenever it is non-empty AND (non-UTF-8 encoding OR not valid
    // UTF-8 OR not LF-terminated); otherwise raw_message is None and message.into_bytes()
    // IS the verbatim body. So `raw_message.unwrap_or(message.into_bytes())` reproduces the
    // exact body. We surface those bytes UNMODIFIED — so `message_bytes` equals the commit
    // payload's message section, which equals `git log --format=%B` MINUS the single
    // trailing newline git appends to its own output (verified in tests/test_objects.py).
    pub fn from_bytes(py: Python<'_>, data: &[u8]) -> PyResult<Self> {
        let c = grit_lib::objects::parse_commit(data).map_err(map_err)?;
        let tree = ObjectId::from_inner(c.tree);
        let parents = c.parents.into_iter().map(ObjectId::from_inner).collect();
        let author = Py::new(py, Signature::parse(&c.author_raw, &c.author))?;
        let committer = Py::new(py, Signature::parse(&c.committer_raw, &c.committer))?;
        let message = c.raw_message.unwrap_or_else(|| c.message.into_bytes());
        Ok(Self {
            tree,
            parents,
            author,
            committer,
            message,
        })
    }
}

// AIDEV-NOTE: ObjectKind is a Python enum.IntEnum defined in python/pygrit/__init__.py.
// Native PyO3 enums lack .name and type-iteration, so kind getters return the IntEnum
// member instead. We cache the class once and construct members by integer value.
// The discriminants here MUST match the IntEnum values in __init__.py (asserted by a test).
static OBJECT_KIND_CLS: GILOnceCell<Py<PyAny>> = GILOnceCell::new();

fn object_kind_discriminant(k: grit_lib::objects::ObjectKind) -> i32 {
    match k {
        grit_lib::objects::ObjectKind::Commit => 0,
        grit_lib::objects::ObjectKind::Tree => 1,
        grit_lib::objects::ObjectKind::Blob => 2,
        grit_lib::objects::ObjectKind::Tag => 3,
    }
}

/// Convert a grit-lib object kind into the public `pygrit.ObjectKind` IntEnum member.
pub fn kind_to_py(py: Python<'_>, k: grit_lib::objects::ObjectKind) -> PyResult<Py<PyAny>> {
    let cls = OBJECT_KIND_CLS.get_or_try_init(py, || -> PyResult<Py<PyAny>> {
        Ok(py.import("pygrit")?.getattr("ObjectKind")?.unbind())
    })?;
    let member = cls.bind(py).call1((object_kind_discriminant(k),))?;
    Ok(member.unbind())
}

// AIDEV-NOTE: `Object` is the value `Odb::read` returns, surfaced to Python. It is
// `frozen` (immutable). `kind` is stored as the already-constructed pygrit.ObjectKind
// IntEnum member (built once at read time via kind_to_py) so the getter can hand back
// the singleton (identity-comparable: `obj.kind is pygrit.ObjectKind.BLOB`). `data` is
// an `Arc<[u8]>` so the payload can later be shared with typed views without copying.
#[pyclass(frozen, module = "pygrit._pygrit")]
pub struct Object {
    id: ObjectId,
    kind: Py<PyAny>,
    data: Arc<[u8]>,
}

#[pymethods]
impl Object {
    #[getter]
    fn id(&self) -> ObjectId {
        self.id.clone()
    }

    #[getter]
    fn kind(&self, py: Python<'_>) -> Py<PyAny> {
        self.kind.clone_ref(py)
    }

    #[getter]
    fn data<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.data)
    }
}

impl Object {
    pub fn new(id: ObjectId, kind: Py<PyAny>, data: Arc<[u8]>) -> Self {
        Self { id, kind, data }
    }
}
