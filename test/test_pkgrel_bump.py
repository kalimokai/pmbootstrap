# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
""" Test pmb.helper.pkgrel_bump """
import glob
import os
import pytest
import sys

import pmb_test  # noqa
import pmb_test.git
import pmb.helpers.pkgrel_bump
import pmb.helpers.logging


@pytest.fixture
def args(request):
    import pmb.parse
    sys.argv = ["pmbootstrap.py", "chroot"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)
    return args


def pmbootstrap(args, tmpdir, parameters, zero_exit=True):
    """
    Helper function for running pmbootstrap inside the fake work folder
    (created by setup() below) with the binary repo disabled and with the
    testdata configured as aports.

    :param parameters: what to pass to pmbootstrap, e.g. ["build", "testlib"]
    :param zero_exit: expect pmbootstrap to exit with 0 (no error)
    """
    # Run pmbootstrap
    aports = tmpdir + "/_aports"
    config = tmpdir + "/_pmbootstrap.cfg"

    # Copy .git dir to fake pmaports
    dot_git = tmpdir + "/_aports/.git"
    if not os.path.exists(dot_git):
        pmb_test.git.copy_dotgit(args, aports)

    try:
        pmb.helpers.run.user(args, ["./pmbootstrap.py", "--work=" + tmpdir,
                                    "--mirror-pmOS=", "--aports=" + aports,
                                    "--config=" + config] + parameters,
                             working_dir=pmb.config.pmb_src)

    # Verify that it exits as desired
    except Exception as exc:
        if zero_exit:
            raise RuntimeError("pmbootstrap failed") from exc
        else:
            return
    if not zero_exit:
        raise RuntimeError("Expected pmbootstrap to fail, but it did not!")


def setup_work(args, tmpdir):
    """
    Create fake work folder in tmpdir with everything symlinked except for the
    built packages. The aports testdata gets copied to the tempfolder as
    well, so it can be modified during testing.
    """
    # Clean the chroots, and initialize the build chroot in the native chroot.
    # We do this before creating the fake work folder, because then all
    # packages are still present.
    os.chdir(pmb.config.pmb_src)
    pmb.helpers.run.user(args, ["./pmbootstrap.py", "-y", "zap"])
    pmb.helpers.run.user(args, ["./pmbootstrap.py", "build_init"])
    pmb.helpers.run.user(args, ["./pmbootstrap.py", "shutdown"])

    # Link everything from work (except for "packages") to the tmpdir
    for path in glob.glob(args.work + "/*"):
        if os.path.basename(path) != "packages":
            pmb.helpers.run.user(args, ["ln", "-s", path, tmpdir + "/"])

    # Copy testdata and selected device aport
    for folder in ["device/testing", "main"]:
        pmb.helpers.run.user(args, ["mkdir", "-p", args.aports, tmpdir +
                                    "/_aports/" + folder])
    path_original = pmb.helpers.pmaports.find(args, f"device-{args.device}")
    pmb.helpers.run.user(args, ["cp", "-r", path_original,
                                f"{tmpdir}/_aports/device/testing"])
    for pkgname in ["testlib", "testapp", "testsubpkg"]:
        pmb.helpers.run.user(args, ["cp", "-r",
                                    "test/testdata/pkgrel_bump/aports/"
                                    f"{pkgname}",
                                    f"{tmpdir}/_aports/main/{pkgname}"])

    # Copy pmaports.cfg
    pmb.helpers.run.user(args, ["cp", args.aports + "/pmaports.cfg", tmpdir +
                                "/_aports"])

    # Empty packages folder
    channel = pmb.config.pmaports.read_config(args)["channel"]
    packages_path = f"{tmpdir}/packages/{channel}"
    pmb.helpers.run.user(args, ["mkdir", "-p", packages_path])
    pmb.helpers.run.user(args, ["chmod", "777", packages_path])

    # Copy over the pmbootstrap config
    pmb.helpers.run.user(args, ["cp", args.config, tmpdir +
                                "/_pmbootstrap.cfg"])


def verify_pkgrels(tmpdir, pkgrel_testlib, pkgrel_testapp,
                   pkgrel_testsubpkg):
    """
    Verify the pkgrels of the three test APKBUILDs ("testlib", "testapp",
    "testsubpkg").
    """
    pmb.helpers.other.cache["apkbuild"] = {}
    mapping = {"testlib": pkgrel_testlib,
               "testapp": pkgrel_testapp,
               "testsubpkg": pkgrel_testsubpkg}
    for pkgname, pkgrel in mapping.items():
        # APKBUILD path
        path = tmpdir + "/_aports/main/" + pkgname + "/APKBUILD"

        # Parse and verify
        apkbuild = pmb.parse.apkbuild(path)
        assert pkgrel == int(apkbuild["pkgrel"])


def test_pkgrel_bump_high_level(args, tmpdir):
    # Tempdir setup
    tmpdir = str(tmpdir)
    setup_work(args, tmpdir)

    # Make sure we don't try and cross compile
    pmbootstrap(args, tmpdir, ["config", "build_default_device_arch", "False"])

    # Let pkgrel_bump exit normally
    pmbootstrap(args, tmpdir, ["build", "testlib", "testapp", "testsubpkg"])
    pmbootstrap(args, tmpdir, ["pkgrel_bump", "--dry", "--auto"])
    verify_pkgrels(tmpdir, 0, 0, 0)

    # Increase soname (testlib soname changes with the pkgrel)
    pmbootstrap(args, tmpdir, ["pkgrel_bump", "testlib"])
    verify_pkgrels(tmpdir, 1, 0, 0)
    pmbootstrap(args, tmpdir, ["build", "testlib"])
    pmbootstrap(args, tmpdir, ["pkgrel_bump", "--dry", "--auto"])
    verify_pkgrels(tmpdir, 1, 0, 0)

    # Delete package with previous soname (--auto-dry exits with >0 now)
    channel = pmb.config.pmaports.read_config(args)["channel"]
    arch = pmb.config.arch_native
    apk_path = f"{tmpdir}/packages/{channel}/{arch}/testlib-1.0-r0.apk"
    pmb.helpers.run.root(args, ["rm", apk_path])
    pmbootstrap(args, tmpdir, ["index"])
    pmbootstrap(args, tmpdir, ["pkgrel_bump", "--dry", "--auto"], False)
    verify_pkgrels(tmpdir, 1, 0, 0)

    # Bump pkgrel and build testapp/testsubpkg
    pmbootstrap(args, tmpdir, ["pkgrel_bump", "--auto"])
    verify_pkgrels(tmpdir, 1, 1, 1)
    pmbootstrap(args, tmpdir, ["build", "testapp", "testsubpkg"])

    # After rebuilding, pkgrel_bump --auto-dry exits with 0
    pmbootstrap(args, tmpdir, ["pkgrel_bump", "--dry", "--auto"])
    verify_pkgrels(tmpdir, 1, 1, 1)

    # Test running with specific package names
    pmbootstrap(args, tmpdir, ["pkgrel_bump", "invalid_package_name"], False)
    pmbootstrap(args, tmpdir, ["pkgrel_bump", "--dry", "testlib"], False)
    verify_pkgrels(tmpdir, 1, 1, 1)

    # Clean up
    pmbootstrap(args, tmpdir, ["shutdown"])
    pmb.helpers.run.root(args, ["rm", "-rf", tmpdir])
