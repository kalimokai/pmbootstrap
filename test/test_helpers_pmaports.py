# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import pytest
import sys

import pmb_test  # noqa
import pmb.build.other


@pytest.fixture
def args(request):
    import pmb.parse
    sys.argv = ["pmbootstrap", "init"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)
    return args


def test_guess_main(args, tmpdir):
    # Fake pmaports folder
    tmpdir = str(tmpdir)
    args.aports = tmpdir
    for aport in ["temp/qemu", "main/some-pkg"]:
        os.makedirs(tmpdir + "/" + aport)
        with open(tmpdir + "/" + aport + "/APKBUILD", 'w'):
            pass

    func = pmb.helpers.pmaports.guess_main
    assert func(args, "qemu-x86_64") == tmpdir + "/temp/qemu"
    assert func(args, "qemu-system-x86_64") == tmpdir + "/temp/qemu"
    assert func(args, "some-pkg-sub-pkg") == tmpdir + "/main/some-pkg"
    assert func(args, "qemuPackageWithoutDashes") is None


def test_guess_main_dev(args, tmpdir):
    # Fake pmaports folder
    tmpdir = str(tmpdir)
    args.aports = tmpdir
    os.makedirs(tmpdir + "/temp/plasma")
    with open(tmpdir + "/temp/plasma/APKBUILD", 'w'):
        pass

    func = pmb.helpers.pmaports.guess_main_dev
    assert func(args, "plasma-framework-dev") is None
    assert func(args, "plasma-dev") == tmpdir + "/temp/plasma"

    func = pmb.helpers.pmaports.guess_main
    assert func(args, "plasma-framework-dev") is None
    assert func(args, "plasma-randomsubpkg") == tmpdir + "/temp/plasma"
