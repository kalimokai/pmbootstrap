# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import logging

import pmb.chroot
import pmb.build
import pmb.helpers.run
import pmb.helpers.pmaports


def update(args, pkgname):
    """ Fetch all sources and update the checksums in the APKBUILD. """
    pmb.build.init_abuild_minimal(args)
    pmb.build.copy_to_buildpath(args, pkgname)
    logging.info("(native) generate checksums for " + pkgname)
    pmb.chroot.user(args, ["abuild", "checksum"],
                    working_dir="/home/pmos/build")

    # Copy modified APKBUILD back
    source = args.work + "/chroot_native/home/pmos/build/APKBUILD"
    target = pmb.helpers.pmaports.find(args, pkgname) + "/"
    pmb.helpers.run.user(args, ["cp", source, target])


def verify(args, pkgname):
    """ Fetch all sources and verify their checksums. """
    pmb.build.init_abuild_minimal(args)
    pmb.build.copy_to_buildpath(args, pkgname)
    logging.info("(native) verify checksums for " + pkgname)

    # Fetch and verify sources, "fetch" alone does not verify them:
    # https://github.com/alpinelinux/abuild/pull/86
    pmb.chroot.user(args, ["abuild", "fetch", "verify"],
                    working_dir="/home/pmos/build")
