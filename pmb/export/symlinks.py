# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import os
import glob

import pmb.build
import pmb.chroot.apk
import pmb.config
import pmb.config.pmaports
import pmb.flasher
import pmb.helpers.file


def symlinks(args, flavor, folder):
    """
    Create convenience symlinks to the rootfs and boot files.
    """

    # Backwards compatibility with old mkinitfs (pma#660)
    suffix = f"-{flavor}"
    pmaports_cfg = pmb.config.pmaports.read_config(args)
    if pmaports_cfg.get("supported_mkinitfs_without_flavors", False):
        suffix = ""

    # File descriptions
    info = {
        f"boot.img{suffix}": ("Fastboot compatible boot.img file,"
                              " contains initramfs and kernel"),
        "dtbo.img": "Fastboot compatible dtbo image",
        f"initramfs{suffix}": "Initramfs",
        f"initramfs{suffix}-extra": "Extra initramfs files in /boot",
        f"uInitrd{suffix}": "Initramfs, legacy u-boot image format",
        f"uImage{suffix}": "Kernel, legacy u-boot image format",
        f"vmlinuz{suffix}": "Linux kernel",
        f"{args.device}.img": "Rootfs with partitions for /boot and /",
        f"{args.device}-boot.img": "Boot partition image",
        f"{args.device}-root.img": "Root partition image",
        f"pmos-{args.device}.zip": "Android recovery flashable zip",
        "lk2nd.img": "Secondary Android bootloader",
    }

    # Generate a list of patterns
    path_native = args.work + "/chroot_native"
    path_boot = args.work + "/chroot_rootfs_" + args.device + "/boot"
    path_buildroot = args.work + "/chroot_buildroot_" + args.deviceinfo["arch"]
    patterns = [f"{path_boot}/boot.img{suffix}",
                f"{path_boot}/initramfs{suffix}*",
                f"{path_boot}/uInitrd{suffix}",
                f"{path_boot}/uImage{suffix}",
                f"{path_boot}/vmlinuz{suffix}",
                f"{path_boot}/dtbo.img",
                f"{path_native}/home/pmos/rootfs/{args.device}.img",
                f"{path_native}/home/pmos/rootfs/{args.device}-boot.img",
                f"{path_native}/home/pmos/rootfs/{args.device}-root.img",
                f"{path_buildroot}/var/lib/postmarketos-android-recovery-" +
                f"installer/pmos-{args.device}.zip",
                f"{path_boot}/lk2nd.img"]

    # Generate a list of files from the patterns
    files = []
    for pattern in patterns:
        files += glob.glob(pattern)

    # Iterate through all files
    for file in files:
        basename = os.path.basename(file)
        link = folder + "/" + basename

        # Display a readable message
        msg = " * " + basename
        if basename in info:
            msg += " (" + info[basename] + ")"
        logging.info(msg)

        pmb.helpers.file.symlink(args, file, link)
