# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import sys
import pytest
import shutil
import filecmp

import pmb_test
import pmb_test.git
import pmb_test.const
import pmb.aportgen
import pmb.aportgen.core
import pmb.config
import pmb.helpers.logging


@pytest.fixture
def args(tmpdir, request):
    import pmb.parse
    cfg = f"{pmb_test.const.testdata}/channels.cfg"
    sys.argv = ["pmbootstrap.py", "--config-channels", cfg, "chroot"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    args.fork_alpine = False
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)
    return args


def test_aportgen_compare_output(args, tmpdir, monkeypatch):
    # Fake aports folder in tmpdir
    tmpdir = str(tmpdir)
    pmb_test.git.copy_dotgit(args, tmpdir)
    args.aports = tmpdir
    os.mkdir(tmpdir + "/cross")
    testdata = pmb_test.const.testdata + "/aportgen"

    # Override get_upstream_aport() to point to testdata
    def func(args, upstream_path, arch=None):
        return testdata + "/aports/main/" + upstream_path
    monkeypatch.setattr(pmb.aportgen.core, "get_upstream_aport", func)

    # Run aportgen and compare output
    pkgnames = ["gcc-armhf"]
    for pkgname in pkgnames:
        pmb.aportgen.generate(args, pkgname)
        path_new = args.aports + "/cross/" + pkgname + "/APKBUILD"
        path_old = testdata + "/pmaports/cross/" + pkgname + "/APKBUILD"
        assert os.path.exists(path_new)
        assert filecmp.cmp(path_new, path_old, False)


def test_aportgen_fork_alpine_compare_output(args, tmpdir, monkeypatch):
    # Fake aports folder in tmpdir
    tmpdir = str(tmpdir)
    pmb_test.git.copy_dotgit(args, tmpdir)
    args.aports = tmpdir
    os.mkdir(tmpdir + "/temp")
    testdata = pmb_test.const.testdata + "/aportgen"
    args.fork_alpine = True

    # Override get_upstream_aport() to point to testdata
    def func(args, upstream_path, arch=None):
        return testdata + "/aports/main/" + upstream_path
    monkeypatch.setattr(pmb.aportgen.core, "get_upstream_aport", func)

    # Run aportgen and compare output
    pkgname = "binutils"
    pmb.aportgen.generate(args, pkgname)
    path_new = args.aports + "/temp/" + pkgname + "/APKBUILD"
    path_old = testdata + "/pmaports/temp/" + pkgname + "/APKBUILD"
    assert os.path.exists(path_new)
    assert filecmp.cmp(path_new, path_old, False)


def test_aportgen(args, tmpdir):
    # Fake aports folder in tmpdir
    testdata = pmb_test.const.testdata
    tmpdir = str(tmpdir)
    pmb_test.git.copy_dotgit(args, tmpdir)
    args.aports = tmpdir
    shutil.copy(f"{testdata}/pmaports.cfg", args.aports)
    os.mkdir(tmpdir + "/cross")

    # Create aportgen folder -> code path where it still exists
    pmb.helpers.run.user(args, ["mkdir", "-p", args.work + "/aportgen"])

    # Generate all valid packages (gcc twice -> different code path)
    pkgnames = ["musl-armv7",
                "busybox-static-armv7",
                "gcc-armv7",
                "gcc-armv7"]
    for pkgname in pkgnames:
        pmb.aportgen.generate(args, pkgname)


def test_aportgen_invalid_generator(args):
    with pytest.raises(ValueError) as e:
        pmb.aportgen.generate(args, "pkgname-with-no-generator")
    assert "No generator available" in str(e.value)


def test_aportgen_get_upstream_aport(args, monkeypatch):
    # Fake pmb.parse.apkbuild()
    def fake_apkbuild(*args, **kwargs):
        return apkbuild
    monkeypatch.setattr(pmb.parse, "apkbuild", fake_apkbuild)

    # Fake pmb.parse.apkindex.package()
    def fake_package(*args, **kwargs):
        return package
    monkeypatch.setattr(pmb.parse.apkindex, "package", fake_package)

    # Equal version
    func = pmb.aportgen.core.get_upstream_aport
    upstream = "gcc"
    upstream_full = args.work + "/cache_git/aports_upstream/main/" + upstream
    apkbuild = {"pkgver": "2.0", "pkgrel": "0"}
    package = {"version": "2.0-r0"}
    assert func(args, upstream) == upstream_full

    # APKBUILD < binary
    apkbuild = {"pkgver": "1.0", "pkgrel": "0"}
    package = {"version": "2.0-r0"}
    assert func(args, upstream) == upstream_full

    # APKBUILD > binary
    apkbuild = {"pkgver": "3.0", "pkgrel": "0"}
    package = {"version": "2.0-r0"}
    assert func(args, upstream) == upstream_full
