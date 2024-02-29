# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
""" Test pmb/helpers/status.py """
import os
import pytest
import shutil
import sys

import pmb_test
import pmb_test.git
import pmb.config
import pmb.config.workdir


@pytest.fixture
def args(request):
    import pmb.parse
    sys.argv = ["pmbootstrap", "init"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)
    return args


def test_pmbootstrap_status(args, tmpdir):
    """ High level testing of 'pmbootstrap status': run it twice, once with
        a fine workdir, and once where one check is failing. """
    # Prepare empty workdir
    work = str(tmpdir)
    with open(work + "/version", "w") as handle:
        handle.write(str(pmb.config.work_version))

    # "pmbootstrap status" succeeds (pmb.helpers.run.user verifies exit 0)
    pmbootstrap = pmb.config.pmb_src + "/pmbootstrap.py"
    pmb.helpers.run.user(args, [pmbootstrap, "-w", work, "status",
                                "--details"])

    # Mark chroot_native as outdated
    with open(work + "/workdir.cfg", "w") as handle:
        handle.write("[chroot-init-dates]\nnative = 1234\n")

    # "pmbootstrap status" fails
    ret = pmb.helpers.run.user(args, [pmbootstrap, "-w", work, "status"],
                               check=False)
    assert ret == 1


def test_print_checks_git_repo(args, monkeypatch, tmpdir):
    """ Test pmb.helpers.status.print_checks_git_repo """
    path, run_git = pmb_test.git.prepare_tmpdir(args, monkeypatch, tmpdir)

    # Not on official branch
    func = pmb.helpers.status.print_checks_git_repo
    name_repo = "test"
    run_git(["checkout", "-b", "inofficial-branch"])
    status, _ = func(args, name_repo)
    assert status == -1

    # Workdir is not clean
    run_git(["checkout", "master"])
    shutil.copy(__file__, path + "/test.py")
    status, _ = func(args, name_repo)
    assert status == -2
    os.unlink(path + "/test.py")

    # Tracking different remote
    status, _ = func(args, name_repo)
    assert status == -3

    # Let master track origin/master
    run_git(["checkout", "-b", "temp"])
    run_git(["branch", "-D", "master"])
    run_git(["checkout", "-b", "master", "--track", "origin/master"])

    # Not up to date
    run_git(["commit", "--allow-empty", "-m", "new"], "remote")
    run_git(["fetch"])
    status, _ = func(args, name_repo)
    assert status == -4

    # Up to date
    run_git(["pull"])
    status, _ = func(args, name_repo)
    assert status == 0

    # Outdated remote information
    def is_outdated(path):
        return True
    monkeypatch.setattr(pmb.helpers.git, "is_outdated", is_outdated)
    status, _ = func(args, name_repo)
    assert status == -5
