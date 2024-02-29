# Copyright 2023 Attila Szollosi
# SPDX-License-Identifier: GPL-3.0-or-later
import glob
import logging
import re
import os

import pmb.build
import pmb.config
import pmb.parse
import pmb.helpers.pmaports


def get_all_component_names():
    """
    Get the component names from kconfig_options variables in
    pmb/config/__init__.py. This does not include the base options.

    :returns: a list of component names, e.g. ["waydroid", "iwd", "nftables"]
    """
    prefix = "kconfig_options_"
    ret = []

    for key in pmb.config.__dict__.keys():
        if key.startswith(prefix):
            ret += [key.split(prefix, 1)[1]]

    return ret


def is_set(config, option):
    """
    Check, whether a boolean or tristate option is enabled
    either as builtin or module.

    :param config: full kernel config as string
    :param option: name of the option to check, e.g. EXT4_FS
    :returns: True if the check passed, False otherwise
    """
    return re.search("^CONFIG_" + option + "=[ym]$", config, re.M) is not None


def is_set_str(config, option, string):
    """
    Check, whether a config option contains a string as value.

    :param config: full kernel config as string
    :param option: name of the option to check, e.g. EXT4_FS
    :param string: the expected string
    :returns: True if the check passed, False otherwise
    """
    match = re.search("^CONFIG_" + option + "=\"(.*)\"$", config, re.M)
    if match:
        return string == match.group(1)
    else:
        return False


def is_in_array(config, option, string):
    """
    Check, whether a config option contains string as an array element

    :param config: full kernel config as string
    :param option: name of the option to check, e.g. EXT4_FS
    :param string: the string expected to be an element of the array
    :returns: True if the check passed, False otherwise
    """
    match = re.search("^CONFIG_" + option + "=\"(.*)\"$", config, re.M)
    if match:
        values = match.group(1).split(",")
        return string in values
    else:
        return False


def check_option(component, details, config, config_path, option,
                 option_value):
    """
    Check, whether one kernel config option has a given value.

    :param component: name of the component to test (postmarketOS, waydroid, …)
    :param details: print all warnings if True, otherwise one per component
    :param config: full kernel config as string
    :param config_path: full path to kernel config file
    :param option: name of the option to check, e.g. EXT4_FS
    :param option_value: expected value, e.g. True, "str", ["str1", "str2"]
    :returns: True if the check passed, False otherwise
    """
    def warn_ret_false(should_str):
        config_name = os.path.basename(config_path)
        if details:
            logging.warning(f"WARNING: {config_name}: CONFIG_{option} should"
                            f" {should_str} ({component}):"
                            f" https://wiki.postmarketos.org/wiki/kconfig#CONFIG_{option}")
        else:
            logging.warning(f"WARNING: {config_name} isn't configured properly"
                            f" ({component}), run 'pmbootstrap kconfig check'"
                            " for details!")
        return False

    if isinstance(option_value, list):
        for string in option_value:
            if not is_in_array(config, option, string):
                return warn_ret_false(f'contain "{string}"')
    elif isinstance(option_value, str):
        if not is_set_str(config, option, option_value):
            return warn_ret_false(f'be set to "{option_value}"')
    elif option_value in [True, False]:
        if option_value != is_set(config, option):
            return warn_ret_false("be set" if option_value else "*not* be set")
    else:
        raise RuntimeError("kconfig check code can only handle booleans,"
                           f" strings and arrays. Given value {option_value}"
                           " is not supported. If you need this, please patch"
                           " pmbootstrap or open an issue.")
    return True


def check_config_options_set(config, config_path, config_arch, options,
                             component, pkgver, details=False):
    """
    Check, whether all the kernel config passes all rules of one component.
    Print a warning if any is missing.

    :param config: full kernel config as string
    :param config_path: full path to kernel config file
    :param config_arch: architecture name (alpine format, e.g. aarch64, x86_64)
    :param options: kconfig_options* var passed from pmb/config/__init__.py:
                    kconfig_options_example = {
                        ">=0.0.0": {  # all versions
                            "all": {  # all arches
                                "ANDROID_PARANOID_NETWORK": False,
                            },
                    }
    :param component: name of the component to test (postmarketOS, waydroid, …)
    :param pkgver: kernel version
    :param details: print all warnings if True, otherwise one per component
    :returns: True if the check passed, False otherwise
    """
    ret = True
    for rules, archs_options in options.items():
        # Skip options irrelevant for the current kernel's version
        # Example rules: ">=4.0 <5.0"
        skip = False
        for rule in rules.split(" "):
            if not pmb.parse.version.check_string(pkgver, rule):
                skip = True
                break
        if skip:
            continue

        for archs, options in archs_options.items():
            if archs != "all":
                # Split and check if the device's architecture architecture has
                # special config options. If option does not contain the
                # architecture of the device kernel, then just skip the option.
                architectures = archs.split(" ")
                if config_arch not in architectures:
                    continue

            for option, option_value in options.items():
                if not check_option(component, details, config, config_path,
                                    option, option_value):
                    ret = False
                    # Stop after one non-detailed error
                    if not details:
                        return False
    return ret


