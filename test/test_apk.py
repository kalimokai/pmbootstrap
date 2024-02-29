# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import fnmatch
import pytest
import sys

import pmb_test  # noqa
import pmb.build
import pmb.chroot.apk


@pytest.fixture
def args(tmpdir, request):
    import pmb.parse
    sys.argv = ["pmbootstrap.py", "init"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)
    return args


def test_install_build(monkeypatch, args):
    func = pmb.chroot.apk.install_build
    ret_apkindex_package = None

    def fake_build_package(args, package, arch):
        return "build-pkg"
    monkeypatch.setattr(pmb.build, "package", fake_build_package)

    def fake_apkindex_package(args, package, arch, must_exist):
        return ret_apkindex_package
    monkeypatch.setattr(pmb.parse.apkindex, "package", fake_apkindex_package)

    package = "hello-world"
    arch = "x86_64"

    # invoked as pmb install, build_pkgs_on_install disabled
    args.action = "install"
    args.build_pkgs_on_install = False
    with pytest.raises(RuntimeError) as e:
        func(args, package, arch)
    assert "no binary package found" in str(e.value)

    # invoked as pmb install, build_pkgs_on_install disabled, binary exists
    args.action = "install"
    args.build_pkgs_on_install = False
    ret_apkindex_package = {"pkgname": "hello-world"}
    assert func(args, package, arch) is None

    # invoked as pmb install, build_pkgs_on_install enabled
    args.action = "install"
    args.build_pkgs_on_install = True
    assert func(args, package, arch) == "build-pkg"

    # invoked as not pmb install
    args.action = "chroot"
    args.build_pkgs_on_install = False
    assert func(args, package, arch) == "build-pkg"


def test_packages_split_to_add_del():
    packages = ["hello", "!test", "hello2", "test2", "!test3"]

    to_add, to_del = pmb.chroot.apk.packages_split_to_add_del(packages)
    assert to_add == ["hello", "hello2", "test2"]
    assert to_del == ["test", "test3"]


def test_packages_get_locally_built_apks(monkeypatch, args):
    args.assume_yes = True

    arch = pmb.config.arch_native
    packages = ["hello-world",  # will exist in repo and locally
                "postmarketos-base",  # will exist in repo only
                "package-that-does-not-exist"]  # will not exist at all

    pmb.chroot.zap(args, pkgs_local=True)
    pmb.build.package(args, "hello-world", force=True)

    ret = pmb.chroot.apk.packages_get_locally_built_apks(args, packages, arch)
    assert len(ret) == 1
    assert fnmatch.fnmatch(ret[0], "*/hello-world-*.apk")


def test_install_run_apk(monkeypatch, args):
    global cmds_progress
    global cmds

    func = pmb.chroot.apk.install_run_apk
    suffix = "chroot_native"

    def fake_chroot_root(args, command, suffix):
        global cmds
        cmds += [command]
    monkeypatch.setattr(pmb.chroot, "root", fake_chroot_root)

    def fake_apk_progress(args, command, chroot, suffix):
        global cmds_progress
        cmds_progress += [command]
    monkeypatch.setattr(pmb.helpers.apk, "apk_with_progress", fake_apk_progress)

    def reset_cmds():
        global cmds_progress, cmds
        cmds = []
        cmds_progress = []

    # Simple add
    reset_cmds()
    to_add = ["postmarketos-base", "device-ppp"]
    to_add_local = []
    to_del = []
    func(args, to_add, to_add_local, to_del, suffix)
    assert cmds_progress == [["apk", "add", "postmarketos-base", "device-ppp",
                              "--no-interactive"]]
    assert cmds == []

    # Add and delete
    reset_cmds()
    to_add = ["postmarketos-base", "device-ppp"]
    to_add_local = []
    to_del = ["osk-sdl"]
    func(args, to_add, to_add_local, to_del, suffix)
    assert cmds_progress == [["apk", "add", "postmarketos-base", "device-ppp",
                              "--no-interactive"]]
    assert cmds == [["apk", "--no-progress", "del", "osk-sdl",
                     "--no-interactive"]]

    # Add with local package
    reset_cmds()
    to_add = ["postmarketos-base", "device-ppp"]
    to_add_local = ["/tmp/device-ppp.apk"]
    to_del = []
    func(args, to_add, to_add_local, to_del, suffix)
    assert cmds_progress == [["apk", "add", "postmarketos-base", "device-ppp",
                              "--no-interactive"]]
    assert cmds == [["apk", "--no-progress", "add", "-u", "--virtual",
                     ".pmbootstrap", "/tmp/device-ppp.apk", "--no-interactive"],
                    ["apk", "--no-progress", "del", ".pmbootstrap",
                     "--no-interactive"]]

    # Add with --no-network
    reset_cmds()
    args.offline = True
    to_add = ["hello-world"]
    to_add_local = []
    to_del = []
    func(args, to_add, to_add_local, to_del, suffix)
    assert cmds_progress == [["apk", "--no-network", "add", "hello-world",
                              "--no-interactive"]]
    assert cmds == []

    # Package name starting with '-'
    reset_cmds()
    to_add = ["hello-world", "--allow-untrusted"]
    to_add_local = []
    to_del = []
    with pytest.raises(ValueError) as e:
        func(args, to_add, to_add_local, to_del, suffix)
    assert "Invalid package name" in str(e.value)
