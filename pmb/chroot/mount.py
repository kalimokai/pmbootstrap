# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import glob
import logging
import os
import pmb.config
import pmb.parse
import pmb.helpers.mount


def create_device_nodes(args, suffix):
    """
    Create device nodes for null, zero, full, random, urandom in the chroot.
    """
    try:
        chroot = args.work + "/chroot_" + suffix

        # Create all device nodes as specified in the config
        for dev in pmb.config.chroot_device_nodes:
            path = chroot + "/dev/" + str(dev[4])
            if not os.path.exists(path):
                pmb.helpers.run.root(args, ["mknod",
                                            "-m", str(dev[0]),  # permissions
                                            path,  # name
                                            str(dev[1]),  # type
                                            str(dev[2]),  # major
                                            str(dev[3]),  # minor
                                            ])

        # Verify major and minor numbers of created nodes
        for dev in pmb.config.chroot_device_nodes:
            path = chroot + "/dev/" + str(dev[4])
            stat_result = os.stat(path)
            rdev = stat_result.st_rdev
            assert os.major(rdev) == dev[2], "Wrong major in " + path
            assert os.minor(rdev) == dev[3], "Wrong minor in " + path

        # Verify /dev/zero reading and writing
        path = chroot + "/dev/zero"
        with open(path, "r+b", 0) as handle:
            assert handle.write(bytes([0xff])), "Write failed for " + path
            assert handle.read(1) == bytes([0x00]), "Read failed for " + path

    # On failure: Show filesystem-related error
    except Exception as e:
        logging.info(str(e) + "!")
        raise RuntimeError("Failed to create device nodes in the '" +
                           suffix + "' chroot.")


def mount_dev_tmpfs(args, suffix="native"):
    """
    Mount tmpfs inside the chroot's dev folder to make sure we can create
    device nodes, even if the filesystem of the work folder does not support
    it.
    """
    # Do nothing when it is already mounted
    dev = args.work + "/chroot_" + suffix + "/dev"
    if pmb.helpers.mount.ismount(dev):
        return

    # Create the $chroot/dev folder and mount tmpfs there
    pmb.helpers.run.root(args, ["mkdir", "-p", dev])
    pmb.helpers.run.root(args, ["mount", "-t", "tmpfs",
                                "-o", "size=1M,noexec,dev",
                                "tmpfs", dev])

    # Create pts, shm folders and device nodes
    pmb.helpers.run.root(args, ["mkdir", "-p", dev + "/pts", dev + "/shm"])
    pmb.helpers.run.root(args, ["mount", "-t", "tmpfs",
                                "-o", "nodev,nosuid,noexec",
                                "tmpfs", dev + "/shm"])
    create_device_nodes(args, suffix)

    # Setup /dev/fd as a symlink
    pmb.helpers.run.root(args, ["ln", "-sf", "/proc/self/fd", f"{dev}/"])


def mount(args, suffix="native"):
    # Mount tmpfs as the chroot's /dev
    mount_dev_tmpfs(args, suffix)

    # Get all mountpoints
    arch = pmb.parse.arch.from_chroot_suffix(args, suffix)
    channel = pmb.config.pmaports.read_config(args)["channel"]
    mountpoints = {}
    for source, target in pmb.config.chroot_mount_bind.items():
        source = source.replace("$WORK", args.work)
        source = source.replace("$ARCH", arch)
        source = source.replace("$CHANNEL", channel)
        mountpoints[source] = target

    # Mount if necessary
    for source, target in mountpoints.items():
        target_full = args.work + "/chroot_" + suffix + target
        pmb.helpers.mount.bind(args, source, target_full)


def mount_native_into_foreign(args, suffix):
    source = args.work + "/chroot_native"
    target = args.work + "/chroot_" + suffix + "/native"
    pmb.helpers.mount.bind(args, source, target)

    musl = os.path.basename(glob.glob(source + "/lib/ld-musl-*.so.1")[0])
    musl_link = args.work + "/chroot_" + suffix + "/lib/" + musl
    if not os.path.lexists(musl_link):
        pmb.helpers.run.root(args, ["ln", "-s", "/native/lib/" + musl,
                                    musl_link])
        pmb.helpers.run.root(args, ["ln", "-sf", "/native/bin/busybox", "/usr/local/bin/gzip"])

def remove_mnt_pmbootstrap(args, suffix):
    """ Safely remove /mnt/pmbootstrap directories from the chroot, without
        running rm -r as root and potentially removing data inside the
        mountpoint in case it was still mounted (bug in pmbootstrap, or user
        ran pmbootstrap 2x in parallel). This is similar to running 'rm -r -d',
        but we don't assume that the host's rm has the -d flag (busybox does
        not). """
    mnt_dir = f"{args.work}/chroot_{suffix}/mnt/pmbootstrap"

    if not os.path.exists(mnt_dir):
        return

    for path in glob.glob(f"{mnt_dir}/*") + [mnt_dir]:
        pmb.helpers.run.root(args, ["rmdir", path])