def check_config(config_path, config_arch, pkgver, components_list=[],
                 details=False, enforce_check=True):
    """
    Check, whether one kernel config passes the rules of multiple components.

    :param config_path: full path to kernel config file
    :param config_arch: architecture name (alpine format, e.g. aarch64, x86_64)
    :param pkgver: kernel version
    :param components_list: what to check for, e.g. ["waydroid", "iwd"]
    :param details: print all warnings if True, otherwise one per component
    :param enforce_check: set to False to not fail kconfig check as long as
                          everything in kconfig_options is set correctly, even
                          if additional components are checked
    :returns: True if the check passed, False otherwise
    """
    logging.debug(f"Check kconfig: {config_path}")
    with open(config_path) as handle:
        config = handle.read()

    # Devices in all categories need basic options
    # https://wiki.postmarketos.org/wiki/Device_categorization
    components_list = ["postmarketOS"] + components_list

    # Devices in "community" or "main" need additional options
    if "community" in components_list:
        components_list += [
            "containers",
            "filesystems",
            "iwd",
            "netboot",
            "nftables",
            "usb_gadgets",
            "waydroid",
            "wireguard",
            "zram",
        ]

    components = {}
    for name in components_list:
        if name == "postmarketOS":
            pmb_config_var = "kconfig_options"
        else:
            pmb_config_var = f"kconfig_options_{name}"

        components[name] = getattr(pmb.config, pmb_config_var, None)
        assert components[name], f"invalid kconfig component name: {name}"

    results = []
    for component, options in components.items():
        result = check_config_options_set(config, config_path, config_arch,
                                          options, component, pkgver, details)
        # We always enforce "postmarketOS" component and when explicitly
        # requested
        if enforce_check or component == "postmarketOS":
            results += [result]

    return all(results)


def check(args, pkgname, components_list=[], details=False, must_exist=True):
    """
    Check for necessary kernel config options in a package.

    :param pkgname: the package to check for, optionally without "linux-"
    :param components_list: what to check for, e.g. ["waydroid", "iwd"]
    :param details: print all warnings if True, otherwise one generic warning
    :param must_exist: if False, just return if the package does not exist
    :returns: True when the check was successful, False otherwise
              None if the aport cannot be found (only if must_exist=False)
    """
    # Don't modify the original component_list (arguments are passed as
    # reference, a list is not immutable)
    components_list = components_list.copy()

    # Pkgname: allow omitting "linux-" prefix
    if pkgname.startswith("linux-"):
        flavor = pkgname.split("linux-")[1]
    else:
        flavor = pkgname

    # Read all kernel configs in the aport
    ret = True
    aport = pmb.helpers.pmaports.find(args, "linux-" + flavor, must_exist=must_exist)
    if aport is None:
        return None
    apkbuild = pmb.parse.apkbuild(f"{aport}/APKBUILD")
    pkgver = apkbuild["pkgver"]

    # We only enforce optional checks for community & main devices
    enforce_check = aport.split("/")[-2] in ["community", "main"]

    for name in get_all_component_names():
        if f"pmb:kconfigcheck-{name}" in apkbuild["options"] and \
                name not in components_list:
            components_list += [name]

    for config_path in glob.glob(aport + "/config-*"):
        # The architecture of the config is in the name, so it just needs to be
        # extracted
        config_name = os.path.basename(config_path)
        config_name_split = config_name.split(".")

        if len(config_name_split) != 2:
            raise RuntimeError(f"{config_name} is not a valid kernel config "
                               "name. Ensure that the _config property in your "
                               "kernel APKBUILD has a . before the "
                               "architecture name, e.g. .aarch64 or .armv7, "
                               "and that there is no excess punctuation "
                               "elsewhere in the name.")

        config_arch = config_name_split[1]
        ret &= check_config(config_path, config_arch, pkgver, components_list,
                            details=details, enforce_check=enforce_check)
    return ret


def extract_arch(config_path):
    # Extract the architecture out of the config
    with open(config_path) as f:
        config = f.read()
    if is_set(config, "ARM"):
        return "armv7"
    elif is_set(config, "ARM64"):
        return "aarch64"
    elif is_set(config, "RISCV"):
        return "riscv64"
    elif is_set(config, "X86_32"):
        return "x86"
    elif is_set(config, "X86_64"):
        return "x86_64"

    # No match
    logging.info("WARNING: failed to extract arch from kernel config")
    return "unknown"


def extract_version(config_path):
    # Try to extract the version string out of the comment header
    with open(config_path) as f:
        # Read the first 3 lines of the file and get the third line only
        text = [next(f) for x in range(3)][2]
    ver_match = re.match(r"# Linux/\S+ (\S+) Kernel Configuration", text)
    if ver_match:
        return ver_match.group(1).replace("-", "_")

    # No match
    logging.info("WARNING: failed to extract version from kernel config")
    return "unknown"


def check_file(config_path, components_list=[], details=False):
    """
    Check for necessary kernel config options in a kconfig file.

    :param config_path: full path to kernel config file
    :param components_list: what to check for, e.g. ["waydroid", "iwd"]
    :param details: print all warnings if True, otherwise one generic warning
    :returns: True when the check was successful, False otherwise
    """
    arch = extract_arch(config_path)
    version = extract_version(config_path)
    logging.debug(f"Check kconfig: parsed arch={arch}, version={version} from "
                  f"file: {config_path}")
    return check_config(config_path, arch, version, components_list,
                        details=details)
