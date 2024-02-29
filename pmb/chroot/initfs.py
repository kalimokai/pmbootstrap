# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import logging
import pmb.chroot.initfs_hooks
import pmb.chroot.other
import pmb.chroot.apk
import pmb.config.pmaports
import pmb.helpers.cli


def build(args, flavor, suffix):
    # Update mkinitfs and hooks
    pmb.chroot.apk.install(args, ["postmarketos-mkinitfs"], suffix)
    pmb.chroot.initfs_hooks.update(args, suffix)
    pmaports_cfg = pmb.config.pmaports.read_config(args)

    # Call mkinitfs
    logging.info(f"({suffix}) mkinitfs {flavor}")
    if pmaports_cfg.get("supported_mkinitfs_without_flavors", False):
        pmb.chroot.root(args, ["mkinitfs"], suffix)
    else:
        release_file = (f"{args.work}/chroot_{suffix}/usr/share/kernel/"
                        f"{flavor}/kernel.release")
        with open(release_file, "r") as handle:
            release = handle.read().rstrip()
            pmb.chroot.root(args, ["mkinitfs", "-o",
                                   f"/boot/initramfs-{flavor}", release],
                            suffix)


def extract(args, flavor, suffix, extra=False):
    """
    Extract the initramfs to /tmp/initfs-extracted or the initramfs-extra to
    /tmp/initfs-extra-extracted and return the outside extraction path.
    """
    # Extraction folder
    inside = "/tmp/initfs-extracted"

    pmaports_cfg = pmb.config.pmaports.read_config(args)
    if pmaports_cfg.get("supported_mkinitfs_without_flavors", False):
        initfs_file = "/boot/initramfs"
    else:
        initfs_file = f"/boot/initramfs-${flavor}"
    if extra:
        inside = "/tmp/initfs-extra-extracted"
        initfs_file += "-extra"

    outside = f"{args.work}/chroot_{suffix}{inside}"
    if os.path.exists(outside):
        if not pmb.helpers.cli.confirm(args, f"Extraction folder {outside}"
                                       " already exists."
                                       " Do you want to overwrite it?"):
            raise RuntimeError("Aborted!")
        pmb.chroot.root(args, ["rm", "-r", inside], suffix)

    # Extraction script (because passing a file to stdin is not allowed
    # in pmbootstrap's chroot/shell functions for security reasons)
    with open(f"{args.work}/chroot_{suffix}/tmp/_extract.sh", "w") as handle:
        handle.write(
            "#!/bin/sh\n"
            f"cd {inside} && cpio -i < _initfs\n")

    # Extract
    commands = [["mkdir", "-p", inside],
                ["cp", initfs_file, f"{inside}/_initfs.gz"],
                ["gzip", "-d", f"{inside}/_initfs.gz"],
                ["cat", "/tmp/_extract.sh"],  # for the log
                ["sh", "/tmp/_extract.sh"],
                ["rm", "/tmp/_extract.sh", f"{inside}/_initfs"]
                ]
    for command in commands:
        pmb.chroot.root(args, command, suffix)

    # Return outside path for logging
    return outside


def ls(args, flavor, suffix, extra=False):
    tmp = "/tmp/initfs-extracted"
    if extra:
        tmp = "/tmp/initfs-extra-extracted"
    extract(args, flavor, suffix, extra)
    pmb.chroot.root(args, ["ls", "-lahR", "."], suffix, tmp, "stdout")
    pmb.chroot.root(args, ["rm", "-r", tmp], suffix)


def frontend(args):
    # Find the appropriate kernel flavor
    suffix = f"rootfs_{args.device}"
    flavor = pmb.chroot.other.kernel_flavor_installed(args, suffix)

    # Handle initfs actions
    action = args.action_initfs
    if action == "build":
        build(args, flavor, suffix)
    elif action == "extract":
        dir = extract(args, flavor, suffix)
        logging.info(f"Successfully extracted initramfs to: {dir}")
        dir_extra = extract(args, flavor, suffix, True)
        logging.info(f"Successfully extracted initramfs-extra to: {dir_extra}")
    elif action == "ls":
        logging.info("*** initramfs ***")
        ls(args, flavor, suffix)
        logging.info("*** initramfs-extra ***")
        ls(args, flavor, suffix, True)

    # Handle hook actions
    elif action == "hook_ls":
        pmb.chroot.initfs_hooks.ls(args, suffix)
    else:
        if action == "hook_add":
            pmb.chroot.initfs_hooks.add(args, args.hook, suffix)
        elif action == "hook_del":
            pmb.chroot.initfs_hooks.delete(args, args.hook, suffix)

        # Rebuild the initfs after adding/removing a hook
        build(args, flavor, suffix)

    if action in ["ls", "extract"]:
        link = "https://wiki.postmarketos.org/wiki/Initramfs_development"
        logging.info(f"See also: <{link}>")
