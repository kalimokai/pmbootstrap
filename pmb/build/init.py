# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import glob
import logging
import os
import pathlib

import pmb.build
import pmb.config
import pmb.chroot
import pmb.chroot.apk
import pmb.helpers.run
import pmb.parse.arch


def init_abuild_minimal(args, suffix="native"):
    """ Initialize a minimal chroot with abuild where one can do
        'abuild checksum'. """
    marker = f"{args.work}/chroot_{suffix}/tmp/pmb_chroot_abuild_init_done"
    if os.path.exists(marker):
        return

    pmb.chroot.apk.install(args, ["abuild"], suffix, build=False)

    # Fix permissions
    pmb.chroot.root(args, ["chown", "root:abuild",
                           "/var/cache/distfiles"], suffix)
    pmb.chroot.root(args, ["chmod", "g+w",
                           "/var/cache/distfiles"], suffix)

    # Add user to group abuild
    pmb.chroot.root(args, ["adduser", "pmos", "abuild"], suffix)

    pathlib.Path(marker).touch()


def init(args, suffix="native"):
    """ Initialize a chroot for building packages with abuild. """
    marker = f"{args.work}/chroot_{suffix}/tmp/pmb_chroot_build_init_done"
    if os.path.exists(marker):
        return

    init_abuild_minimal(args, suffix)

    # Initialize chroot, install packages
    pmb.chroot.apk.install(args, pmb.config.build_packages, suffix,
                           build=False)

    # Generate package signing keys
    chroot = args.work + "/chroot_" + suffix
    if not os.path.exists(args.work + "/config_abuild/abuild.conf"):
        logging.info("(" + suffix + ") generate abuild keys")
        pmb.chroot.user(args, ["abuild-keygen", "-n", "-q", "-a"],
                        suffix, env={"PACKAGER": "pmos <pmos@local>"})

        # Copy package signing key to /etc/apk/keys
        for key in glob.glob(chroot +
                             "/mnt/pmbootstrap/abuild-config/*.pub"):
            key = key[len(chroot):]
            pmb.chroot.root(args, ["cp", key, "/etc/apk/keys/"], suffix)

    apk_arch = pmb.parse.arch.from_chroot_suffix(args, suffix)

    # Add apk wrapper that runs native apk and lies about arch
    if pmb.parse.arch.cpu_emulation_required(apk_arch) and \
            not os.path.exists(chroot + "/usr/local/bin/abuild-apk"):
        with open(chroot + "/tmp/apk_wrapper.sh", "w") as handle:
            content = f"""
                #!/bin/sh
                export LD_PRELOAD_PATH=/native/usr/lib:/native/lib
                args=""
                for arg in "$@"; do
                    if [ "$arg" == "--print-arch" ]; then
                        echo "{apk_arch}"
                        exit 0
                    fi
                    args="$args $arg"
                done
                /native/usr/bin/abuild-apk $args
            """
            lines = content.split("\n")[1:]
            for i in range(len(lines)):
                lines[i] = lines[i][16:]
            handle.write("\n".join(lines))
        pmb.chroot.root(args, ["cp", "/tmp/apk_wrapper.sh",
                               "/usr/local/bin/abuild-apk"], suffix)
        pmb.chroot.root(args, ["chmod", "+x", "/usr/local/bin/abuild-apk"], suffix)

    # abuild.conf: Don't clean the build folder after building, so we can
    # inspect it afterwards for debugging
    pmb.chroot.root(args, ["sed", "-i", "-e", "s/^CLEANUP=.*/CLEANUP=''/",
                           "/etc/abuild.conf"], suffix)

    # abuild.conf: Don't clean up installed packages in strict mode, so
    # abuild exits directly when pressing ^C in pmbootstrap.
    pmb.chroot.root(args, ["sed", "-i", "-e",
                           "s/^ERROR_CLEANUP=.*/ERROR_CLEANUP=''/",
                           "/etc/abuild.conf"], suffix)

    pathlib.Path(marker).touch()


def init_compiler(args, depends, cross, arch):
    cross_pkgs = ["ccache-cross-symlinks", "abuild"]
    if "gcc4" in depends:
        cross_pkgs += ["gcc4-" + arch]
    elif "gcc6" in depends:
        cross_pkgs += ["gcc6-" + arch]
    else:
        cross_pkgs += ["gcc-" + arch, "g++-" + arch]
    if "clang" in depends or "clang-dev" in depends:
        cross_pkgs += ["clang"]
    if cross == "crossdirect":
        cross_pkgs += ["crossdirect"]
        if "rust" in depends or "cargo" in depends:
            if args.ccache:
                cross_pkgs += ["sccache"]
            # crossdirect for rust installs all build dependencies in the
            # native chroot too, as some of them can be required for building
            # native macros / build scripts
            cross_pkgs += depends

    pmb.chroot.apk.install(args, cross_pkgs)
