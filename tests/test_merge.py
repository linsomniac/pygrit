import subprocess


def _git(repo, env, *args):
    return (
        subprocess.run(
            ["git", *args], cwd=repo, env=env, stdout=subprocess.PIPE, check=True
        )
        .stdout.decode()
        .strip()
    )


def _diamond(work, git_env):
    """base -> (A on main) and (B on feat); return (repo_path, oid_A, oid_B, oid_base)."""
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(work)], env=git_env, check=True
    )
    (work / "f.txt").write_text("base\n")
    _git(work, git_env, "add", "-A")
    _git(work, git_env, "commit", "-q", "-m", "base")
    base = _git(work, git_env, "rev-parse", "HEAD")
    (work / "a.txt").write_text("a\n")
    _git(work, git_env, "add", "-A")
    _git(work, git_env, "commit", "-q", "-m", "A")
    oid_a = _git(work, git_env, "rev-parse", "HEAD")
    _git(work, git_env, "checkout", "-q", "-b", "feat", base)
    (work / "b.txt").write_text("b\n")
    _git(work, git_env, "add", "-A")
    _git(work, git_env, "commit", "-q", "-m", "B")
    oid_b = _git(work, git_env, "rev-parse", "HEAD")
    return work, oid_a, oid_b, base


def test_merge_base_matches_git(tmp_path, git_env):
    import pylibgrit

    work, a, b, base = _diamond(tmp_path / "r", git_env)
    repo = pylibgrit.Repository.open(str(work / ".git"))
    mb = repo.merge_base(pylibgrit.ObjectId.from_hex(a), pylibgrit.ObjectId.from_hex(b))
    assert mb is not None
    assert mb.hex == base
    assert mb.hex == _git(work, git_env, "merge-base", a, b)


def test_merge_base_unrelated_is_none(tmp_path, git_env):
    import pylibgrit

    work = tmp_path / "r"
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(work)], env=git_env, check=True
    )
    (work / "x").write_text("x\n")
    _git(work, git_env, "add", "-A")
    _git(work, git_env, "commit", "-q", "-m", "one")
    one = _git(work, git_env, "rev-parse", "HEAD")
    _git(work, git_env, "checkout", "-q", "--orphan", "orphan")
    (work / "y").write_text("y\n")
    _git(work, git_env, "add", "-A")
    _git(work, git_env, "commit", "-q", "-m", "two")
    two = _git(work, git_env, "rev-parse", "HEAD")
    repo = pylibgrit.Repository.open(str(work / ".git"))
    assert (
        repo.merge_base(
            pylibgrit.ObjectId.from_hex(one), pylibgrit.ObjectId.from_hex(two)
        )
        is None
    )
