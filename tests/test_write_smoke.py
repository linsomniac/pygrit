import subprocess


def test_build_a_commit_end_to_end(tmp_path, git_env):
    import pylibgrit

    repo = tmp_path / "r"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-q", "-b", "main", str(repo)], env=git_env, check=True
    )
    pg = pylibgrit.Repository.open(str(repo / ".git"))

    blob = pg.odb.write(pylibgrit.ObjectKind.BLOB, b"hello\n")
    idx = pg.index()
    idx.add(b"greeting.txt", blob, 0o100644)
    idx.write()
    tree = idx.write_tree()
    sig = pylibgrit.Signature(b"Ada", b"ada@x.io", (1718000000, 0))
    commit = pg.create_commit(
        tree, parents=[], author=sig, committer=sig, message=b"init\n"
    )
    pg.update_ref(
        b"refs/heads/main", commit, create=True, message=b"commit: init", signer=sig
    )

    got = (
        subprocess.run(
            ["git", "rev-parse", "refs/heads/main"],
            cwd=repo,
            env=git_env,
            stdout=subprocess.PIPE,
            check=True,
        )
        .stdout.decode()
        .strip()
    )
    assert got == commit.hex
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", commit.hex],
        cwd=repo,
        env=git_env,
        stdout=subprocess.PIPE,
        check=True,
    ).stdout.decode()
    assert "greeting.txt" in listing
