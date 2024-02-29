# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import logging

import pmb.helpers.run
import pmb.helpers.other
import pmb.parse
import pmb.parse.arch


def is_registered(arch_qemu):
    return os.path.exists("/proc/sys/fs/binfmt_misc/qemu-" + arch_qemu)


def register(args, arch):
    """
    Get arch, magic, mask.
    """
    arch_qemu = pmb.parse.arch.alpine_to_qemu(arch)

    # always make sure the qemu-<arch> binary is installed, since registering
    # may happen outside of this method (e.g. by OS)
    if f"qemu-{arch_qemu}" not in pmb.chroot.apk.installed(args):
        pmb.chroot.apk.install(args, ["qemu-" + arch_qemu])

    if is_registered(arch_qemu):
        return
    pmb.helpers.other.check_binfmt_misc(args)

    # Don't continue if the actions from check_binfmt_misc caused the OS to
    # automatically register the target arch
    if is_registered(arch_qemu):
        return

    info = pmb.parse.binfmt_info(arch_qemu)

    # Build registration string
    # https://en.wikipedia.org/wiki/Binfmt_misc
    # :name:type:offset:magic:mask:interpreter:flags
    name = "qemu-" + arch_qemu
    type = "M"
    offset = ""
    magic = info["magic"]
    mask = info["mask"]
    interpreter = "/usr/bin/qemu-" + arch_qemu + "-static"
    flags = "C"
    code = ":".join(["", name, type, offset, magic, mask, interpreter,
                     flags])

    # Register in binfmt_misc
    logging.info("Register qemu binfmt (" + arch_qemu + ")")
    register = "/proc/sys/fs/binfmt_misc/register"
    pmb.helpers.run.root(
        args, ["sh", "-c", 'echo "' + code + '" > ' + register])


def unregister(args, arch):
    arch_qemu = pmb.parse.arch.alpine_to_qemu(arch)
    binfmt_file = "/proc/sys/fs/binfmt_misc/qemu-" + arch_qemu
    if not os.path.exists(binfmt_file):
        return
    logging.info("Unregister qemu binfmt (" + arch_qemu + ")")
    pmb.helpers.run.root(args, ["sh", "-c", "echo -1 > " + binfmt_file])
