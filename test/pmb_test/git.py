# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
""" Common code for git tests """
import os

import pmb.helpers.git
import pmb.helpers.run
import shutil


def prepare_tmpdir(args, monkeypatch, tmpdir):
    """ Prepare git repositories in tmpdir, and override related functions.

        Git repositories:
        * local: like local clone of pmaports.git
        * remote: emulate a remote repository that we can add to "local", so
                  we can pass the tracking-remote tests in pmb.helpers.git.pull
        * remote2: unexpected remote that pmbootstrap can complain about

        Function overrides:
        * pmb.helpers.git.get_path: always return path to "local" repo
        * pmb.helpers.git.get_upstream_remote: always return "origin"

        :returns: path_local, run_git
                  * path_local: path to "local" repo
                  * run_git(git_args, repo="local"): convenience function """
    # Directory structure
    tmpdir = str(tmpdir)
    path_local = tmpdir + "/local"
    path_remote = tmpdir + "/remote"
    path_remote2 = tmpdir + "/remote2"
    os.makedirs(path_local)
    os.makedirs(path_remote)
    os.makedirs(path_remote2)

    def run_git(git_args, repo="local"):
        path = tmpdir + "/" + repo
        pmb.helpers.run.user(args, ["git"] + git_args, path, "stdout", output_return=True)

    # Remote repos
    run_git(["init", "-b", "master", "."], "remote")
    run_git(["commit", "--allow-empty", "-m", "commit: remote"], "remote")
    run_git(["init", "-b", "master", "."], "remote2")
    run_git(["commit", "--allow-empty", "-m", "commit: remote2"], "remote2")

    # Local repo (with master -> origin2/master)
    run_git(["init", "-b", "master", "."])
    run_git(["remote", "add", "-f", "origin", path_remote])
    run_git(["remote", "add", "-f", "origin2", path_remote2])
    run_git(["checkout", "-b", "master", "--track", "origin2/master"])

    # Override get_path()
    def get_path(args, name_repo):
        return path_local
    monkeypatch.setattr(pmb.helpers.git, "get_path", get_path)

    # Override get_upstream_remote()
    def get_u_r(args, name_repo):
        return "origin"
    monkeypatch.setattr(pmb.helpers.git, "get_upstream_remote", get_u_r)

    return path_local, run_git

def copy_dotgit(args, tmpdir):
    shutil.copytree(args.aports + "/.git", tmpdir + "/.git", ignore_dangling_symlinks=True)
