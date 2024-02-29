# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
# This file has a _zzz_ prefix so it runs last, because it tends to fail on
# sourcehut currently. Related to some CDN caching issue probably.
import os
import sys
import pytest
import glob
import filecmp

import pmb_test  # noqa
import pmb.parse.apkindex
import pmb.helpers.logging
import pmb.config


@pytest.fixture
def args(request):
    import pmb.parse
    sys.argv = ["pmbootstrap.py", "chroot"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)
    return args


def test_keys(args):
    # Get the alpine-keys apk filename
    pmb.chroot.init(args)
    version = pmb.parse.apkindex.package(args, "alpine-keys")["version"]
    pattern = (args.work + "/cache_apk_" + pmb.config.arch_native +
               "/alpine-keys-" + version + ".*.apk")
    filename = os.path.basename(glob.glob(pattern)[0])

    # Extract it to a temporary folder
    temp = "/tmp/test_keys_extract"
    temp_outside = args.work + "/chroot_native" + temp
    if os.path.exists(temp_outside):
        pmb.chroot.root(args, ["rm", "-r", temp])
    pmb.chroot.user(args, ["mkdir", "-p", temp])
    pmb.chroot.user(args, ["tar", "xvf", "/var/cache/apk/" + filename],
                    working_dir=temp)

    # Get all relevant key file names as {"filename": "full_outside_path"}
    keys_upstream = {}
    for arch in pmb.config.build_device_architectures + ["x86_64"]:
        pattern = temp_outside + "/usr/share/apk/keys/" + arch + "/*.pub"
        for path in glob.glob(pattern):
            keys_upstream[os.path.basename(path)] = path
    assert len(keys_upstream)

    # Check if the keys are mirrored correctly
    mirror_path_keys = pmb.config.apk_keys_path
    for key, original_path in keys_upstream.items():
        mirror_path = mirror_path_keys + "/" + key
        assert filecmp.cmp(mirror_path, original_path, False)

    # Find postmarketOS keys
    keys_pmos = ["build.postmarketos.org.rsa.pub"]
    for key in keys_pmos:
        assert os.path.exists(mirror_path_keys + "/" + key)

    # Find outdated keys, which need to be removed
    glob_result = glob.glob(mirror_path_keys + "/*.pub")
    assert len(glob_result)
    for path in glob_result:
        key = os.path.basename(key)
        assert key in keys_pmos or key in keys_upstream
