# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import pmb.config.pmaports


def variables(args, flavor, method):
    _cmdline = args.deviceinfo["kernel_cmdline"] or ""
    if "cmdline" in args and args.cmdline:
        _cmdline = args.cmdline

    flash_pagesize = args.deviceinfo['flash_pagesize']

    # TODO Remove _partition_system deviceinfo support once pmaports has been
    # updated and minimum pmbootstrap version bumped.
    # See also https://gitlab.com/postmarketOS/pmbootstrap/-/issues/2243

    if method.startswith("fastboot"):
        _partition_kernel = args.deviceinfo["flash_fastboot_partition_kernel"]\
            or "boot"
        _partition_rootfs = args.deviceinfo["flash_fastboot_partition_rootfs"]\
            or args.deviceinfo["flash_fastboot_partition_system"] or "userdata"
        _partition_vbmeta = args.deviceinfo["flash_fastboot_partition_vbmeta"]\
            or None
        _partition_dtbo = args.deviceinfo["flash_fastboot_partition_dtbo"]\
            or None
    # Require that the partitions are specified in deviceinfo for now
    elif method.startswith("rkdeveloptool"):
        _partition_kernel = args.deviceinfo["flash_rk_partition_kernel"]\
            or None
        _partition_rootfs = args.deviceinfo["flash_rk_partition_rootfs"]\
            or args.deviceinfo["flash_rk_partition_system"] or None
        _partition_vbmeta = None
        _partition_dtbo = None
    elif method.startswith("mtkclient"):
        _partition_kernel = args.deviceinfo["flash_mtkclient_partition_kernel"]\
            or "boot"
        _partition_rootfs = args.deviceinfo["flash_mtkclient_partition_rootfs"]\
            or "userdata"
        _partition_vbmeta = args.deviceinfo["flash_mtkclient_partition_vbmeta"]\
            or None
        _partition_dtbo = args.deviceinfo["flash_mtkclient_partition_dtbo"]\
            or None
    else:
        _partition_kernel = args.deviceinfo["flash_heimdall_partition_kernel"]\
            or "KERNEL"
        _partition_rootfs = args.deviceinfo["flash_heimdall_partition_rootfs"]\
            or args.deviceinfo["flash_heimdall_partition_system"] or "SYSTEM"
        _partition_vbmeta = args.deviceinfo["flash_heimdall_partition_vbmeta"]\
            or None
        _partition_dtbo = args.deviceinfo["flash_heimdall_partition_dtbo"]\
            or None

    if "partition" in args and args.partition:
        # Only one operation is done at same time so it doesn't matter
        # sharing the arg
        _partition_kernel = args.partition
        _partition_rootfs = args.partition
        _partition_vbmeta = args.partition
        _partition_dtbo = args.partition

    _dtb = ""
    if args.deviceinfo["append_dtb"] == "true":
        _dtb = "-dtb"
    
    _no_reboot = ""
    if getattr(args, 'no_reboot', False):
        _no_reboot = "--no-reboot"

    _resume = ""
    if getattr(args,'resume', False):
        _resume = "--resume"

    vars = {
        "$BOOT": "/mnt/rootfs_" + args.device + "/boot",
        "$DTB": _dtb,
        "$IMAGE_SPLIT_BOOT": "/home/pmos/rootfs/" + args.device + "-boot.img",
        "$IMAGE_SPLIT_ROOT": "/home/pmos/rootfs/" + args.device + "-root.img",
        "$IMAGE": "/home/pmos/rootfs/" + args.device + ".img",
        "$KERNEL_CMDLINE": _cmdline,
        "$PARTITION_KERNEL": _partition_kernel,
        "$PARTITION_INITFS": args.deviceinfo[
            "flash_heimdall_partition_initfs"] or "RECOVERY",
        "$PARTITION_ROOTFS": _partition_rootfs,
        "$PARTITION_VBMETA": _partition_vbmeta,
        "$PARTITION_DTBO": _partition_dtbo,
        "$FLASH_PAGESIZE": flash_pagesize,
        "$RECOVERY_ZIP": "/mnt/buildroot_" + args.deviceinfo["arch"] +
                         "/var/lib/postmarketos-android-recovery-installer"
                         "/pmos-" + args.device + ".zip",
        "$UUU_SCRIPT": "/mnt/rootfs_" + args.deviceinfo["codename"] +
                       "/usr/share/uuu/flash_script.lst",
        "$NO_REBOOT": _no_reboot,
        "$RESUME": _resume
    }

    # Backwards compatibility with old mkinitfs (pma#660)
    pmaports_cfg = pmb.config.pmaports.read_config(args)
    if pmaports_cfg.get("supported_mkinitfs_without_flavors", False):
        vars["$FLAVOR"] = ""
    else:
        vars["$FLAVOR"] = f"-{flavor}" if flavor is not None else "-"

    return vars
