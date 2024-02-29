# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import fnmatch
import logging
import re
import glob
import pmb.helpers.git


def indent_size(line):
    """
    Number of spaces at the beginning of a string.
    """
    matches = re.findall("^[ ]*", line)
    if len(matches) == 1:
        return len(matches[0])
    return 0


def format_function(name, body, remove_indent=4):
    """
    Format the body of a shell function passed to rewrite() below, so it fits
    the format of the original APKBUILD.
    :param remove_indent: Maximum number of spaces to remove from the
        beginning of each line of the function body.
    """
    tab_width = 4
    ret = ""
    lines = body.split("\n")
    for i in range(len(lines)):
        line = lines[i]
        if not line.strip():
            if not ret or i == len(lines) - 1:
                continue

        # Remove indent
        spaces = min(indent_size(line), remove_indent)
        line = line[spaces:]

        # Convert spaces to tabs
        spaces = indent_size(line)
        tabs = int(spaces / tab_width)
        line = ("\t" * tabs) + line[spaces:]

        ret += line + "\n"
    return name + "() {\n" + ret + "}\n"


def rewrite(args, pkgname, path_original="", fields={}, replace_pkgname=None,
            replace_functions={}, replace_simple={}, below_header="",
            remove_indent=4):
    """
    Append a header to $WORK/aportgen/APKBUILD, delete maintainer/contributor
    lines (so they won't be bugged with issues regarding our generated aports),
    and add reference to the original aport.

    :param path_original: The original path of the automatically generated
        aport.
    :param fields: key-value pairs of fields that shall be changed in the
        APKBUILD. For example: {"pkgdesc": "my new package", "subpkgs": ""}
    :param replace_pkgname: When set, $pkgname gets replaced with that string
        in every line.
    :param replace_functions: Function names and new bodies, for example:
        {"build": "return 0"}
        The body can also be None (deletes the function)
    :param replace_simple: Lines that fnmatch the pattern, get
        replaced/deleted. Example: {"*test*": "# test", "*mv test.bin*": None}
    :param below_header: String that gets directly placed below the header.
    :param remove_indent: Number of spaces to remove from function body
        provided to replace_functions.

    """
    # Header
    if path_original:
        lines_new = [
            "# Automatically generated aport, do not edit!\n",
            "# Generator: pmbootstrap aportgen " + pkgname + "\n",
            "# Based on: " + path_original + "\n",
            "\n",
        ]
    else:
        lines_new = [
            "# Forked from Alpine INSERT-REASON-HERE (CHANGEME!)\n",
            "\n",
        ]

    if below_header:
        for line in below_header.split("\n"):
            if not line[:8].strip():
                line = line[8:]
            lines_new += line.rstrip() + "\n"

    # Copy/modify lines, skip Maintainer/Contributor
    path = args.work + "/aportgen/APKBUILD"
    with open(path, "r+", encoding="utf-8") as handle:
        skip_in_func = False
        for line in handle.readlines():
            # Skip maintainer/contributor
            if line.startswith("# Maintainer") or line.startswith(
                    "# Contributor"):
                continue

            # Replace functions
            if skip_in_func:
                if line.startswith("}"):
                    skip_in_func = False
                continue
            else:
                for func, body in replace_functions.items():
                    if line.startswith(func + "() {"):
                        skip_in_func = True
                        if body:
                            lines_new += format_function(
                                func, body, remove_indent=remove_indent)
                        break
                if skip_in_func:
                    continue

            # Replace fields
            for key, value in fields.items():
                if line.startswith(key + "="):
                    if value:
                        if key in ["pkgname", "pkgver", "pkgrel"]:
                            # No quotes to avoid lint error
                            line = f"{key}={value}\n"
                        else:
                            line = f'{key}="{value}"\n'
                    else:
                        # Remove line without value to avoid lint error
                        line = ""
                    break

            # Replace $pkgname
            if replace_pkgname and "$pkgname" in line:
                line = line.replace("$pkgname", replace_pkgname)

            # Replace simple
            for pattern, replacement in replace_simple.items():
                if fnmatch.fnmatch(line, pattern + "\n"):
                    line = replacement
                    if replacement:
                        line += "\n"
                    break
            if line is None:
                continue

            lines_new.append(line)

        # Write back
        handle.seek(0)
        handle.write("".join(lines_new))
        handle.truncate()


def get_upstream_aport(args, pkgname, arch=None):
    """
    Perform a git checkout of Alpine's aports and get the path to the aport.

    :param pkgname: package name
    :param arch: Alpine architecture (e.g. "armhf"), defaults to native arch
    :returns: absolute path on disk where the Alpine aport is checked out
              example: /opt/pmbootstrap_work/cache_git/aports/upstream/main/gcc
    """
    # APKBUILD
    pmb.helpers.git.clone(args, "aports_upstream")
    aports_upstream_path = args.work + "/cache_git/aports_upstream"

    # Checkout branch
    channel_cfg = pmb.config.pmaports.read_config_channel(args)
    branch = channel_cfg["branch_aports"]
    logging.info(f"Checkout aports.git branch: {branch}")
    if pmb.helpers.run.user(args, ["git", "checkout", branch],
                            aports_upstream_path, check=False):
        logging.info("NOTE: run 'pmbootstrap pull' and try again")
        logging.info("NOTE: if it still fails, your aports.git was cloned with"
                     " an older version of pmbootstrap, as shallow clone."
                     " Unshallow it, or remove it and let pmbootstrap clone it"
                     f" again: {aports_upstream_path}")
        raise RuntimeError("Branch checkout failed.")

    # Search package
    paths = glob.glob(aports_upstream_path + "/*/" + pkgname)
    if len(paths) > 1:
        raise RuntimeError("Package " + pkgname + " found in multiple"
                           " aports subfolders.")
    elif len(paths) == 0:
        raise RuntimeError("Package " + pkgname + " not found in alpine"
                           " aports repository.")
    aport_path = paths[0]

    # Parse APKBUILD
    apkbuild = pmb.parse.apkbuild(f"{aport_path}/APKBUILD",
                                  check_pkgname=False)
    apkbuild_version = apkbuild["pkgver"] + "-r" + apkbuild["pkgrel"]

    # Binary package
    split = aport_path.split("/")
    repo = split[-2]
    pkgname = split[-1]
    index_path = pmb.helpers.repo.alpine_apkindex_path(args, repo, arch)
    package = pmb.parse.apkindex.package(args, pkgname, indexes=[index_path])

    # Compare version (return when equal)
    compare = pmb.parse.version.compare(apkbuild_version, package["version"])

    # APKBUILD > binary: this is fine
    if compare == 1:
        logging.info(f"NOTE: {pkgname} {arch} binary package has a lower"
                     f" version {package['version']} than the APKBUILD"
                     f" {apkbuild_version}")
        return aport_path

    # APKBUILD < binary: aports.git is outdated
    if compare == -1:
        logging.warning("WARNING: Package '" + pkgname + "' has a lower version in"
                  " local checkout of Alpine's aports (" + apkbuild_version +
                  ") compared to Alpine's binary package (" +
                  package["version"] + ")!")
        logging.info("NOTE: You can update your local checkout with: 'pmbootstrap pull'")

    return aport_path
