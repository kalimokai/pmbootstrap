# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
""" Test pmb/parse/kconfig.py """
import pytest
import sys
import os

import pmb_test  # noqa
import pmb.parse.kconfig

test_options_checked_count = None


@pytest.fixture
def args(tmpdir, request):
    import pmb.parse
    sys.argv = ["pmbootstrap.py", "kconfig", "check"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)
    return args


def patch_config(monkeypatch):
    """
    Delete the real kconfig_options_* variables in pmb/config/__init__.py and
    replace them with a very basic config for the tests. The idea is that it
    should use all features of the kconfig check code, so we can test all the
    code paths.
    """
    for key in list(pmb.config.__dict__.keys()):
        if key.startswith("kconfig_options"):
            monkeypatch.delattr(pmb.config, key)

    monkeypatch.setattr(pmb.config, "kconfig_options", {
        ">=0.0.0": {  # all versions
            "all": {  # all arches
                "ANDROID_PARANOID_NETWORK": False,
                "BLK_DEV_INITRD": True,
                "DEFAULT_HOSTNAME": "(none)",
            },
        },
        ">=2.6.0": {
            "all": {
                "BINFMT_ELF": True,
            },
        },
        "<4.7.0": {
            "all": {
                "DEVPTS_MULTIPLE_INSTANCES": True,
            },
        },
        "<5.2.0": {
            "armhf armv7 x86": {
                "LBDAF": True
            },
        },
    }, False)

    monkeypatch.setattr(pmb.config, "kconfig_options_waydroid", {
        ">=0.0.0": {
            "all": {
                "SQUASHFS": True,
                "ANDROID_BINDERFS": False,
                "ANDROID_BINDER_DEVICES": ["binder", "hwbinder", "vndbinder"],
            }
        },
    }, False)

    monkeypatch.setattr(pmb.config, "kconfig_options_nftables", {
        ">=3.13.0 <5.17": {
            "all": {
                "NFT_COUNTER": True,
            },
        },
    }, False)


def test_get_all_component_names(monkeypatch):
    patch_config(monkeypatch)
    func = pmb.parse.kconfig.get_all_component_names
    assert func() == ["waydroid", "nftables"]


def test_is_set():
    config = ("CONFIG_WIREGUARD=m\n"
              "# CONFIG_EXT2_FS is not set\n"
              "CONFIG_EXT4_FS=y\n")
    func = pmb.parse.kconfig.is_set
    assert func(config, "WIREGUARD") is True
    assert func(config, "EXT4_FS") is True
    assert func(config, "NON_EXISTING") is False


def test_is_set_str():
    config = 'CONFIG_DEFAULT_HOSTNAME="(none)"\n'
    func = pmb.parse.kconfig.is_set_str
    option = "DEFAULT_HOSTNAME"
    assert func(config, option, "(none)") is True
    assert func(config, option, "hello") is False
    assert func(config, f"{option}_2", "(none)") is False


def test_is_in_array():
    config = 'CONFIG_ANDROID_BINDER_DEVICES="binder,hwbinder,vndbinder"\n'
    func = pmb.parse.kconfig.is_in_array
    option = "ANDROID_BINDER_DEVICES"
    assert func(config, option, "binder") is True
    assert func(config, option, "hwbinder") is True
    assert func(config, option, "vndbinder") is True
    assert func(config, option, "invalidbinder") is False
    assert func(config, f"{option}_2", "binder") is False


def test_check_option():
    func = pmb.parse.kconfig.check_option
    config = ('CONFIG_BOOL=m\n'
              'CONFIG_LIST="a,b,c"\n'
              'CONFIG_STR="test"\n')
    path = "/home/user/myconfig.aarch64"

    assert func("test", False, config, path, "BOOL", True) is True
    assert func("test", True, config, path, "BOOL", True) is True
    assert func("test", True, config, path, "NON_EXISTING", True) is False
    assert func("test", True, config, path, "STR", "test") is True
    assert func("test", True, config, path, "STR", "test2") is False
    assert func("test", True, config, path, "LIST", ["a"]) is True
    assert func("test", True, config, path, "LIST", ["d"]) is False

    with pytest.raises(RuntimeError) as e:
        func("test", True, config, path, "TEST", {"dict": "notsupported"})
    assert "is not supported" in str(e.value)

    with pytest.raises(RuntimeError) as e:
        func("test", True, config, path, "TEST", None)
    assert "is not supported" in str(e.value)


