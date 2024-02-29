# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import sys
import pytest

import pmb_test
import pmb_test.const
import pmb.aportgen
import pmb.aportgen.core
import pmb.build
import pmb.build.envkernel
import pmb.config
import pmb.helpers.logging


@pytest.fixture
def args(tmpdir, request):
    import pmb.parse
    sys.argv = ["pmbootstrap.py", "init"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)
    return args


def test_package_kernel_args(args):
    args.packages = ["package-one", "package-two"]
    with pytest.raises(RuntimeError) as e:
        pmb.build.envkernel.package_kernel(args)
    assert "--envkernel needs exactly one linux-* package as argument." in \
        str(e.value)


def test_find_kbuild_output_dir():
    # Test parsing an APKBUILD
    pkgname = "linux-envkernel-test"
    path = pmb_test.const.testdata + "/apkbuild/APKBUILD." + pkgname
    function_body = pmb.parse.function_body(path, "package")
    kbuild_out = pmb.build.envkernel.find_kbuild_output_dir(function_body)
    assert kbuild_out == "build"

    # Test full function body
    function_body = [
        "   install -Dm644 \"$srcdir\"/build/arch/arm/boot/dt.img ",
        "       \"$pkgdir\"/boot/dt.img",
        "",
        "   install -Dm644 \"$srcdir\"/build/arch/arm/boot/zImage-dtb ",
        "       \"$pkgdir\"/boot/vmlinuz-$_flavor",
        "",
        "   install -D \"$srcdir\"/build/include/config/kernel.release ",
        "       \"$pkgdir\"/usr/share/kernel/$_flavor/kernel.release",
        "",
        "   cd \"$srcdir\"/build",
        "   unset LDFLAGS",
        "",
        "   make ARCH=\"$_carch\" CC=\"${CC:-gcc}\" ",
        "       KBUILD_BUILD_VERSION=\"$((pkgrel + 1))-Alpine\" ",
        "       INSTALL_MOD_PATH=\"$pkgdir\" modules_install",
    ]
    kbuild_out = pmb.build.envkernel.find_kbuild_output_dir(function_body)
    assert kbuild_out == "build"

    # Test no kbuild out dir
    function_body = [
        "   install -Dm644 \"$srcdir\"/arch/arm/boot/zImage ",
        "       \"$pkgdir\"/boot/vmlinuz-$_flavor",
        "   install -D \"$srcdir\"/include/config/kernel.release ",
        "       \"$pkgdir\"/usr/share/kernel/$_flavor/kernel.release",
    ]
    kbuild_out = pmb.build.envkernel.find_kbuild_output_dir(function_body)
    assert kbuild_out == ""

    # Test curly brackets around srcdir
    function_body = [
        "   install -Dm644 \"${srcdir}\"/build/arch/arm/boot/zImage ",
        "       \"$pkgdir\"/boot/vmlinuz-$_flavor",
        "   install -D \"${srcdir}\"/build/include/config/kernel.release ",
        "       \"$pkgdir\"/usr/share/kernel/$_flavor/kernel.release",
    ]
    kbuild_out = pmb.build.envkernel.find_kbuild_output_dir(function_body)
    assert kbuild_out == "build"

    # Test multiple sub directories
    function_body = [
        "   install -Dm644 \"${srcdir}\"/sub/dir/arch/arm/boot/zImage-dtb ",
        "       \"$pkgdir\"/boot/vmlinuz-$_flavor",
        "   install -D \"${srcdir}\"/sub/dir/include/config/kernel.release ",
        "       \"$pkgdir\"/usr/share/kernel/$_flavor/kernel.release",
    ]
    kbuild_out = pmb.build.envkernel.find_kbuild_output_dir(function_body)
    assert kbuild_out == "sub/dir"

    # Test no kbuild out dir found
    function_body = [
        "   install -Dm644 \"$srcdir\"/build/not/found/zImage-dtb ",
        "       \"$pkgdir\"/boot/vmlinuz-$_flavor",
        "   install -D \"$srcdir\"/not/found/kernel.release ",
        "       \"$pkgdir\"/usr/share/kernel/$_flavor/kernel.release",
    ]
    with pytest.raises(RuntimeError) as e:
        kbuild_out = pmb.build.envkernel.find_kbuild_output_dir(function_body)
    assert ("Couldn't find a kbuild out directory. Is your APKBUILD messed up?"
            " If not, then consider adjusting the patterns in "
            "pmb/build/envkernel.py to work with your APKBUILD, or submit an "
            "issue.") in str(e.value)

    # Test multiple different kbuild out dirs
    function_body = [
        "   install -Dm644 \"$srcdir\"/build/arch/arm/boot/zImage-dtb ",
        "       \"$pkgdir\"/boot/vmlinuz-$_flavor",
        "   install -D \"$srcdir\"/include/config/kernel.release ",
        "       \"$pkgdir\"/usr/share/kernel/$_flavor/kernel.release",
    ]
    with pytest.raises(RuntimeError) as e:
        kbuild_out = pmb.build.envkernel.find_kbuild_output_dir(function_body)
    assert ("Multiple kbuild out directories found. Can you modify your "
            "APKBUILD so it only has one output path? If you can't resolve it,"
            " please open an issue.") in str(e.value)
