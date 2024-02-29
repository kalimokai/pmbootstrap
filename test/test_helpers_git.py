# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import sys
import pytest
import shutil
import time

import pmb_test  # noqa
import pmb_test.const
import pmb_test.git
import pmb.helpers.git
import pmb.helpers.logging
import pmb.helpers.run


@pytest.fixture
def args(request):
    import pmb.parse
    cfg = f"{pmb_test.const.testdata}/channels.cfg"
    sys.argv = ["pmbootstrap.py", "--config-channels", cfg, "init"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)
    return args


def test_get_path(args):
    func = pmb.helpers.git.get_path
    args.work = "/wrk"
    args.aports = "/tmp/pmaports"

    assert func(args, "aports_upstream") == "/wrk/cache_git/aports_upstream"
    assert func(args, "pmaports") == "/tmp/pmaports"


def test_can_fast_forward(args, tmpdir):
    tmpdir = str(tmpdir)
    func = pmb.helpers.git.can_fast_forward
    branch_origin = "fake-branch-origin"

    def run_git(git_args):
        pmb.helpers.run.user(args, ["git"] + git_args, tmpdir, "stdout")

    # Create test git repo
    run_git(["init", "-b", "master", "."])
    run_git(["commit", "--allow-empty", "-m", "commit on master"])
    run_git(["checkout", "-b", branch_origin])
    run_git(["commit", "--allow-empty", "-m", "commit on branch_origin"])
    run_git(["checkout", "master"])

    # Can fast-forward
    assert func(args, tmpdir, branch_origin) is True

    # Can't fast-forward
    run_git(["commit", "--allow-empty", "-m", "commit on master #2"])
    assert func(args, tmpdir, branch_origin) is False

    # Git command fails
    with pytest.raises(RuntimeError) as e:
        func(args, tmpdir, "invalid-branch")
    assert str(e.value).startswith("Unexpected exit code")


def test_clean_worktree(args, tmpdir):
    tmpdir = str(tmpdir)
    func = pmb.helpers.git.clean_worktree

    def run_git(git_args):
        pmb.helpers.run.user(args, ["git"] + git_args, tmpdir, "stdout")

    # Create test git repo
    run_git(["init", "-b", "master", "."])
    run_git(["commit", "--allow-empty", "-m", "commit on master"])

    assert func(args, tmpdir) is True
    pmb.helpers.run.user(args, ["touch", "test"], tmpdir)
    assert func(args, tmpdir) is False


def test_get_upstream_remote(args, monkeypatch, tmpdir):
    tmpdir = str(tmpdir)
    func = pmb.helpers.git.get_upstream_remote
    name_repo = "test"

    # Override get_path()
    def get_path(args, name_repo):
        return tmpdir
    monkeypatch.setattr(pmb.helpers.git, "get_path", get_path)

    # Override pmb.config.git_repos
    url = "https://postmarketos.org/get-upstream-remote-test.git"
    git_repos = {"test": url}
    monkeypatch.setattr(pmb.config, "git_repos", git_repos)

    def run_git(git_args):
        pmb.helpers.run.user(args, ["git"] + git_args, tmpdir, "stdout")

    # Create git repo
    run_git(["init", "-b", "master", "."])
    run_git(["commit", "--allow-empty", "-m", "commit on master"])

    # No upstream remote
    with pytest.raises(RuntimeError) as e:
        func(args, name_repo)
    assert "could not find remote name for URL" in str(e.value)

    run_git(["remote", "add", "hello", url])
    assert func(args, name_repo) == "hello"


def test_parse_channels_cfg(args):
    exp = {"meta": {"recommended": "edge"},
           "channels": {"edge": {"description": "Rolling release channel",
                                 "branch_pmaports": "master",
                                 "branch_aports": "master",
                                 "mirrordir_alpine": "edge"},
                        "v20.05": {"description": "For workgroups",
                                   "branch_pmaports": "v20.05",
                                   "branch_aports": "3.11-stable",
                                   "mirrordir_alpine": "v3.11"},
                        "v21.03": {"description": "Second beta release",
                                   "branch_pmaports": "v21.03",
                                   "branch_aports": "3.13-stable",
                                   "mirrordir_alpine": "v3.13"}}}
    assert pmb.helpers.git.parse_channels_cfg(args) == exp


def test_pull_non_existing(args):
    assert pmb.helpers.git.pull(args, "non-existing-repo-name") == 1


def test_pull(args, monkeypatch, tmpdir):
    """ Test pmb.helpers.git.pull """
    path, run_git = pmb_test.git.prepare_tmpdir(args, monkeypatch, tmpdir)

    # Not on official branch
    func = pmb.helpers.git.pull
    name_repo = "test"
    run_git(["checkout", "-b", "inofficial-branch"])
    assert func(args, name_repo) == -1

    # Workdir is not clean
    run_git(["checkout", "master"])
    shutil.copy(__file__, path + "/test.py")
    assert func(args, name_repo) == -2
    os.unlink(path + "/test.py")

    # Tracking different remote
    assert func(args, name_repo) == -3

    # Let master track origin/master
    run_git(["checkout", "-b", "temp"])
    run_git(["branch", "-D", "master"])
    run_git(["checkout", "-b", "master", "--track", "origin/master"])

    # Already up to date
    assert func(args, name_repo) == 2

    # Can't fast-forward
    run_git(["commit", "--allow-empty", "-m", "test"])
    assert func(args, name_repo) == -4

    # Fast-forward successfully
    run_git(["reset", "--hard", "origin/master"])
    run_git(["commit", "--allow-empty", "-m", "new"], "remote")
    assert func(args, name_repo) == 0


def test_is_outdated(tmpdir, monkeypatch):
    func = pmb.helpers.git.is_outdated

    # Override time.time(): now is "100"
    def fake_time():
        return 100.0
    monkeypatch.setattr(time, "time", fake_time)

    # Create .git/FETCH_HEAD
    path = str(tmpdir)
    os.mkdir(path + "/.git")
    fetch_head = path + "/.git/FETCH_HEAD"
    open(fetch_head, "w").close()

    # Set mtime to 90
    os.utime(fetch_head, times=(0, 90))

    # Outdated (date_outdated: 90)
    monkeypatch.setattr(pmb.config, "git_repo_outdated", 10)
    assert func(path) is True

    # Not outdated (date_outdated: 89)
    monkeypatch.setattr(pmb.config, "git_repo_outdated", 11)
    assert func(path) is False
