# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import pmb.chroot.apk
import pmb.config
import pmb.config.pmaports
import pmb.helpers.mount


def install_depends(args):
    if hasattr(args, 'flash_method'):
        method = args.flash_method or args.deviceinfo["flash_method"]
    else:
        method = args.deviceinfo["flash_method"]

    if method not in pmb.config.flashers:
        raise RuntimeError(f"Flash method {method} is not supported by the"
                           " current configuration. However, adding a new"
                           " flash method is not that hard, when the flashing"
                           " application already exists.\n"
                           "Make sure, it is packaged for Alpine Linux, or"
                           " package it yourself, and then add it to"
                           " pmb/config/__init__.py.")
    depends = pmb.config.flashers[method]["depends"]

    # Depends for some flash methods may be different for various pmaports
    # branches, so read them from pmaports.cfg.
    if method == "fastboot":
        pmaports_cfg = pmb.config.pmaports.read_config(args)
        depends = pmaports_cfg.get("supported_fastboot_depends",
                                   "android-tools,avbtool").split(",")
    elif method == "heimdall-bootimg":
        pmaports_cfg = pmb.config.pmaports.read_config(args)
        depends = pmaports_cfg.get("supported_heimdall_depends",
                                   "heimdall,avbtool").split(",")
    elif method == "mtkclient":
        pmaports_cfg = pmb.config.pmaports.read_config(args)
        depends = pmaports_cfg.get("supported_mtkclient_depends",
                                   "mtkclient,android-tools").split(",")

    pmb.chroot.apk.install(args, depends)


def init(args):
    install_depends(args)

    # Mount folders from host system
    for folder in pmb.config.flash_mount_bind:
        pmb.helpers.mount.bind(args, folder, args.work +
                               "/chroot_native" + folder)

    # Mount device chroot inside native chroot (required for kernel/ramdisk)
    mountpoint = "/mnt/rootfs_" + args.device
    pmb.helpers.mount.bind(args, args.work + "/chroot_rootfs_" + args.device,
                           args.work + "/chroot_native" + mountpoint)