def test_check_config_options_set():
    func = pmb.parse.kconfig.check_config_options_set
    config = ('CONFIG_BOOL=m\n'
              'CONFIG_LIST="a,b,c"\n'
              'CONFIG_STR="test"\n')
    path = "/home/user/myconfig.aarch64"
    arch = "aarch64"
    pkgver = "6.0"
    component = "testcomponent"

    # Skip check because version is too low
    options = {
        ">=6.0.1": {
            "all": {
                "BOOL": False
            }
        }
    }
    assert func(config, path, arch, options, component, pkgver) is True

    # Skip check because version is too high
    options = {
        "<6.0": {
            "all": {
                "BOOL": False
            }
        }
    }
    assert func(config, path, arch, options, component, pkgver) is True

    # Skip with two version that don't match
    options = {
        "<6.2 >=6.0.1": {
            "all": {
                "BOOL": False
            }
        }
    }
    assert func(config, path, arch, options, component, pkgver) is True

    # Version matches, arch does not match
    options = {
        ">=6.0": {
            "armhf": {
                "BOOL": False
            }
        }
    }
    assert func(config, path, arch, options, component, pkgver) is True

    # Version matches, arch matches (aarch64)
    options = {
        ">=6.0": {
            "aarch64": {
                "BOOL": False
            }
        }
    }
    assert func(config, path, arch, options, component, pkgver) is False

    # Version matches, arch matches (all)
    options = {
        ">=6.0": {
            "all": {
                "BOOL": False
            }
        }
    }
    assert func(config, path, arch, options, component, pkgver) is False

    # Version matches, arch matches (all), rule passes
    options = {
        ">=6.0": {
            "all": {
                "BOOL": True
            }
        }
    }
    assert func(config, path, arch, options, component, pkgver) is True


def test_check_config_options_set_details(monkeypatch):
    global test_options_checked_count

    func = pmb.parse.kconfig.check_config_options_set
    config = ('CONFIG_BOOL=m\n'
              'CONFIG_LIST="a,b,c"\n'
              'CONFIG_STR="test"\n')
    path = "/home/user/myconfig.aarch64"
    arch = "aarch64"
    pkgver = "6.0"
    component = "testcomponent"

    def check_option_fake(*args, **kwargs):
        global test_options_checked_count
        test_options_checked_count += 1
        return False

    monkeypatch.setattr(pmb.parse.kconfig, "check_option", check_option_fake)

    options = {
        ">=0.0.0": {
            "all": {
                "BOOL": False,
                "STR": False,
            }
        }
    }

    # No details: stop after first error
    details = False
    test_options_checked_count = 0
    assert func(config, path, arch, options, component, pkgver, details) is False
    assert test_options_checked_count == 1

    # Details: don't stop, do both checks
    details = True
    test_options_checked_count = 0
    assert func(config, path, arch, options, component, pkgver, details) is False
    assert test_options_checked_count == 2


def test_check_config(monkeypatch, tmpdir):
    # Write test kernel config
    tmpdir = str(tmpdir)
    path = f"{tmpdir}/myconfig.aarch64"
    with open(path, "w") as handle:
        handle.write('CONFIG_BOOL=m\n'
                     'CONFIG_LIST="a,b,c"\n'
                     'CONFIG_STR="test"\n')

    patch_config(monkeypatch)

    func = pmb.parse.kconfig.check_config
    arch = "aarch64"
    pkgver = "6.0"

    # Invalid component
    components_list = ["invalid-component-name"]
    with pytest.raises(AssertionError) as e:
        func(path, arch, pkgver, components_list)
    assert "invalid kconfig component name" in str(e.value)

    # Fail base check
    components_list = []
    assert func(path, arch, pkgver, components_list) is False

    # Fails base check, even with enforce=False
    details = False
    enforce = False
    assert func(path, arch, pkgver, components_list, details, enforce) is False

    # Pass base check
    with open(path, "w") as handle:
        handle.write('CONFIG_BLK_DEV_INITRD=y\n'
                     'CONFIG_DEFAULT_HOSTNAME="(none)"\n'
                     'CONFIG_BINFMT_ELF=y\n')
    components_list = []
    assert func(path, arch, pkgver, components_list) is True

    # Fail additional check
    components_list = ["waydroid"]
    assert func(path, arch, pkgver, components_list) is False

    # Fail additional check, but result is still True with enforce=False
    components_list = ["waydroid"]
    details = True
    enforce = False
    assert func(path, arch, pkgver, components_list, details, enforce) is True


