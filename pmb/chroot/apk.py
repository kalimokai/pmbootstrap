# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import logging
import shlex

import pmb.chroot
import pmb.config
import pmb.helpers.apk
import pmb.helpers.pmaports
import pmb.parse.apkindex
import pmb.parse.arch
import pmb.parse.depends
import pmb.parse.version


def update_repository_list(args, suffix="native", check=False):
    """
    Update /etc/apk/repositories, if it is outdated (when the user changed the
    --mirror-alpine or --mirror-pmOS parameters).

    :param check: This function calls it self after updating the
                  /etc/apk/repositories file, to check if it was successful.
                  Only for this purpose, the "check" parameter should be set to
                  True.
    """
    # Skip if we already did this
    if suffix in pmb.helpers.other.cache["apk_repository_list_updated"]:
        return

    # Read old entries or create folder structure
    path = f"{args.work}/chroot_{suffix}/etc/apk/repositories"
    lines_old = []
    if os.path.exists(path):
        # Read all old lines
        lines_old = []
        with open(path) as handle:
            for line in handle:
                lines_old.append(line[:-1])
    else:
        pmb.helpers.run.root(args, ["mkdir", "-p", os.path.dirname(path)])

    # Up to date: Save cache, return
    lines_new = pmb.helpers.repo.urls(args)
    if lines_old == lines_new:
        pmb.helpers.other.cache["apk_repository_list_updated"].append(suffix)
        return

    # Check phase: raise error when still outdated
    if check:
        raise RuntimeError(f"Failed to update: {path}")

    # Update the file
    logging.debug(f"({suffix}) update /etc/apk/repositories")
    if os.path.exists(path):
        pmb.helpers.run.root(args, ["rm", path])
    for line in lines_new:
        pmb.helpers.run.root(args, ["sh", "-c", "echo "
                                    f"{shlex.quote(line)} >> {path}"])
    update_repository_list(args, suffix, True)


def check_min_version(args, suffix="native"):
    """
    Check the minimum apk version, before running it the first time in the
    current session (lifetime of one pmbootstrap call).
    """

    # Skip if we already did this
    if suffix in pmb.helpers.other.cache["apk_min_version_checked"]:
        return

    # Skip if apk is not installed yet
    if not os.path.exists(f"{args.work}/chroot_{suffix}/sbin/apk"):
        logging.debug(f"NOTE: Skipped apk version check for chroot '{suffix}'"
                      ", because it is not installed yet!")
        return

    # Compare
    version_installed = installed(args, suffix)["apk-tools"]["version"]
    pmb.helpers.apk.check_outdated(
        args, version_installed,
        "Delete your http cache and zap all chroots, then try again:"
        " 'pmbootstrap zap -hc'")

    # Mark this suffix as checked
    pmb.helpers.other.cache["apk_min_version_checked"].append(suffix)


def install_build(args, package, arch):
    """
    Build an outdated package unless pmbootstrap was invoked with
    "pmbootstrap install" and the option to build packages during pmb install
    is disabled.

    :param package: name of the package to build
    :param arch: architecture of the package to build
    """
    # User may have disabled building packages during "pmbootstrap install"
    if args.action == "install" and not args.build_pkgs_on_install:
        if not pmb.parse.apkindex.package(args, package, arch, False):
            raise RuntimeError(f"{package}: no binary package found for"
                               f" {arch}, and compiling packages during"
                               " 'pmbootstrap install' has been disabled."
                               " Consider changing this option in"
                               " 'pmbootstrap init'.")
        # Use the existing binary package
        return

    # Build the package if it's in pmaports and there is no binary package
    # with the same pkgver and pkgrel. This check is done in
    # pmb.build.is_necessary, which gets called in pmb.build.package.
    return pmb.build.package(args, package, arch)


def packages_split_to_add_del(packages):
    """
    Sort packages into "to_add" and "to_del" lists depending on their pkgname
    starting with an exclamation mark.

    :param packages: list of pkgnames
    :returns: (to_add, to_del) - tuple of lists of pkgnames, e.g.
              (["hello-world", ...], ["some-conflict-pkg", ...])
    """
    to_add = []
    to_del = []

    for package in packages:
        if package.startswith("!"):
            to_del.append(package.lstrip("!"))
        else:
            to_add.append(package)

    return (to_add, to_del)


