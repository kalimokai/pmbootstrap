# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import glob
import logging
import math
import os

import pmb.chroot
import pmb.config.pmaports
import pmb.config.workdir
import pmb.helpers.pmaports
import pmb.helpers.run
import pmb.parse.apkindex


def zap(args, confirm=True, dry=False, pkgs_local=False, http=False,
        pkgs_local_mismatch=False, pkgs_online_mismatch=False, distfiles=False,
        rust=False, netboot=False):
    """
    Shutdown everything inside the chroots (e.g. adb), umount
    everything and then safely remove folders from the work-directory.

    :param dry: Only show what would be deleted, do not delete for real
    :param pkgs_local: Remove *all* self-compiled packages (!)
    :param http: Clear the http cache (used e.g. for the initial apk download)
    :param pkgs_local_mismatch: Remove the packages that have
        a different version compared to what is in the aports folder.
    :param pkgs_online_mismatch: Clean out outdated binary packages
        downloaded from mirrors (e.g. from Alpine)
    :param distfiles: Clear the downloaded files cache
    :param rust: Remove rust related caches
    :param netboot: Remove images for netboot

    NOTE: This function gets called in pmb/config/init.py, with only args.work
    and args.device set!
    """
    # Get current work folder size
    if not dry:
        pmb.chroot.shutdown(args)
        logging.debug("Calculate work folder size")
        size_old = pmb.helpers.other.folder_size(args, args.work)

    # Delete packages with a different version compared to aports,
    # then re-index
    if pkgs_local_mismatch:
        zap_pkgs_local_mismatch(args, confirm, dry)

    # Delete outdated binary packages
    if pkgs_online_mismatch:
        zap_pkgs_online_mismatch(args, confirm, dry)

    pmb.chroot.shutdown(args)

    # Deletion patterns for folders inside args.work
    patterns = [
        "chroot_native",
        "chroot_buildroot_*",
        "chroot_installer_*",
        "chroot_rootfs_*",
    ]
    if pkgs_local:
        patterns += ["packages"]
    if http:
        patterns += ["cache_http"]
    if distfiles:
        patterns += ["cache_distfiles"]
    if rust:
        patterns += ["cache_rust"]
    if netboot:
        patterns += ["images_netboot"]

    # Delete everything matching the patterns
    for pattern in patterns:
        pattern = os.path.realpath(f"{args.work}/{pattern}")
        matches = glob.glob(pattern)
        for match in matches:
            if (not confirm or
                    pmb.helpers.cli.confirm(args, f"Remove {match}?")):
                logging.info(f"% rm -rf {match}")
                if not dry:
                    pmb.helpers.run.root(args, ["rm", "-rf", match])

    # Remove config init dates for deleted chroots
    pmb.config.workdir.clean(args)

    # Chroots were zapped, so no repo lists exist anymore
    pmb.helpers.other.cache["apk_repository_list_updated"].clear()

    # Print amount of cleaned up space
    if dry:
        logging.info("Dry run: nothing has been deleted")
    else:
        size_new = pmb.helpers.other.folder_size(args, args.work)
        mb = (size_old - size_new) / 1024
        logging.info(f"Cleared up ~{math.ceil(mb)} MB of space")


def zap_pkgs_local_mismatch(args, confirm=True, dry=False):
    channel = pmb.config.pmaports.read_config(args)["channel"]
    if not os.path.exists(f"{args.work}/packages/{channel}"):
        return

    question = "Remove binary packages that are newer than the corresponding" \
               f" pmaports (channel '{channel}')?"
    if confirm and not pmb.helpers.cli.confirm(args, question):
        return

    reindex = False
    pattern = f"{args.work}/packages/{channel}/*/APKINDEX.tar.gz"
    for apkindex_path in glob.glob(pattern):
        # Delete packages without same version in aports
        blocks = pmb.parse.apkindex.parse_blocks(apkindex_path)
        for block in blocks:
            pkgname = block["pkgname"]
            origin = block["origin"]
            version = block["version"]
            arch = block["arch"]

            # Apk path
            apk_path_short = f"{arch}/{pkgname}-{version}.apk"
            apk_path = f"{args.work}/packages/{channel}/{apk_path_short}"
            if not os.path.exists(apk_path):
                logging.info("WARNING: Package mentioned in index not"
                             f" found: {apk_path_short}")
                continue

            # Aport path
            aport_path = pmb.helpers.pmaports.find(args, origin, False)
            if not aport_path:
                logging.info(f"% rm {apk_path_short}"
                             f" ({origin} aport not found)")
                if not dry:
                    pmb.helpers.run.root(args, ["rm", apk_path])
                    reindex = True
                continue

            # Clear out any binary apks that do not match what is in aports
            apkbuild = pmb.parse.apkbuild(f"{aport_path}/APKBUILD")
            version_aport = f"{apkbuild['pkgver']}-r{apkbuild['pkgrel']}"
            if version != version_aport:
                logging.info(f"% rm {apk_path_short}"
                             f" ({origin} aport: {version_aport})")
                if not dry:
                    pmb.helpers.run.root(args, ["rm", apk_path])
                    reindex = True

    if reindex:
        pmb.build.other.index_repo(args)


def zap_pkgs_online_mismatch(args, confirm=True, dry=False):
    # Check whether we need to do anything
    paths = glob.glob(f"{args.work}/cache_apk_*")
    if not len(paths):
        return
    if (confirm and not pmb.helpers.cli.confirm(args,
                                                "Remove outdated"
                                                " binary packages?")):
        return

    # Iterate over existing apk caches
    for path in paths:
        arch = os.path.basename(path).split("_", 2)[2]
        suffix = f"buildroot_{arch}"
        if arch == pmb.config.arch_native:
            suffix = "native"

        # Clean the cache with apk
        logging.info(f"({suffix}) apk -v cache clean")
        if not dry:
            pmb.chroot.root(args, ["apk", "-v", "cache", "clean"], suffix)
