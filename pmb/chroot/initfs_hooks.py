# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import glob
import logging

import pmb.config
import pmb.chroot.apk


def list_chroot(args, suffix, remove_prefix=True):
    ret = []
    prefix = pmb.config.initfs_hook_prefix
    for pkgname in pmb.chroot.apk.installed(args, suffix).keys():
        if pkgname.startswith(prefix):
            if remove_prefix:
                ret.append(pkgname[len(prefix):])
            else:
                ret.append(pkgname)
    return ret


def list_aports(args):
    ret = []
    prefix = pmb.config.initfs_hook_prefix
    for path in glob.glob(f"{args.aports}/*/{prefix}*"):
        ret.append(os.path.basename(path)[len(prefix):])
    return ret


def ls(args, suffix):
    hooks_chroot = list_chroot(args, suffix)
    hooks_aports = list_aports(args)

    for hook in hooks_aports:
        line = f"* {hook} ({'' if hook in hooks_chroot else 'not '}installed)"
        logging.info(line)


def add(args, hook, suffix):
    if hook not in list_aports(args):
        raise RuntimeError("Invalid hook name!"
                           " Run 'pmbootstrap initfs hook_ls'"
                           " to get a list of all hooks.")
    prefix = pmb.config.initfs_hook_prefix
    pmb.chroot.apk.install(args, [f"{prefix}{hook}"], suffix)


def delete(args, hook, suffix):
    if hook not in list_chroot(args, suffix):
        raise RuntimeError("There is no such hook installed!")
    prefix = pmb.config.initfs_hook_prefix
    pmb.chroot.root(args, ["apk", "del", f"{prefix}{hook}"], suffix)


def update(args, suffix):
    """
    Rebuild and update all hooks that are out of date
    """
    pmb.chroot.apk.install(args, list_chroot(args, suffix, False), suffix)
