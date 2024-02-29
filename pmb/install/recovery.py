# Copyright 2023 Attila Szollosi
# SPDX-License-Identifier: GPL-3.0-or-later
import logging

import pmb.chroot
import pmb.config.pmaports
import pmb.flasher
import pmb.helpers.frontend


def create_zip(args, suffix):
    """
    Create android recovery compatible installer zip.
    """
    zip_root = "/var/lib/postmarketos-android-recovery-installer/"
    rootfs = "/mnt/rootfs_" + args.device
    flavor = pmb.helpers.frontend._parse_flavor(args)
    method = args.deviceinfo["flash_method"]
    vars = pmb.flasher.variables(args, flavor, method)

    # Install recovery installer package in buildroot
    pmb.chroot.apk.install(args,
                           ["postmarketos-android-recovery-installer"],
                           suffix)

    logging.info("(" + suffix + ") create recovery zip")

    for key in vars:
        pmb.flasher.check_partition_blacklist(args, key, vars[key])

    # Create config file for the recovery installer
    options = {
        "DEVICE": args.device,
        "FLASH_KERNEL": args.recovery_flash_kernel,
        "ISOREC": method == "heimdall-isorec",
        "KERNEL_PARTLABEL": vars["$PARTITION_KERNEL"],
        "INITFS_PARTLABEL": vars["$PARTITION_INITFS"],
        # Name is still "SYSTEM", not "ROOTFS" in the recovery installer
        "SYSTEM_PARTLABEL": vars["$PARTITION_ROOTFS"],
        "INSTALL_PARTITION": args.recovery_install_partition,
        "CIPHER": args.cipher,
        "FDE": args.full_disk_encryption,
    }

    # Backwards compatibility with old mkinitfs (pma#660)
    pmaports_cfg = pmb.config.pmaports.read_config(args)
    if pmaports_cfg.get("supported_mkinitfs_without_flavors", False):
        options["FLAVOR"] = ""
    else:
        options["FLAVOR"] = f"-{flavor}" if flavor is not None else "-"

    # Write to a temporary file
    config_temp = args.work + "/chroot_" + suffix + "/tmp/install_options"
    with open(config_temp, "w") as handle:
        for key, value in options.items():
            if isinstance(value, bool):
                value = str(value).lower()
            handle.write(key + "='" + value + "'\n")

    commands = [
        # Move config file from /tmp/ to zip root
        ["mv", "/tmp/install_options", "chroot/install_options"],
        # Create tar archive of the rootfs
        ["tar", "-pcf", "rootfs.tar", "--exclude", "./home", "-C", rootfs,
         "."],
        # Append packages keys
        ["tar", "-prf", "rootfs.tar", "-C", "/", "./etc/apk/keys"],
        # Compress with -1 for speed improvement
        ["gzip", "-f1", "rootfs.tar"],
        ["build-recovery-zip", args.device]]
    for command in commands:
        pmb.chroot.root(args, command, suffix, zip_root)
