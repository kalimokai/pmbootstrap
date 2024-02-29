# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import pmb.helpers.run_core


def user(args, cmd, working_dir=None, output="log", output_return=False,
         check=None, env={}, sudo=False):
    """
    Run a command on the host system as user.

    :param env: dict of environment variables to be passed to the command, e.g.
                {"JOBS": "5"}

    See pmb.helpers.run_core.core() for a detailed description of all other
    arguments and the return value.
    """
    # Readable log message (without all the escaping)
    msg = "% "
    for key, value in env.items():
        msg += key + "=" + value + " "
    if working_dir:
        msg += "cd " + working_dir + "; "
    msg += " ".join(cmd)

    # Add environment variables and run
    env = env.copy()
    pmb.helpers.run_core.add_proxy_env_vars(env)
    if env:
        cmd = ["sh", "-c", pmb.helpers.run_core.flat_cmd(cmd, env=env)]
    return pmb.helpers.run_core.core(args, msg, cmd, working_dir, output,
                                     output_return, check, sudo)


def root(args, cmd, working_dir=None, output="log", output_return=False,
         check=None, env={}):
    """
    Run a command on the host system as root, with sudo or doas.

    :param env: dict of environment variables to be passed to the command, e.g.
                {"JOBS": "5"}

    See pmb.helpers.run_core.core() for a detailed description of all other
    arguments and the return value.
    """
    env = env.copy()
    pmb.helpers.run_core.add_proxy_env_vars(env)

    if env:
        cmd = ["sh", "-c", pmb.helpers.run_core.flat_cmd(cmd, env=env)]
    cmd = pmb.config.sudo(cmd)

    return user(args, cmd, working_dir, output, output_return, check, env,
                True)
