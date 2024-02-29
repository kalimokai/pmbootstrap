# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import sys
import pytest

import pmb_test  # noqa
import pmb.aportgen
import pmb.config
import pmb.helpers.frontend
import pmb.helpers.logging
import pmb.helpers.run
import pmb.helpers.run_core


@pytest.fixture
def args(tmpdir, request):
    import pmb.parse
    sys.argv = ["pmbootstrap.py", "chroot"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)
    return args


def change_config(monkeypatch, path_config, key, value):
    args = args_patched(monkeypatch, ["pmbootstrap.py", "-c", path_config,
                                      "config", key, value])
    pmb.helpers.frontend.config(args)


def args_patched(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", argv)
    return pmb.parse.arguments()


def test_config_user(args, tmpdir, monkeypatch):
    # Temporary paths
    tmpdir = str(tmpdir)
    path_work = tmpdir + "/work"
    path_config = tmpdir + "/pmbootstrap.cfg"

    # Generate default config (only uses tmpdir)
    cmd = pmb.helpers.run_core.flat_cmd(["./pmbootstrap.py",
                                         "-c", path_config,
                                         "-w", path_work,
                                         "--aports", args.aports,
                                         "init"])
    pmb.helpers.run.user(args, ["sh", "-c", "yes '' | " + cmd],
                         pmb.config.pmb_src)

    # Load and verify default config
    argv = ["pmbootstrap.py", "-c", path_config, "config"]
    args_default = args_patched(monkeypatch, argv)
    assert args_default.work == path_work

    # Modify jobs count
    change_config(monkeypatch, path_config, "jobs", "9000")
    assert args_patched(monkeypatch, argv).jobs == "9000"

    # Override jobs count via commandline (-j)
    argv_jobs = ["pmbootstrap.py", "-c", path_config, "-j", "1000", "config"]
    assert args_patched(monkeypatch, argv_jobs).jobs == "1000"

    # Override a config option with something that evaluates to false
    argv_empty = ["pmbootstrap.py", "-c", path_config, "-w", "",
                  "--details-to-stdout", "config"]
    assert args_patched(monkeypatch, argv_empty).work == ""
