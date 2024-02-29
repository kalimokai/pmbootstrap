# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import glob
import os
import pytest
import shutil
import sys

import pmb_test  # noqa
import pmb_test.const
import pmb.build.newapkbuild
import pmb.config
import pmb.config.init
import pmb.helpers.logging


@pytest.fixture
def args(tmpdir, request):
    import pmb.parse
    cfg = f"{pmb_test.const.testdata}/channels.cfg"
    sys.argv = ["pmbootstrap.py", "--config-channels", cfg, "init"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)
    return args


def test_newapkbuild(args, monkeypatch, tmpdir):
    testdata = pmb_test.const.testdata

    # Fake functions
    def confirm_true(*nargs):
        return True

    def confirm_false(*nargs):
        return False

    # Preparation
    monkeypatch.setattr(pmb.helpers.cli, "confirm", confirm_false)
    pmb.build.init(args)
    args.aports = tmpdir = str(tmpdir)
    shutil.copy(f"{testdata}/pmaports.cfg", args.aports)
    func = pmb.build.newapkbuild

    # Show the help
    func(args, "main", ["-h"])
    assert glob.glob(f"{tmpdir}/*") == [f"{tmpdir}/pmaports.cfg"]

    # Test package
    pkgname = "testpackage"
    func(args, "main", [pkgname])
    apkbuild_path = tmpdir + "/main/" + pkgname + "/APKBUILD"
    apkbuild = pmb.parse.apkbuild(apkbuild_path)
    assert apkbuild["pkgname"] == pkgname
    assert apkbuild["pkgdesc"] == ""

    # Don't overwrite
    with pytest.raises(RuntimeError) as e:
        func(args, "main", [pkgname])
    assert "Aborted" in str(e.value)

    # Overwrite
    monkeypatch.setattr(pmb.helpers.cli, "confirm", confirm_true)
    pkgdesc = "testdescription"
    func(args, "main", ["-d", pkgdesc, pkgname])
    pmb.helpers.other.cache["apkbuild"] = {}
    apkbuild = pmb.parse.apkbuild(apkbuild_path)
    assert apkbuild["pkgname"] == pkgname
    assert apkbuild["pkgdesc"] == pkgdesc

    # There should be no src folder
    assert not os.path.exists(tmpdir + "/main/" + pkgname + "/src")
