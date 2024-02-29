# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import collections
import glob
import logging
import os
import shlex
import pmb.chroot
import pmb.helpers.cli


def get_ci_scripts(topdir):
    """ Find 'pmbootstrap ci'-compatible scripts inside a git repository, and
        parse their metadata (description, options). The reference is at:
        https://postmarketos.org/pmb-ci
        :param topdir: top directory of the git repository, get it with:
                       pmb.helpers.git.get_topdir()
        :returns: a dict of CI scripts found in the git repository, e.g.
                  {"ruff": {"description": "lint all python scripts",
                              "options": []},
                   ...} """
    ret = {}
    for script in glob.glob(f"{topdir}/.ci/*.sh"):
        is_pmb_ci_script = False
        description = ""
        options = []

        with open(script) as handle:
            for line in handle:
                if line.startswith("# https://postmarketos.org/pmb-ci"):
                    is_pmb_ci_script = True
                elif line.startswith("# Description: "):
                    description = line.split(": ", 1)[1].rstrip()
                elif line.startswith("# Options: "):
                    options = line.split(": ", 1)[1].rstrip().split(" ")
                elif not line.startswith("#"):
                    # Stop parsing after the block of comments on top
                    break

        if not is_pmb_ci_script:
            continue

        if not description:
            logging.error(f"ERROR: {script}: missing '# Description: …' line")
            exit(1)

        for option in options:
            if option not in pmb.config.ci_valid_options:
                raise RuntimeError(f"{script}: unsupported option '{option}'."
                                   " Typo in script or pmbootstrap too old?")

        short_name = os.path.basename(script).split(".", -1)[0]
        ret[short_name] = {"description": description,
                           "options": options}
    return ret


def sort_scripts_by_speed(scripts):
    """ Order the scripts, so fast scripts run before slow scripts. Whether a
        script is fast or not is determined by the '# Options: slow' comment in
        the file.
        :param scripts: return of get_ci_scripts()
        :returns: same format as get_ci_scripts(), but as ordered dict with
                  fast scripts before slow scripts """
    ret = collections.OrderedDict()

    # Fast scripts first
    for script_name, script in scripts.items():
        if "slow" in script["options"]:
            continue
        ret[script_name] = script

    # Then slow scripts
    for script_name, script in scripts.items():
        if "slow" not in script["options"]:
            continue
        ret[script_name] = script
    return ret


def ask_which_scripts_to_run(scripts_available):
    """ Display an interactive prompt about which of the scripts the user
        wishes to run, or all of them.
        :param scripts_available: same format as get_ci_scripts()
        :returns: either full scripts_available (all selected), or a subset """
    count = len(scripts_available.items())
    choices = ["all"]

    logging.info(f"Available CI scripts ({count}):")
    for script_name, script in scripts_available.items():
        extra = ""
        if "slow" in script["options"]:
            extra += " (slow)"
        logging.info(f"* {script_name}: {script['description']}{extra}")
        choices += [script_name]

    selection = pmb.helpers.cli.ask("Which script?", None, "all",
                                    complete=choices)
    if selection == "all":
        return scripts_available

    ret = {}
    ret[selection] = scripts_available[selection]
    return ret


def copy_git_repo_to_chroot(args, topdir):
    """ Create a tarball of the git repo (including unstaged changes and new
        files) and extract it in chroot_native.
        :param topdir: top directory of the git repository, get it with:
                       pmb.helpers.git.get_topdir() """
    pmb.chroot.init(args)
    tarball_path = f"{args.work}/chroot_native/tmp/git.tar.gz"
    files = pmb.helpers.git.get_files(args, topdir)

    with open(f"{tarball_path}.files", "w") as handle:
        for file in files:
            handle.write(file)
            handle.write("\n")

    pmb.helpers.run.user(args, ["tar", "-cf", tarball_path, "-T",
                                f"{tarball_path}.files"], topdir)

    ci_dir = "/home/pmos/ci"
    pmb.chroot.user(args, ["rm", "-rf", ci_dir])
    pmb.chroot.user(args, ["mkdir", ci_dir])
    pmb.chroot.user(args, ["tar", "-xf", "/tmp/git.tar.gz"],
                    working_dir=ci_dir)


def run_scripts(args, topdir, scripts):
    """ Run one of the given scripts after another, either natively or in a
        chroot. Display a progress message and stop on error (without printing
        a python stack trace).
        :param topdir: top directory of the git repository, get it with:
                       pmb.helpers.git.get_topdir()
        :param scripts: return of get_ci_scripts() """
    steps = len(scripts)
    step = 0
    repo_copied = False

    for script_name, script in scripts.items():
        step += 1

        where = "pmbootstrap chroot"
        if "native" in script["options"]:
            where = "native"

        script_path = f".ci/{script_name}.sh"
        logging.info(f"*** ({step}/{steps}) RUNNING CI SCRIPT: {script_path}"
                     f" [{where}] ***")

        if "native" in script["options"]:
            rc = pmb.helpers.run.user(args, [script_path], topdir,
                                      output="tui")
            continue
        else:
            # Run inside pmbootstrap chroot
            if not repo_copied:
                copy_git_repo_to_chroot(args, topdir)
                repo_copied = True

            env = {"TESTUSER": "pmos"}
            rc = pmb.chroot.root(args, [script_path], check=False, env=env,
                                 working_dir="/home/pmos/ci",
                                 output="tui")
        if rc:
            logging.error(f"ERROR: CI script failed: {script_name}")
            exit(1)