def packages_get_locally_built_apks(args, packages, arch):
    """
    Iterate over packages and if existing, get paths to locally built packages.
    This is used to force apk to upgrade packages to newer local versions, even
    if the pkgver and pkgrel did not change.

    :param packages: list of pkgnames
    :param arch: architecture that the locally built packages should have
    :returns: list of apk file paths that are valid inside the chroots, e.g.
              ["/mnt/pmbootstrap/packages/x86_64/hello-world-1-r6.apk", ...]
    """
    channel = pmb.config.pmaports.read_config(args)["channel"]
    ret = []

    for package in packages:
        data_repo = pmb.parse.apkindex.package(args, package, arch, False)
        if not data_repo:
            continue

        apk_file = f"{package}-{data_repo['version']}.apk"
        if not os.path.exists(f"{args.work}/packages/{channel}/{arch}/{apk_file}"):
            continue

        ret.append(f"/mnt/pmbootstrap/packages/{arch}/{apk_file}")

    return ret


def install_run_apk(args, to_add, to_add_local, to_del, suffix):
    """
    Run apk to add packages, and ensure only the desired packages get
    explicitly marked as installed.

    :param to_add: list of pkgnames to install, without their dependencies
    :param to_add_local: return of packages_get_locally_built_apks()
    :param to_del: list of pkgnames to be deleted, this should be set to
                   conflicting dependencies in any of the packages to be
                   installed or their dependencies (e.g. ["osk-sdl"])
    :param suffix: the chroot suffix, e.g. "native" or "rootfs_qemu-amd64"
    """
    # Sanitize packages: don't allow '--allow-untrusted' and other options
    # to be passed to apk!
    for package in to_add + to_add_local + to_del:
        if package.startswith("-"):
            raise ValueError(f"Invalid package name: {package}")

    commands = [["add"] + to_add]

    # Use a virtual package to mark only the explicitly requested packages as
    # explicitly installed, not the ones in to_add_local
    if to_add_local:
        commands += [["add", "-u", "--virtual", ".pmbootstrap"] + to_add_local,
                     ["del", ".pmbootstrap"]]

    if to_del:
        commands += [["del"] + to_del]

    for (i, command) in enumerate(commands):
        # --no-interactive is a parameter to `add`, so it must be appended or apk
        # gets confused
        command += ["--no-interactive"]

        if args.offline:
            command = ["--no-network"] + command
        if i == 0:
            pmb.helpers.apk.apk_with_progress(args, ["apk"] + command,
                                              chroot=True, suffix=suffix)
        else:
            # Virtual package related commands don't actually install or remove
            # packages, but only mark the right ones as explicitly installed.
            # They finish up almost instantly, so don't display a progress bar.
            pmb.chroot.root(args, ["apk", "--no-progress"] + command,
                            suffix=suffix)


def install(args, packages, suffix="native", build=True):
    """
    Install packages from pmbootstrap's local package index or the pmOS/Alpine
    binary package mirrors. Iterate over all dependencies recursively, and
    build missing packages as necessary.

    :param packages: list of pkgnames to be installed
    :param suffix: the chroot suffix, e.g. "native" or "rootfs_qemu-amd64"
    :param build: automatically build the package, when it does not exist yet
                  or needs to be updated, and it is inside pmaports. For the
                  special case that all packages are expected to be in Alpine's
                  repositories, set this to False for performance optimization.
    """
    arch = pmb.parse.arch.from_chroot_suffix(args, suffix)

    if not packages:
        logging.verbose("pmb.chroot.apk.install called with empty packages list,"
                        " ignoring")
        return

    # Initialize chroot
    check_min_version(args, suffix)
    pmb.chroot.init(args, suffix)

    packages_with_depends = pmb.parse.depends.recurse(args, packages, suffix)
    to_add, to_del = packages_split_to_add_del(packages_with_depends)

    if build:
        for package in to_add:
            install_build(args, package, arch)

    to_add_local = packages_get_locally_built_apks(args, to_add, arch)
    to_add_no_deps, _ = packages_split_to_add_del(packages)

    logging.info(f"({suffix}) install {' '.join(to_add_no_deps)}")
    install_run_apk(args, to_add_no_deps, to_add_local, to_del, suffix)


def installed(args, suffix="native"):
    """
    Read the list of installed packages (which has almost the same format, as
    an APKINDEX, but with more keys).

    :returns: a dictionary with the following structure:
              { "postmarketos-mkinitfs":
                {
                  "pkgname": "postmarketos-mkinitfs"
                  "version": "0.0.4-r10",
                  "depends": ["busybox-extras", "lddtree", ...],
                  "provides": ["mkinitfs=0.0.1"]
                }, ...
              }
    """
    path = f"{args.work}/chroot_{suffix}/lib/apk/db/installed"
    return pmb.parse.apkindex.parse(path, False)
