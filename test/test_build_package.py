# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
""" Tests all functions from pmb.build._package """
import datetime
import glob
import os
import pytest
import shutil
import sys

import pmb_test  # noqa
import pmb_test.git
import pmb.build
import pmb.build._package
import pmb.config
import pmb.config.init
import pmb.helpers.logging


@pytest.fixture
def args(tmpdir, request):
    import pmb.parse
    sys.argv = ["pmbootstrap", "init"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)
    return args


def return_none(*args, **kwargs):
    return None


def return_string(*args, **kwargs):
    return "some/random/path.apk"


def return_true(*args, **kwargs):
    return True


def return_false(*args, **kwargs):
    return False


def return_fake_build_depends(*args, **kwargs):
    """
    Fake return value for pmb.build._package.build_depends:
    depends: ["alpine-base"], depends_built: []
    """
    return (["alpine-base"], [])


def args_patched(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", argv)
    return pmb.parse.arguments()


def test_skip_already_built(args):
    func = pmb.build._package.skip_already_built
    assert pmb.helpers.other.cache["built"] == {}
    assert func("test-package", "armhf") is False
    assert pmb.helpers.other.cache["built"] == {"armhf": ["test-package"]}
    assert func("test-package", "armhf") is True


def test_get_apkbuild(args):
    func = pmb.build._package.get_apkbuild

    # Valid aport
    pkgname = "postmarketos-base"
    assert func(args, pkgname, "x86_64")["pkgname"] == pkgname

    # Valid binary package
    assert func(args, "alpine-base", "x86_64") is None

    # Invalid package
    with pytest.raises(RuntimeError) as e:
        func(args, "invalid-package-name", "x86_64")
    assert "Could not find" in str(e.value)


def test_check_build_for_arch(monkeypatch, args):
    # Fake APKBUILD data
    apkbuild = {"pkgname": "testpkgname"}

    def fake_helpers_pmaports_get(args, pkgname):
        return apkbuild
    monkeypatch.setattr(pmb.helpers.pmaports, "get", fake_helpers_pmaports_get)

    # pmaport with arch exists
    func = pmb.build._package.check_build_for_arch
    apkbuild["arch"] = ["armhf"]
    assert func(args, "testpkgname", "armhf") is True
    apkbuild["arch"] = ["noarch"]
    assert func(args, "testpkgname", "armhf") is True
    apkbuild["arch"] = ["all"]
    assert func(args, "testpkgname", "armhf") is True

    # No binary package exists and can't build it
    apkbuild["arch"] = ["x86_64"]
    with pytest.raises(RuntimeError) as e:
        func(args, "testpkgname", "armhf")
    assert "Can't build" in str(e.value)

    # pmaport can't be built for x86_64, but binary package exists in Alpine
    apkbuild = {"pkgname": "mesa",
                "arch": "armhf",
                "pkgver": "9999",
                "pkgrel": "0"}
    assert func(args, "mesa", "x86_64") is False


def test_get_depends(monkeypatch):
    func = pmb.build._package.get_depends
    apkbuild = {"pkgname": "test", "depends": ["a"], "makedepends": ["c", "b"],
                "checkdepends": "e", "subpackages": {"d": None}, "options": []}

    # Depends + makedepends
    args = args_patched(monkeypatch, ["pmbootstrap", "build", "test"])
    assert func(args, apkbuild) == ["a", "b", "c", "e"]
    args = args_patched(monkeypatch, ["pmbootstrap", "install"])
    assert func(args, apkbuild) == ["a", "b", "c", "e"]

    # Ignore depends (-i)
    args = args_patched(monkeypatch, ["pmbootstrap", "build", "-i", "test"])
    assert func(args, apkbuild) == ["b", "c", "e"]

    # Package depends on its own subpackage
    apkbuild["makedepends"] = ["d"]
    args = args_patched(monkeypatch, ["pmbootstrap", "build", "test"])
    assert func(args, apkbuild) == ["a", "e"]

    # Package depends on itself
    apkbuild["makedepends"] = ["c", "b", "test"]
    args = args_patched(monkeypatch, ["pmbootstrap", "build", "test"])
    assert func(args, apkbuild) == ["a", "b", "c", "e"]


def test_build_depends(args, monkeypatch):
    # Shortcut and fake apkbuild
    func = pmb.build._package.build_depends
    apkbuild = {"pkgname": "test", "depends": ["a", "!c"],
                "makedepends": ["b"], "checkdepends": [],
                "subpackages": {"d": None}, "options": []}

    # No depends built (first makedepends + depends, then only makedepends)
    monkeypatch.setattr(pmb.build._package, "package", return_none)
    assert func(args, apkbuild, "armhf", True) == (["!c", "a", "b"], [])

    # All depends built (makedepends only)
    monkeypatch.setattr(pmb.build._package, "package", return_string)
    assert func(args, apkbuild, "armhf", False) == (["!c", "a", "b"],
                                                    ["a", "b"])


def test_build_depends_no_binary_error(args, monkeypatch):
    # Shortcut and fake apkbuild
    func = pmb.build._package.build_depends
    apkbuild = {"pkgname": "test", "depends": ["some-invalid-package-here"],
                "makedepends": [], "checkdepends": [], "subpackages": {},
                "options": []}

    # pmbootstrap build --no-depends
    args.no_depends = True

    # Missing binary package error
    with pytest.raises(RuntimeError) as e:
        func(args, apkbuild, "armhf", True)
    assert str(e.value).startswith("Missing binary package for dependency")

    # All depends exist
    apkbuild["depends"] = ["alpine-base"]
    assert func(args, apkbuild, "armhf", True) == (["alpine-base"], [])


def test_build_depends_binary_outdated(args, monkeypatch):
    """ pmbootstrap runs with --no-depends and dependency binary package is
        outdated (#1895) """
    # Override pmb.parse.apkindex.package(): pretend hello-world-wrapper is
    # missing and hello-world is outdated
    func_orig = pmb.parse.apkindex.package

    def func_patch(args, package, *args2, **kwargs):
        print(f"func_patch: called for package: {package}")
        if package == "hello-world-wrapper":
            print("pretending that it does not exist")
            return None
        if package == "hello-world":
            print("pretending that it is outdated")
            ret = func_orig(args, package, *args2, **kwargs)
            ret["version"] = "0-r0"
            return ret
        return func_orig(args, package, *args2, **kwargs)
    monkeypatch.setattr(pmb.parse.apkindex, "package", func_patch)

    # Build hello-world-wrapper with --no-depends and expect failure
    args.no_depends = True
    pkgname = "hello-world-wrapper"
    arch = "x86_64"
    force = False
    strict = True
    with pytest.raises(RuntimeError) as e:
        pmb.build.package(args, pkgname, arch, force, strict)
    assert "'hello-world' of 'hello-world-wrapper' is outdated" in str(e.value)


def test_is_necessary_warn_depends(args, monkeypatch):
    # Shortcut and fake apkbuild
    func = pmb.build._package.is_necessary_warn_depends
    apkbuild = {"pkgname": "test"}

    # Necessary
    monkeypatch.setattr(pmb.build, "is_necessary", return_true)
    assert func(args, apkbuild, "armhf", False, []) is True

    # Necessary (strict=True overrides is_necessary())
    monkeypatch.setattr(pmb.build, "is_necessary", return_false)
    assert func(args, apkbuild, "armhf", True, []) is True

    # Not necessary (with depends: different code path that prints a warning)
    assert func(args, apkbuild, "armhf", False, []) is False
    assert func(args, apkbuild, "armhf", False, ["first", "second"]) is False


def test_init_buildenv(args, monkeypatch):
    # First init native chroot buildenv properly without patched functions
    pmb.build.init(args)

    # Disable effects of functions we don't want to test here
    monkeypatch.setattr(pmb.build._package, "build_depends",
                        return_fake_build_depends)
    monkeypatch.setattr(pmb.build._package, "is_necessary_warn_depends",
                        return_true)
    monkeypatch.setattr(pmb.chroot.apk, "install", return_none)

    # Shortcut and fake apkbuild
    func = pmb.build._package.init_buildenv
    apkbuild = {"pkgname": "test", "depends": ["a"], "makedepends": ["b"],
                "options": []}

    # Build is necessary (various code paths)
    assert func(args, apkbuild, "armhf", strict=True) is True
    assert func(args, apkbuild, "armhf", cross="native") is True

    # Build is not necessary (only builds dependencies)
    monkeypatch.setattr(pmb.build._package, "is_necessary_warn_depends",
                        return_false)
    assert func(args, apkbuild, "armhf") is False


def test_get_pkgver(monkeypatch):
    # With original source
    func = pmb.build._package.get_pkgver
    assert func("1.0", True) == "1.0"

    # Without original source
    now = datetime.date(2018, 1, 1)
    assert func("1.0", False, now) == "1.0_p20180101000000"
    assert func("1.0_git20170101", False, now) == "1.0_p20180101000000"


def test_run_abuild(args, monkeypatch):
    # Disable effects of functions we don't want to test here
    monkeypatch.setattr(pmb.build, "copy_to_buildpath", return_none)
    monkeypatch.setattr(pmb.chroot, "user", return_none)

    # Shortcut and fake apkbuild
    func = pmb.build._package.run_abuild
    apkbuild = {"pkgname": "test", "pkgver": "1", "pkgrel": "2", "options": []}

    # Normal run
    output = "armhf/test-1-r2.apk"
    env = {"CARCH": "armhf",
           "GOCACHE": "/home/pmos/.cache/go-build",
           "RUSTC_WRAPPER": "/usr/bin/sccache",
           "SUDO_APK": "abuild-apk --no-progress"}
    cmd = ["abuild", "-D", "postmarketOS", "-d"]
    assert func(args, apkbuild, "armhf") == (output, cmd, env)

    # Force and strict
    cmd = ["abuild", "-D", "postmarketOS", "-r", "-f"]
    assert func(args, apkbuild, "armhf", True, True) == (output, cmd, env)

    # cross=native
    env = {"CARCH": "armhf",
           "GOCACHE": "/home/pmos/.cache/go-build",
           "RUSTC_WRAPPER": "/usr/bin/sccache",
           "SUDO_APK": "abuild-apk --no-progress",
           "CROSS_COMPILE": "armv6-alpine-linux-musleabihf-",
           "CC": "armv6-alpine-linux-musleabihf-gcc"}
    cmd = ["abuild", "-D", "postmarketOS", "-d"]
    assert func(args, apkbuild, "armhf", cross="native") == (output, cmd, env)


def test_finish(args, monkeypatch):
    # Real output path
    output = pmb.build.package(args, "hello-world", force=True)

    # Disable effects of functions we don't want to test below
    monkeypatch.setattr(pmb.chroot, "user", return_none)

    # Shortcut and fake apkbuild
    func = pmb.build._package.finish
    apkbuild = {"options": []}

    # Non-existing output path
    with pytest.raises(RuntimeError) as e:
        func(args, apkbuild, "armhf", "/invalid/path")
    assert "Package not found" in str(e.value)

    # Existing output path
    func(args, apkbuild, pmb.config.arch_native, output)


def test_package(args):
    # First build
    assert pmb.build.package(args, "hello-world", force=True)

    # Package exists
    pmb.helpers.other.cache["built"] = {}
    assert pmb.build.package(args, "hello-world") is None

    # Force building again
    pmb.helpers.other.cache["built"] = {}
    assert pmb.build.package(args, "hello-world", force=True)

    # Build for another architecture
    assert pmb.build.package(args, "hello-world", "armhf", force=True)

    # Upstream package, for which we don't have an aport
    assert pmb.build.package(args, "alpine-base") is None


def test_build_depends_high_level(args, monkeypatch):
    """
    "hello-world-wrapper" depends on "hello-world". We build both, then delete
    "hello-world" and check that it gets rebuilt correctly again.
    """
    # Patch pmb.build.is_necessary() to always build the hello-world package
    def fake_build_is_necessary(args, arch, apkbuild, apkindex_path=None):
        if apkbuild["pkgname"] == "hello-world":
            return True
        return pmb.build.other.is_necessary(args, arch, apkbuild,
                                            apkindex_path)
    monkeypatch.setattr(pmb.build, "is_necessary",
                        fake_build_is_necessary)

    # Build hello-world to get its full output path
    channel = pmb.config.pmaports.read_config(args)["channel"]
    output_hello = pmb.build.package(args, "hello-world")
    output_hello_outside = f"{args.work}/packages/{channel}/{output_hello}"
    assert os.path.exists(output_hello_outside)

    # Make sure the wrapper exists
    pmb.build.package(args, "hello-world-wrapper")

    # Remove hello-world
    pmb.helpers.run.root(args, ["rm", output_hello_outside])
    pmb.build.index_repo(args, pmb.config.arch_native)
    pmb.helpers.other.cache["built"] = {}

    # Ask to build the wrapper. It should not build the wrapper (it exists, not
    # using force), but build/update its missing dependency "hello-world"
    # instead.
    assert pmb.build.package(args, "hello-world-wrapper") is None
    assert os.path.exists(output_hello_outside)


def test_build_local_source_high_level(args, tmpdir):
    """
    Test building a package with overriding the source code:
        pmbootstrap build --src=/some/path hello-world

    We use a copy of the hello-world APKBUILD here that doesn't have the
    source files it needs to build included. And we use the original aport
    folder as local source folder, so pmbootstrap should take the source files
    from there and the build should succeed.
    """
    # aports: Add deviceinfo (required by pmbootstrap to start)
    tmpdir = str(tmpdir)
    aports = tmpdir + "/aports"
    aport = aports + "/device/testing/device-" + args.device
    os.makedirs(aport)
    path_original = pmb.helpers.pmaports.find(args, f"device-{args.device}")
    shutil.copy(f"{path_original}/deviceinfo", aport)

    # aports: Add modified hello-world aport (source="", uses $builddir)
    aport = aports + "/main/hello-world"
    os.makedirs(aport)
    shutil.copy(pmb.config.pmb_src + "/test/testdata/build_local_src/APKBUILD",
                aport)

    # aports: Add pmaports.cfg, .git
    shutil.copy(args.aports + "/pmaports.cfg", aports)
    pmb_test.git.copy_dotgit(args, tmpdir)

    # src: Copy hello-world source files
    src = tmpdir + "/src"
    os.makedirs(src)
    shutil.copy(args.aports + "/main/hello-world/Makefile", src)
    shutil.copy(args.aports + "/main/hello-world/main.c", src)

    # src: Create unreadable file (rsync should skip it)
    unreadable = src + "/_unreadable_file"
    shutil.copy(args.aports + "/main/hello-world/main.c", unreadable)
    pmb.helpers.run.root(args, ["chown", "root:root", unreadable])
    pmb.helpers.run.root(args, ["chmod", "500", unreadable])

    # Test native arch and foreign arch chroot
    channel = pmb.config.pmaports.read_config(args)["channel"]
    for arch in [pmb.config.arch_native, "armhf"]:
        # Delete all hello-world --src packages
        pattern = f"{args.work}/packages/{channel}/{arch}/hello-world-*_p*.apk"
        for path in glob.glob(pattern):
            pmb.helpers.run.root(args, ["rm", path])
        assert len(glob.glob(pattern)) == 0

        # Build hello-world --src package
        pmb.helpers.run.user(args, [pmb.config.pmb_src + "/pmbootstrap.py",
                                    "--aports", aports, "build", "--src", src,
                                    "hello-world", "--arch", arch])

        # Verify that the package has been built and delete it
        paths = glob.glob(pattern)
        assert len(paths) == 1
        pmb.helpers.run.root(args, ["rm", paths[0]])

    # Clean up: update index, delete temp folder
    pmb.build.index_repo(args, pmb.config.arch_native)
    pmb.helpers.run.root(args, ["rm", "-r", tmpdir])


def test_build_abuild_leftovers(args, tmpdir):
    """
    Test building a package with having abuild leftovers, that will error if
    copied:
        pmbootstrap build hello-world
    """
    # aports: Add deviceinfo (required by pmbootstrap to start)
    tmpdir = str(tmpdir)
    aports = f"{tmpdir}/aports"
    aport = f"{aports}/device/testing/device-{args.device}"
    os.makedirs(aport)
    path_original = pmb.helpers.pmaports.find(args, f"device-{args.device}")
    shutil.copy(f"{path_original}/deviceinfo", aport)

    # aports: Add modified hello-world aport (source="", uses $builddir)
    test_aport = "main/hello-world"
    aport = f"{aports}/{test_aport}"
    shutil.copytree(f"{args.aports}/{test_aport}", aport)

    # aports: Add pmaports.cfg, .git
    shutil.copy(f"{args.aports}/pmaports.cfg", aports)
    pmb_test.git.copy_dotgit(args, aports)

    # aport: create abuild dir with broken symlink
    src = f"{aport}/src"
    os.makedirs(src)
    os.symlink("/var/cache/distfiles/non-existent.tar.gz",
               f"{src}/broken-tarball-symlink.tar.gz")

    # Delete all hello-world packages
    channel = pmb.config.pmaports.read_config(args)["channel"]
    pattern = f"{args.work}/packages/{channel}/*/hello-world-*_p*.apk"
    for path in glob.glob(pattern):
        pmb.helpers.run.root(args, ["rm", path])
    assert len(glob.glob(pattern)) == 0

    # Build hello-world package
    pmb.helpers.run.user(args, [f"{pmb.config.pmb_src}/pmbootstrap.py",
                                "--aports", aports, "build", "--src", src,
                                "hello-world", "--arch", pmb.config.arch_native])

    # Verify that the package has been built and delete it
    paths = glob.glob(pattern)
    assert len(paths) == 1
    pmb.helpers.run.root(args, ["rm", paths[0]])

    # Clean up: update index, delete temp folder
    pmb.build.index_repo(args, pmb.config.arch_native)
    pmb.helpers.run.root(args, ["rm", "-r", tmpdir])
