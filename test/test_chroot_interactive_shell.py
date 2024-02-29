# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import subprocess
import os
import pmb_test  # noqa
import pmb.config


def test_chroot_interactive_shell():
    """
    Open a shell with 'pmbootstrap chroot' and pass 'echo hello_world\n' as
    stdin.
    """
    os.chdir(pmb.config.pmb_src)
    ret = subprocess.check_output(["./pmbootstrap.py", "-q", "chroot", "sh"],
                                  timeout=300, input="echo hello_world\n",
                                  universal_newlines=True,
                                  stderr=subprocess.STDOUT)
    assert ret == "hello_world\n"


def test_chroot_interactive_shell_user():
    """
    Open a shell with 'pmbootstrap chroot' as user, and test the resulting ID.
    """
    os.chdir(pmb.config.pmb_src)
    ret = subprocess.check_output(["./pmbootstrap.py", "-q", "chroot",
                                   "--user", "sh"], timeout=300,
                                  input="id -un",
                                  universal_newlines=True,
                                  stderr=subprocess.STDOUT)
    assert ret == "pmos\n"


def test_chroot_arguments():
    """
    Open a shell with 'pmbootstrap chroot' for every architecture, pass
    'uname -m\n' as stdin and check the output
    """
    os.chdir(pmb.config.pmb_src)

    for arch in ["armhf", "aarch64", "x86_64"]:
        ret = subprocess.check_output(["./pmbootstrap.py", "-q", "chroot",
                                       "-b", arch, "sh"],
                                      timeout=300,
                                      input="uname -m\n",
                                      universal_newlines=True,
                                      stderr=subprocess.STDOUT)
        if arch == "armhf":
            assert ret == "armv7l\n"
        else:
            assert ret == arch + "\n"
