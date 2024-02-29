# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import os
import glob
import filecmp

import pmb.chroot
import pmb.chroot.apk_static
import pmb.config
import pmb.config.workdir
import pmb.helpers.repo
import pmb.helpers.run
import pmb.parse.arch


def copy_resolv_conf(args, suffix="native"):
    """
    Use pythons super fast file compare function (due to caching)
    and copy the /etc/resolv.conf to the chroot, in case it is
    different from the host.
    If the file doesn't exist, create an empty file with 'touch'.
    """
    host = "/etc/resolv.conf"
    chroot = f"{args.work}/chroot_{suffix}{host}"
    if os.path.exists(host):
        if not os.path.exists(chroot) or not filecmp.cmp(host, chroot):
            pmb.helpers.run.root(args, ["cp", host, chroot])
    else:
        pmb.helpers.run.root(args, ["touch", chroot])


def mark_in_chroot(args, suffix="native"):
    """
    Touch a flag so we can know when we're running in chroot (and
    don't accidentally flash partitions on our host). This marker
    gets removed in pmb.chroot.shutdown (pmbootstrap shutdown).
    """
    in_chroot_file = f"{args.work}/chroot_{suffix}/in-pmbootstrap"
    if not os.path.exists(in_chroot_file):
        pmb.helpers.run.root(args, ["touch", in_chroot_file])


def setup_qemu_emulation(args, suffix):
    arch = pmb.parse.arch.from_chroot_suffix(args, suffix)
    if not pmb.parse.arch.cpu_emulation_required(arch):
        return

    chroot = f"{args.work}/chroot_{suffix}"
    arch_qemu = pmb.parse.arch.alpine_to_qemu(arch)

    # mount --bind the qemu-user binary
    pmb.chroot.binfmt.register(args, arch)
    pmb.helpers.mount.bind_file(args, f"{args.work}/chroot_native"
                                      f"/usr/bin/qemu-{arch_qemu}",
                                f"{chroot}/usr/bin/qemu-{arch_qemu}-static",
                                create_folders=True)


def init_keys(args):
    """
    All Alpine and postmarketOS repository keys are shipped with pmbootstrap.
    Copy them into $WORK/config_apk_keys, which gets mounted inside the various
    chroots as /etc/apk/keys.

    This is done before installing any package, so apk can verify APKINDEX
    files of binary repositories even though alpine-keys/postmarketos-keys are
    not installed yet.
    """
    for key in glob.glob(f"{pmb.config.apk_keys_path}/*.pub"):
        target = f"{args.work}/config_apk_keys/{os.path.basename(key)}"
        if not os.path.exists(target):
            # Copy as root, so the resulting files in chroots are owned by root
            pmb.helpers.run.root(args, ["cp", key, target])


def init(args, suffix="native"):
    # When already initialized: just prepare the chroot
    chroot = f"{args.work}/chroot_{suffix}"
    arch = pmb.parse.arch.from_chroot_suffix(args, suffix)

    pmb.chroot.mount(args, suffix)
    setup_qemu_emulation(args, suffix)
    mark_in_chroot(args, suffix)
    if os.path.islink(f"{chroot}/bin/sh"):
        pmb.config.workdir.chroot_check_channel(args, suffix)
        copy_resolv_conf(args, suffix)
        pmb.chroot.apk.update_repository_list(args, suffix)
        return

    # Require apk-tools-static
    pmb.chroot.apk_static.init(args)

    logging.info(f"({suffix}) install alpine-base")

    # Initialize cache
    apk_cache = f"{args.work}/cache_apk_{arch}"
    pmb.helpers.run.root(args, ["ln", "-s", "-f", "/var/cache/apk",
                                f"{chroot}/etc/apk/cache"])

    # Initialize /etc/apk/keys/, resolv.conf, repositories
    init_keys(args)
    copy_resolv_conf(args, suffix)
    pmb.chroot.apk.update_repository_list(args, suffix)

    pmb.config.workdir.chroot_save_init(args, suffix)

    # Install alpine-base
    pmb.helpers.repo.update(args, arch)
    pmb.chroot.apk_static.run(args, ["--root", chroot,
                                     "--cache-dir", apk_cache,
                                     "--initdb", "--arch", arch,
                                     "add", "alpine-base"])

    # Building chroots: create "pmos" user, add symlinks to /home/pmos
    if not suffix.startswith("rootfs_"):
        pmb.chroot.root(args, ["adduser", "-D", "pmos", "-u",
                               pmb.config.chroot_uid_user],
                        suffix, auto_init=False)

        # Create the links (with subfolders if necessary)
        for target, link_name in pmb.config.chroot_home_symlinks.items():
            link_dir = os.path.dirname(link_name)
            if not os.path.exists(f"{chroot}{link_dir}"):
                pmb.chroot.user(args, ["mkdir", "-p", link_dir], suffix)
            if not os.path.exists(f"{chroot}{target}"):
                pmb.chroot.root(args, ["mkdir", "-p", target], suffix)
            pmb.chroot.user(args, ["ln", "-s", target, link_name], suffix)
            pmb.chroot.root(args, ["chown", "pmos:pmos", target], suffix)
