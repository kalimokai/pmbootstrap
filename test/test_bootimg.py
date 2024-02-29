# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import sys
import pytest

import pmb_test
import pmb_test.const
import pmb.chroot.apk_static
import pmb.parse.apkindex
import pmb.helpers.logging
import pmb.parse.bootimg


@pytest.fixture
def args(request):
    import pmb.parse
    sys.argv = ["pmbootstrap.py", "chroot"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)
    return args


def test_bootimg_invalid_path(args):
    with pytest.raises(RuntimeError) as e:
        pmb.parse.bootimg(args, "/invalid-path")
    assert "Could not find file" in str(e.value)


def test_bootimg_kernel(args):
    path = pmb_test.const.testdata + "/bootimg/kernel-boot.img"
    with pytest.raises(RuntimeError) as e:
        pmb.parse.bootimg(args, path)
    assert "heimdall-isorec" in str(e.value)


def test_bootimg_invalid_file(args):
    with pytest.raises(RuntimeError) as e:
        pmb.parse.bootimg(args, __file__)
    assert "File is not an Android boot.img" in str(e.value)


def test_bootimg_normal(args):
    path = pmb_test.const.testdata + "/bootimg/normal-boot.img"
    output = {"header_version": "0",
              "base": "0x80000000",
              "kernel_offset": "0x00008000",
              "ramdisk_offset": "0x04000000",
              "second_offset": "0x00f00000",
              "tags_offset": "0x0e000000",
              "pagesize": "2048",
              "cmdline": "bootopt=64S3,32S1,32S1",
              "qcdt": "false",
              "dtb_second": "false"}
    assert pmb.parse.bootimg(args, path) == output


def test_bootimg_qcdt(args):
    path = pmb_test.const.testdata + "/bootimg/qcdt-boot.img"
    output = {"base": "0x80000000",
              "kernel_offset": "0x00008000",
              "ramdisk_offset": "0x04000000",
              "second_offset": "0x00f00000",
              "tags_offset": "0x0e000000",
              "pagesize": "2048",
              "cmdline": "bootopt=64S3,32S1,32S1",
              "qcdt": "true",
              "dtb_second": "false"}
    assert pmb.parse.bootimg(args, path) == output


def test_bootimg_mtk(args):
    path = pmb_test.const.testdata + "/bootimg/mtk-boot.img"
    output = {"header_version": "0",
              "base": "0x10000000",
              "kernel_offset": "0x00008000",
              "ramdisk_offset": "0x01000000",
              "second_offset": "0x00f00000",
              "tags_offset": "0x00000100",
              "pagesize": "2048",
              "mtk_label_kernel": "KERNEL",
              "mtk_label_ramdisk": "ROOTFS",
              "cmdline": "",
              "qcdt": "false",
              "dtb_second": "false"}
    assert pmb.parse.bootimg(args, path) == output


def test_bootimg_mtk_recovery(args):
    path = pmb_test.const.testdata + "/bootimg/mtk-boot-recovery.img"
    output = {"header_version": "0",
              "base": "0x80000000",
              "kernel_offset": "0x00008000",
              "ramdisk_offset": "0x04000000",
              "second_offset": "0x00f00000",
              "tags_offset": "0x00000100",
              "pagesize": "2048",
              "mtk_label_kernel": "KERNEL",
              "mtk_label_ramdisk": "ROOTFS",
              "cmdline": "",
              "qcdt": "false",
              "dtb_second": "false"}
    assert pmb.parse.bootimg(args, path) == output


def test_bootimg_mtk_kernelonly(args):
    path = pmb_test.const.testdata + "/bootimg/mtk-boot-kernel-only.img"
    output = {"header_version": "0",
              "base": "0x10000000",
              "kernel_offset": "0x00008000",
              "ramdisk_offset": "0x01000000",
              "second_offset": "0xf0000000",
              "tags_offset": "0x00000100",
              "pagesize": "2048",
              "mtk_label_kernel": "KERNEL",
              "cmdline": "",
              "qcdt": "false",
              "dtb_second": "false"}
    assert pmb.parse.bootimg(args, path) == output


def test_bootimg_dtb_second(args):
    path = pmb_test.const.testdata + "/bootimg/dtb-second-boot.img"
    output = {"header_version": "0",
              "base": "0x00000000",
              "kernel_offset": "0x00008000",
              "ramdisk_offset": "0x02000000",
              "second_offset": "0x00f00000",
              "tags_offset": "0x00000100",
              "pagesize": "2048",
              "cmdline": "bootopt=64S3,32S1,32S1",
              "qcdt": "false",
              "dtb_second": "true"}
    assert pmb.parse.bootimg(args, path) == output


def test_bootimg_v2(args):
    path = pmb_test.const.testdata + "/bootimg/boot-header-v2.img"
    output = {"header_version": "2",
              "base": "0x40078000",
              "kernel_offset": "0x00008000",
              "ramdisk_offset": "0x07c08000",
              "second_offset": "0x00e10000",
              "tags_offset": "0x0bc08000",
              "pagesize": "2048",
              "dtb_offset": "0x0bc08000",
              "cmdline": "bootopt=64S3,32N2,64N2 systempart=/dev/mapper/system",
              "qcdt": "false",
              "dtb_second": "false"}
    assert pmb.parse.bootimg(args, path) == output


def test_bootimg_v3(args):
    path = pmb_test.const.testdata + "/bootimg/boot-header-v3.img"
    output = {"header_version": "3",
              "pagesize": "4096",
              "cmdline": "twrpfastboot=1",
              "qcdt": "false",
              "dtb_second": "false"}
    assert pmb.parse.bootimg(args, path) == output
