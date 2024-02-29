# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
"""
This file runs various installations and boots into them with QEMU, then checks
via SSH if expected processes are running.

We use an extra config file (based on ~/.config/pmbootstrap.cfg), because we
need to change it a lot (e.g. UI, username, ...).
"""
import pytest
import sys
import shutil
import shlex
import time

import pmb_test  # noqa
import pmb.chroot.apk_static
import pmb.parse.apkindex
import pmb.helpers.logging
import pmb.helpers.run
import pmb.parse.bootimg


@pytest.fixture
def args(request):
    import pmb.parse
    sys.argv = ["pmbootstrap.py", "chroot"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)
    return args


def ssh_create_askpass_script(args):
    """Create /tmp/y.sh, which we need to automatically login via SSH."""
    with open(args.work + "/chroot_native/tmp/y.sh", "w") as handle:
        handle.write("#!/bin/sh\necho y\n")
    pmb.chroot.root(args, ["chmod", "+x", "/tmp/y.sh"])


def pmbootstrap_run(args, config, parameters, output="log"):
    """Execute pmbootstrap.py with a test pmbootstrap.conf."""
    return pmb.helpers.run.user(args, ["./pmbootstrap.py", "-c", config] +
                                parameters, working_dir=pmb.config.pmb_src,
                                output=output)


def pmbootstrap_yes(args, config, parameters):
    """
    Execute pmbootstrap.py with a test pmbootstrap.conf, and pipe "yes" into it
    (so we can do a fully automated installation, using "y" as password
    everywhere). Use --details-to-stdout to avoid the pmbootstrap process from
    looking like it is hanging, when downloading packages with apk (otherwise
    it would write no output, and get killed by the timeout).
    """
    command = ("yes | ./pmbootstrap.py --details-to-stdout -c " +
               shlex.quote(config))
    for parameter in parameters:
        command += " " + shlex.quote(parameter)
    return pmb.helpers.run.user(args, ["/bin/sh", "-c", command],
                                working_dir=pmb.config.pmb_src)


class QEMU(object):
    def __init__(self, request):
        self.process = None
        request.addfinalizer(self.terminate)

    def terminate(self):
        if self.process:
            self.process.terminate()
        else:
            print("WARNING: The QEMU process wasn't set, so it could not be"
                  " terminated.")

    def run(self, args, tmpdir, ui="none"):
        # Copy and adjust user's pmbootstrap.cfg
        config = str(tmpdir) + "/pmbootstrap.cfg"
        shutil.copyfile(args.config, config)
        pmbootstrap_run(args, config, ["config", "device", "qemu-amd64"])
        pmbootstrap_run(args, config, ["config", "kernel", "virt"])
        pmbootstrap_run(args, config, ["config", "extra_packages", "none"])
        pmbootstrap_run(args, config, ["config", "user", "testuser"])
        pmbootstrap_run(args, config, ["config", "ui", ui])

        # Prepare native chroot
        pmbootstrap_run(args, config, ["-y", "zap"])
        pmb.chroot.apk.install(args, ["openssh-client"])
        ssh_create_askpass_script(args)

        # Create and run rootfs
        pmbootstrap_yes(args, config, ["install"])
        self.process = pmbootstrap_run(args, config, ["qemu", "--display",
                                                      "none"], "background")


@pytest.fixture
def qemu(request):
    return QEMU(request)


def ssh_run(args, command):
    """
    Run a command in the QEMU VM on localhost via SSH.

    :param command: flat string of the command to execute, e.g. "ps au"
    :returns: the result from the SSH server
    """
    ret = pmb.chroot.user(args, ["SSH_ASKPASS=/tmp/y.sh", "DISPLAY=", "ssh",
                                 "-o", "ConnectTimeout=10",
                                 "-o", "UserKnownHostsFile=/dev/null",
                                 "-o", "StrictHostKeyChecking=no",
                                 "-p", "2222", "testuser@localhost", "--",
                                 command], output_return=True, check=False)
    return ret


def is_running(args, programs, timeout=300, sleep_before_retry=1):
    """
    Simple check that looks for program names in the output of "ps ax".
    This is error-prone, only use it with programs that have a unique name.
    With defaults timeout and sleep_before_retry values, it will try keep
    trying for 5 minutes, but not more than once per second.

    :param programs: list of programs to check for, e.g. ["xfce4-desktop"]
    :param timeout: approximate time in seconds until timeout
    :param sleep_before_retry: time in seconds to sleep before trying again
    """
    print(f"Looking for programs to appear in the VM (timeout: {timeout}): " +
          ", ".join(programs))
    ssh_works = False

    end = time.monotonic() + timeout
    last_try = 0

    while last_try < end:
        # Sleep only when last try exited immediately
        sleep = last_try - time.monotonic() + sleep_before_retry
        if sleep > 0:
            time.sleep(sleep)
        last_try = time.monotonic()

        # Get running programs via SSH
        all = ssh_run(args, "ps ax")
        if not all:
            continue
        ssh_works = True

        # Missing programs
        missing = []
        for program in programs:
            if program not in all:
                missing.append(program)
        if not missing:
            return True

    # Not found
    print("ERROR: Timeout reached!")
    if ssh_works:
        print("Programs not running: " + ", ".join(missing))
    else:
        print("Could not connect to the VM via SSH")
    return False


@pytest.mark.skip_ci
def test_none(args, tmpdir, qemu):
    qemu.run(args, tmpdir)

    # Check that at least SSH works (no special process running)
    assert is_running(args, [])

    # self-test of is_running() - invalid-process should not be detected as
    # running
    assert is_running(args, ["invalid-process"], 1) is False


@pytest.mark.skip_ci
def test_xfce4(args, tmpdir, qemu):
    qemu.run(args, tmpdir, "xfce4")
    assert is_running(args, ["xfce4-session", "xfdesktop", "xfce4-panel",
                             "Thunar", "dbus-daemon", "xfwm4"])


@pytest.mark.skip_ci
def test_plasma_mobile(args, tmpdir, qemu):
    # NOTE: Once we have plasma mobile running properly without GL, we can
    # check for more processes
    qemu.run(args, tmpdir, "plasma-mobile")
    assert is_running(args, ["polkitd"])
