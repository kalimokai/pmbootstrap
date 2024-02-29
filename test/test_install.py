# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import pytest
import sys
import os
import shutil

import pmb_test
import pmb_test.const
import pmb.aportgen.device
import pmb.config
import pmb.config.init
import pmb.helpers.logging
import pmb.install._install


@pytest.fixture
def args(tmpdir, request):
    import pmb.parse
    sys.argv = ["pmbootstrap.py", "init"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)
    return args


def test_get_nonfree_packages(args):
    args.aports = pmb_test.const.testdata + "/init_questions_device/aports"
    func = pmb.install._install.get_nonfree_packages

    # Device without any non-free subpackages
    assert func(args, "lg-mako") == []

    # Device with non-free firmware and userland
    device = "nonfree-firmware-and-userland"
    assert func(args, device) == ["device-" + device + "-nonfree-firmware",
                                  "device-" + device + "-nonfree-userland"]

    # Device with non-free userland
    device = "nonfree-userland"
    assert func(args, device) == ["device-" + device + "-nonfree-userland"]


def test_get_recommends(args):
    args.aports = pmb_test.const.testdata + "/pmb_recommends"
    func = pmb.install._install.get_recommends

    # UI: none
    args.install_recommends = True
    assert func(args, ["postmarketos-ui-none"]) == []

    # UI: test, --no-recommends
    args.install_recommends = False
    assert func(args, ["postmarketos-ui-test"]) == []

    # UI: test
    args.install_recommends = True
    assert func(args, ["postmarketos-ui-test"]) == ["plasma-camera",
                                                    "plasma-angelfish"]

    # UI: test + test-extras
    args.install_recommends = True
    assert func(args, ["postmarketos-ui-test",
                       "postmarketos-ui-test-extras"]) == ["plasma-camera",
                                                           "plasma-angelfish",
                                                           "buho", "kaidan",
                                                           "test-app", "foot",
                                                           "htop"]
    # Non-UI package
    args.install_recommends = True
    args.ui_extras = False
    assert func(args, ["test-app"]) == ["foot", "htop"]


def test_get_groups(args):
    args.aports = f"{pmb_test.const.testdata}/pmb_groups"
    func = pmb.install.ui.get_groups

    # UI: none:
    args.ui = "none"
    assert func(args) == []

    # UI: test, without -extras
    args.ui = "test"
    args.ui_extras = False
    assert func(args) == ["feedbackd"]

    # UI: test, with -extras
    args.ui = "test"
    args.ui_extras = True
    assert func(args) == ["feedbackd", "extra"]

    # UI: invalid
    args.ui = "invalid"
    with pytest.raises(RuntimeError) as e:
        func(args)
    assert str(e.value).startswith("Could not find aport for package")


def test_generate_binary_list(args):
    suffix = "mysuffix"
    args.work = "/tmp"
    func = pmb.install._install.generate_binary_list
    binary_dir = os.path.join(args.work, f"chroot_{suffix}", "usr/share")
    os.makedirs(binary_dir, exist_ok=True)
    step = 1024
    binaries = [f"{pmb_test.const.testdata}/pmb_install/small.bin",
                f"{pmb_test.const.testdata}/pmb_install/full.bin",
                f"{pmb_test.const.testdata}/pmb_install/big.bin",
                f"{pmb_test.const.testdata}/pmb_install/overrun.bin",
                f"{pmb_test.const.testdata}/pmb_install/binary2.bin"]
    for b in binaries:
        shutil.copy(b, binary_dir)

    # Binary that is small enough to fit the partition of 10 blocks
    # of 512 bytes each
    binaries = "small.bin:1,binary2.bin:11"
    args.deviceinfo = {"sd_embed_firmware": binaries,
                       "boot_part_start": "128"}
    assert func(args, suffix, step) == [('small.bin', 1), ('binary2.bin', 11)]

    # Binary that is fully filling the partition of 10 blocks of 512 bytes each
    binaries = "full.bin:1,binary2.bin:11"
    args.deviceinfo = {"sd_embed_firmware": binaries,
                       "boot_part_start": "128"}
    assert func(args, suffix, step) == [('full.bin', 1), ('binary2.bin', 11)]

    # Binary that is too big to fit the partition of 10 blocks
    # of 512 bytes each
    binaries = "big.bin:1,binary2.bin:2"
    args.deviceinfo = {"sd_embed_firmware": binaries,
                       "boot_part_start": "128"}
    with pytest.raises(RuntimeError) as e:
        func(args, suffix, step)
    assert str(e.value).startswith("The firmware overlaps with at least one")

    # Binary that overruns the first partition
    binaries = "overrun.bin:1"
    args.deviceinfo = {"sd_embed_firmware": binaries,
                       "boot_part_start": "1"}
    with pytest.raises(RuntimeError) as e:
        func(args, suffix, step)
    assert str(e.value).startswith("The firmware is too big to embed in")

    # Binary does not exist
    binaries = "does-not-exist.bin:1,binary2.bin:11"
    args.deviceinfo = {"sd_embed_firmware": binaries,
                       "boot_part_start": "128"}
    with pytest.raises(RuntimeError) as e:
        func(args, suffix, step)
    assert str(e.value).startswith("The following firmware binary does not")

    # Binaries are touching but not overlapping
    # boot_part_start is at 2 sectors (1024 b)
    # |-----|---------------------|-------------------|-------------------
    # |  …  | binary2.bin (100 b) | small.bin (600 b) | /boot part start …
    # |-----|---------------------|-------------------|-------------------
    # 0    324                   424                 1024
    step = 1
    binaries = "binary2.bin:324,small.bin:424"
    args.deviceinfo = {"sd_embed_firmware": binaries,
                       "boot_part_start": "2"}
    assert func(args, suffix, step) == [('binary2.bin', 324),
                                        ('small.bin', 424)]

    # Same layout written with different order in sd_embed_firmware
    binaries = "small.bin:424,binary2.bin:324"
    args.deviceinfo = {"sd_embed_firmware": binaries,
                       "boot_part_start": "2"}
    assert func(args, suffix, step) == [('small.bin', 424),
                                        ('binary2.bin', 324)]