def test_check(args, monkeypatch, tmpdir):
    func = pmb.parse.kconfig.check
    details = True
    components_list = []
    patch_config(monkeypatch)

    # Create fake pmaports kernel structure
    tmpdir = str(tmpdir)
    monkeypatch.setattr(args, "aports", tmpdir)
    path_aport = f"{tmpdir}/device/community/linux-nokia-n900"
    path_apkbuild = f"{path_aport}/APKBUILD"
    os.makedirs(path_aport)

    # APKBUILD
    with open(path_apkbuild, "w") as handle:
        handle.write('pkgname=linux-nokia-n900\n'
                     'pkgver=5.15\n'
                     'options="pmb:kconfigcheck-nftables"\n')

    # Non-existing #1
    must_exist = True
    pkgname = "linux-does-not-exist"
    with pytest.raises(RuntimeError) as e:
        func(args, pkgname, components_list, details, must_exist)
    assert "Could not find aport" in str(e.value)

    # Non-existing #2
    must_exist = False
    pkgname = "linux-does-not-exist"
    assert func(args, pkgname, components_list, details, must_exist) is None

    # Invalid kernel config name
    path_kconfig = f"{path_aport}/config-nokia-n900_armv7"
    with open(path_kconfig, "w") as handle:
        handle.write('CONFIG_BOOL=m\n')
    must_exist = True
    pkgname = "linux-nokia-n900"
    with pytest.raises(RuntimeError) as e:
        func(args, pkgname, components_list, details, must_exist)
    assert "is not a valid kernel config" in str(e.value)
    os.unlink(path_kconfig)

    # Pass checks of base and nftables
    path_kconfig = f"{path_aport}/config-nokia-n900.armv7"
    with open(path_kconfig, "w") as handle:
        handle.write('CONFIG_BLK_DEV_INITRD=y\n'
                     'CONFIG_DEFAULT_HOSTNAME="(none)"\n'
                     'CONFIG_BINFMT_ELF=y\n'
                     'CONFIG_NFT_COUNTER=y\n')
    must_exist = True
    pkgname = "nokia-n900"
    assert func(args, pkgname, components_list, details, must_exist) is True

    # Don't pass nftables check
    with open(path_kconfig, "w") as handle:
        handle.write('CONFIG_BLK_DEV_INITRD=y\n'
                     'CONFIG_DEFAULT_HOSTNAME="(none)"\n'
                     'CONFIG_BINFMT_ELF=y\n')
    assert func(args, pkgname, components_list, details, must_exist) is False

    # Don't pass waydroid check (extra component check passed via cmdline)
    with open(path_kconfig, "w") as handle:
        handle.write('CONFIG_BLK_DEV_INITRD=y\n'
                     'CONFIG_DEFAULT_HOSTNAME="(none)"\n'
                     'CONFIG_BINFMT_ELF=y\n'
                     'CONFIG_NFT_COUNTER=y\n')
    components_list = ["waydroid"]
    assert func(args, pkgname, components_list, details, must_exist) is False


def test_extract_arch(tmpdir):
    func = pmb.parse.kconfig.extract_arch
    path = f"{tmpdir}/config"

    with open(path, "w") as handle:
        handle.write('CONFIG_ARM=y\n')
    assert func(path) == "armv7"

    with open(path, "w") as handle:
        handle.write('CONFIG_ARM64=y\n')
    assert func(path) == "aarch64"

    with open(path, "w") as handle:
        handle.write('CONFIG_RISCV=y\n')
    assert func(path) == "riscv64"

    with open(path, "w") as handle:
        handle.write('CONFIG_X86_32=y\n')
    assert func(path) == "x86"

    with open(path, "w") as handle:
        handle.write('CONFIG_X86_64=y\n')
    assert func(path) == "x86_64"

    with open(path, "w") as handle:
        handle.write('hello')
    assert func(path) == "unknown"


def test_extract_version(tmpdir):
    func = pmb.parse.kconfig.extract_version
    path = f"{tmpdir}/config"

    with open(path, "w") as handle:
        handle.write("#\n"
                     "# Automatically generated file; DO NOT EDIT.\n"
                     "# Linux/arm64 3.10.93 Kernel Configuration\n")
    assert func(path) == "3.10.93"

    with open(path, "w") as handle:
        handle.write("#\n"
                     "# Automatically generated file; DO NOT EDIT.\n"
                     "# Linux/arm64 6.2.0 Kernel Configuration\n")
    assert func(path) == "6.2.0"

    with open(path, "w") as handle:
        handle.write("#\n"
                     "# Automatically generated file; DO NOT EDIT.\n"
                     "# Linux/riscv 6.1.0-rc3 Kernel Configuration\n")
    assert func(path) == "6.1.0_rc3"

    with open(path, "w") as handle:
        handle.write("#\n"
                     "# Automatically generated file; DO NOT EDIT.\n"
                     "# no version here\n")
    assert func(path) == "unknown"


def test_check_file(tmpdir, monkeypatch):
    patch_config(monkeypatch)
    func = pmb.parse.kconfig.check_file
    path = f"{tmpdir}/config"

    # Fail the basic check
    with open(path, "w") as handle:
        handle.write("#\n"
                     "# Automatically generated file; DO NOT EDIT.\n"
                     "# Linux/arm64 3.10.93 Kernel Configuration\n"
                     "CONFIG_ARM64=y\n")

    func(path) is False

    # Pass the basic check
    with open(path, "w") as handle:
        handle.write("#\n"
                     "# Automatically generated file; DO NOT EDIT.\n"
                     "# Linux/arm64 3.10.93 Kernel Configuration\n"
                     "CONFIG_ARM64=y\n"
                     "BLK_DEV_INITRD=y\n"
                     "DEFAULT_HOSTNAME=\"(none)\"\n"
                     "BINFMT_ELF=y\n"
                     "DEVPTS_MULTIPLE_INSTANCES=y\n"
                     "LBDAF=y\n")

    func(path) is True
