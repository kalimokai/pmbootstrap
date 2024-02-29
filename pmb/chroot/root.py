# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import shutil

import pmb.config
import pmb.chroot
import pmb.chroot.binfmt
import pmb.helpers.run
import pmb.helpers.run_core


def executables_absolute_path():
    """
    Get the absolute paths to the sh and chroot executables.
    """
    ret = {}
    for binary in ["sh", "chroot"]:
        path = shutil.which(binary, path=pmb.config.chroot_host_path)
        if not path:
            raise RuntimeError(f"Could not find the '{binary}'"
                               " executable. Make sure that it is in"
                               " your current user's PATH.")
        ret[binary] = path
    return ret


def root(args, cmd, suffix="native", working_dir="/", output="log",
         output_return=False, check=None, env={}, auto_init=True,
         disable_timeout=False, add_proxy_env_vars=True):
    """
    Run a command inside a chroot as root.

    :param env: dict of environment variables to be passed to the command, e.g.
                {"JOBS": "5"}
    :param auto_init: automatically initialize the chroot
    :param add_proxy_env_vars: if True, preserve HTTP_PROXY etc. vars from host
                               environment. pmb.chroot.user sets this to False
                               when calling pmb.chroot.root, because it already
                               makes the variables part of the cmd argument.

    See pmb.helpers.run_core.core() for a detailed description of all other
    arguments and the return value.
    """
    # Initialize chroot
    chroot = f"{args.work}/chroot_{suffix}"
    if not auto_init and not os.path.islink(f"{chroot}/bin/sh"):
        raise RuntimeError(f"Chroot does not exist: {chroot}")
    if auto_init:
        pmb.chroot.init(args, suffix)

    # Readable log message (without all the escaping)
    msg = f"({suffix}) % "
    for key, value in env.items():
        msg += f"{key}={value} "
    if working_dir != "/":
        msg += f"cd {working_dir}; "
    msg += " ".join(cmd)

    # Merge env with defaults into env_all
    env_all = {"CHARSET": "UTF-8",
               "HISTFILE": "~/.ash_history",
               "HOME": "/root",
               "LANG": "UTF-8",
               "PATH": pmb.config.chroot_path,
               "PYTHONUNBUFFERED": "1",
               "SHELL": "/bin/ash",
               "TERM": "xterm"}
    for key, value in env.items():
        env_all[key] = value
    if add_proxy_env_vars:
        pmb.helpers.run_core.add_proxy_env_vars(env_all)

    # Build the command in steps and run it, e.g.:
    # cmd: ["echo", "test"]
    # cmd_chroot: ["/sbin/chroot", "/..._native", "/bin/sh", "-c", "echo test"]
    # cmd_sudo: ["sudo", "env", "-i", "sh", "-c", "PATH=... /sbin/chroot ..."]
    executables = executables_absolute_path()
    cmd_chroot = [executables["chroot"], chroot, "/bin/sh", "-c",
                  pmb.helpers.run_core.flat_cmd(cmd, working_dir)]
    cmd_sudo = pmb.config.sudo([
        "env", "-i", executables["sh"], "-c",
        pmb.helpers.run_core.flat_cmd(cmd_chroot, env=env_all)]
    )
    return pmb.helpers.run_core.core(args, msg, cmd_sudo, None, output,
                                     output_return, check, True,
                                     disable_timeout)
