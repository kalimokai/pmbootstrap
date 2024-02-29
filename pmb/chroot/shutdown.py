# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import glob
import os
import socket
from contextlib import closing

import pmb.chroot
import pmb.helpers.mount
import pmb.install.losetup
import pmb.parse.arch


def kill_adb(args):
    """
    Kill adb daemon if it's running.
    """
    port = 5038
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            pmb.chroot.root(args, ["adb", "-P", str(port), "kill-server"])


def kill_sccache(args):
    """
    Kill sccache daemon if it's running. Unlike ccache it automatically spawns
    a daemon when you call it and exits after some time of inactivity.
    """
    port = 4226
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        if sock.connect_ex(("127.0.0.1", port)) == 0:
            pmb.chroot.root(args, ["sccache", "--stop-server"])


def shutdown_cryptsetup_device(args, name):
    """
    :param name: cryptsetup device name, usually "pm_crypt" in pmbootstrap
    """
    if not os.path.exists(args.work + "/chroot_native/dev/mapper/" + name):
        return
    pmb.chroot.apk.install(args, ["cryptsetup"])
    status = pmb.chroot.root(args, ["cryptsetup", "status", name],
                             output_return=True, check=False)
    if not status:
        logging.warning("WARNING: Failed to run cryptsetup to get the status"
                        " for " + name + ", assuming it is not mounted"
                        " (shutdown fails later if it is)!")
        return

    if status.startswith("/dev/mapper/" + name + " is active."):
        pmb.chroot.root(args, ["cryptsetup", "luksClose", name])
    elif status.startswith("/dev/mapper/" + name + " is inactive."):
        # When "cryptsetup status" fails, the device is not mounted and we
        # have a left over file (#83)
        pmb.chroot.root(args, ["rm", "/dev/mapper/" + name])
    else:
        raise RuntimeError("Failed to parse 'cryptsetup status' output!")


def shutdown(args, only_install_related=False):
    # Stop daemons
    kill_adb(args)
    kill_sccache(args)

    # Umount installation-related paths (order is important!)
    pmb.helpers.mount.umount_all(args, args.work +
                                 "/chroot_native/mnt/install")
    shutdown_cryptsetup_device(args, "pm_crypt")

    # Umount all losetup mounted images
    chroot = args.work + "/chroot_native"
    if pmb.helpers.mount.ismount(chroot + "/dev/loop-control"):
        pattern = chroot + "/home/pmos/rootfs/*.img"
        for path_outside in glob.glob(pattern):
            path = path_outside[len(chroot):]
            pmb.install.losetup.umount(args, path, auto_init=False)

    # Umount device rootfs and installer chroots
    for prefix in ["rootfs", "installer"]:
        path = f"{args.work}/chroot_{prefix}_{args.device}"
        if os.path.exists(path):
            pmb.helpers.mount.umount_all(args, path)

    # Remove "in-pmbootstrap" marker from all chroots. This marker indicates
    # that pmbootstrap has set up all mount points etc. to run programs inside
    # the chroots, but we want it gone afterwards (e.g. when the chroot
    # contents get copied to a rootfs / installer image, or if creating an
    # android recovery zip from its contents).
    for marker in glob.glob(f"{args.work}/chroot_*/in-pmbootstrap"):
        pmb.helpers.run.root(args, ["rm", marker])

    if not only_install_related:
        # Umount all folders inside args.work
        # The folders are explicitly iterated over, so folders symlinked inside
        # args.work get umounted as well (used in test_pkgrel_bump.py, #1595)
        for path in glob.glob(args.work + "/*"):
            pmb.helpers.mount.umount_all(args, path)

        # Clean up the rest
        for arch in pmb.config.build_device_architectures:
            if pmb.parse.arch.cpu_emulation_required(arch):
                pmb.chroot.binfmt.unregister(args, arch)
        logging.debug("Shutdown complete")
