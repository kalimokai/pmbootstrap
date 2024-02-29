# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import os
import glob
import pmb.helpers.mount
import pmb.install.losetup
import pmb.helpers.cli
import pmb.config


def previous_install(args, path):
    """
    Search the disk for possible existence of a previous installation of
    pmOS. We temporarily mount the possible pmOS_boot partition as
    /dev/diskp1 inside the native chroot to check the label from there.
    :param path: path to disk block device (e.g. /dev/mmcblk0)
    """
    label = ""
    for blockdevice_outside in [f"{path}1", f"{path}p1"]:
        if not os.path.exists(blockdevice_outside):
            continue
        blockdevice_inside = "/dev/diskp1"
        pmb.helpers.mount.bind_file(args, blockdevice_outside,
                                    args.work + '/chroot_native' +
                                    blockdevice_inside)
        try:
            label = pmb.chroot.root(args, ["blkid", "-s", "LABEL",
                                           "-o", "value",
                                           blockdevice_inside],
                                    output_return=True)
        except RuntimeError:
            logging.info("WARNING: Could not get block device label,"
                         " assume no previous installation on that partition")

        pmb.helpers.run.root(args, ["umount", args.work + "/chroot_native" +
                                    blockdevice_inside])
    return "pmOS_boot" in label


def mount_disk(args, path):
    """
    :param path: path to disk block device (e.g. /dev/mmcblk0)
    """
    # Sanity checks
    if not os.path.exists(path):
        raise RuntimeError(f"The disk block device does not exist: {path}")
    for path_mount in glob.glob(f"{path}*"):
        if pmb.helpers.mount.ismount(path_mount):
            raise RuntimeError(f"{path_mount} is mounted! Will not attempt to"
                               " format this!")
    logging.info(f"(native) mount /dev/install (host: {path})")
    pmb.helpers.mount.bind_file(args, path,
                                args.work + "/chroot_native/dev/install")
    if previous_install(args, path):
        if not pmb.helpers.cli.confirm(args, "WARNING: This device has a"
                                       " previous installation of pmOS."
                                       " CONTINUE?"):
            raise RuntimeError("Aborted.")
    else:
        if not pmb.helpers.cli.confirm(args, f"EVERYTHING ON {path} WILL BE"
                                       " ERASED! CONTINUE?"):
            raise RuntimeError("Aborted.")


def create_and_mount_image(args, size_boot, size_root, size_reserve,
                           split=False):
    """
    Create a new image file, and mount it as /dev/install.

    :param size_boot: size of the boot partition in MiB
    :param size_root: size of the root partition in MiB
    :param size_reserve: empty partition between root and boot in MiB (pma#463)
    :param split: create separate images for boot and root partitions
    """

    # Short variables for paths
    chroot = args.work + "/chroot_native"
    img_path_prefix = "/home/pmos/rootfs/" + args.device
    img_path_full = img_path_prefix + ".img"
    img_path_boot = img_path_prefix + "-boot.img"
    img_path_root = img_path_prefix + "-root.img"

    # Umount and delete existing images
    for img_path in [img_path_full, img_path_boot, img_path_root]:
        outside = chroot + img_path
        if os.path.exists(outside):
            pmb.helpers.mount.umount_all(args, chroot + "/mnt")
            pmb.install.losetup.umount(args, img_path)
            pmb.chroot.root(args, ["rm", img_path])

    # Make sure there is enough free space
    size_mb = round(size_boot + size_reserve + size_root)
    disk_data = os.statvfs(args.work)
    free = round((disk_data.f_bsize * disk_data.f_bavail) / (1024**2))
    if size_mb > free:
        raise RuntimeError("Not enough free space to create rootfs image! "
                           f"(free: {free}M, required: {size_mb}M)")

    # Create empty image files
    pmb.chroot.user(args, ["mkdir", "-p", "/home/pmos/rootfs"])
    size_mb_full = str(size_mb) + "M"
    size_mb_boot = str(round(size_boot)) + "M"
    size_mb_root = str(round(size_root)) + "M"
    images = {img_path_full: size_mb_full}
    if split:
        images = {img_path_boot: size_mb_boot,
                  img_path_root: size_mb_root}
    for img_path, size_mb in images.items():
        logging.info(f"(native) create {os.path.basename(img_path)} "
                     f"({size_mb})")
        pmb.chroot.root(args, ["truncate", "-s", size_mb, img_path])

    # Mount to /dev/install
    mount_image_paths = {img_path_full: "/dev/install"}
    if split:
        mount_image_paths = {img_path_boot: "/dev/installp1",
                             img_path_root: "/dev/installp2"}

    for img_path, mount_point in mount_image_paths.items():
        logging.info("(native) mount " + mount_point +
                     " (" + os.path.basename(img_path) + ")")
        pmb.install.losetup.mount(args, img_path)
        device = pmb.install.losetup.device_by_back_file(args, img_path)
        pmb.helpers.mount.bind_file(args, device,
                                    args.work + "/chroot_native" + mount_point)


def create(args, size_boot, size_root, size_reserve, split, disk):
    """
    Create /dev/install (the "install blockdevice").

    :param size_boot: size of the boot partition in MiB
    :param size_root: size of the root partition in MiB
    :param size_reserve: empty partition between root and boot in MiB (pma#463)
    :param split: create separate images for boot and root partitions
    :param disk: path to disk block device (e.g. /dev/mmcblk0) or None
    """
    pmb.helpers.mount.umount_all(
        args, args.work + "/chroot_native/dev/install")
    if disk:
        mount_disk(args, disk)
    else:
        create_and_mount_image(args, size_boot, size_root, size_reserve,
                               split)
