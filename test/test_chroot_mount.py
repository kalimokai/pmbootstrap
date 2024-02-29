# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
""" Test pmb/chroot/mount.py """
import os
import pytest
import sys

import pmb_test  # noqa
import pmb.chroot


@pytest.fixture
def args(tmpdir, request):
    import pmb.parse
    sys.argv = ["pmbootstrap", "init"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)
    return args


def test_chroot_mount(args):
    suffix = "native"
    mnt_dir = f"{args.work}/chroot_native/mnt/pmbootstrap"

    # Run something in the chroot to have the dirs created
    pmb.chroot.root(args, ["true"])
    assert os.path.exists(mnt_dir)
    assert os.path.exists(f"{mnt_dir}/packages")

    # Umount everything, like in pmb.install.install_system_image
    pmb.helpers.mount.umount_all(args, f"{args.work}/chroot_{suffix}")

    # Remove all /mnt/pmbootstrap dirs
    pmb.chroot.remove_mnt_pmbootstrap(args, suffix)
    assert not os.path.exists(mnt_dir)

    # Run again: it should not crash
    pmb.chroot.remove_mnt_pmbootstrap(args, suffix)
