# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import pytest
import shutil
import sys

import pmb_test
import pmb_test.const
import pmb.helpers.lint
import pmb.helpers.run


@pytest.fixture
def args(request):
    import pmb.parse
    sys.argv = ["pmbootstrap", "lint"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)
    return args


def test_pmbootstrap_lint(args, tmpdir):
    args.aports = tmpdir = str(tmpdir)

    # Create hello-world pmaport in tmpdir
    apkbuild_orig = f"{pmb_test.const.testdata}/apkbuild/APKBUILD.lint"
    apkbuild_tmp = f"{tmpdir}/hello-world/APKBUILD"
    os.makedirs(f"{tmpdir}/hello-world")
    shutil.copyfile(apkbuild_orig, apkbuild_tmp)

    # Lint passes
    assert pmb.helpers.lint.check(args, ["hello-world"]) == ""

    # Change "pmb:cross-native" to non-existing "pmb:invalid-opt"
    pmb.helpers.run.user(args, ["sed", "s/pmb:cross-native/pmb:invalid-opt/g",
                                "-i", apkbuild_tmp])

    # Lint error
    err_str = "invalid option 'pmb:invalid-opt'"
    assert err_str in pmb.helpers.lint.check(args, ["hello-world"])
