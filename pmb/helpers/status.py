# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import logging

import pmb.config
import pmb.config.workdir
import pmb.helpers.git


def print_config(args):
    """ Print an overview of what was set in "pmbootstrap init". """
    logging.info("*** CONFIG ***")
    info = args.deviceinfo
    logging.info("Device: {} ({}, \"{}\")"
                 .format(args.device, info["arch"], info["name"]))

    if pmb.parse._apkbuild.kernels(args, args.device):
        logging.info("Kernel: " + args.kernel)

    if args.extra_packages != "none":
        logging.info("Extra packages: {}".format(args.extra_packages))

    logging.info("User Interface: {}".format(args.ui))


def print_git_repos(args):
    logging.info("*** GIT REPOS ***")
    logging.info("Path: {}/cache_git".format(args.work))
    for repo in pmb.config.git_repos.keys():
        path = pmb.helpers.git.get_path(args, repo)
        if not os.path.exists(path):
            continue

        # Get branch name (if on branch) or current commit
        ref = pmb.helpers.git.rev_parse(args, path,
                                        extra_args=["--abbrev-ref"])
        if ref == "HEAD":
            ref = pmb.helpers.git.rev_parse(args, path)[0:8]

        logging.info("- {} ({})".format(repo, ref))


def print_checks_git_repo(args, repo, details=True):
    """ Perform various checks on one checked out git repo.
        :param details: if True, print each passing check (this is True by
                       default for the testsuite)
        :returns: status, todo_msg
                  - status: integer, 0 if all passed, < 0 on failure
                  - msg_todo: message to help the user resolve the failure """
    def log_ok(msg_ok):
        if details:
            logging.info("[OK ] {}: {}".format(repo, msg_ok))

    def log_nok_ret(status, msg_nok, msg_todo):
        logging.warning("[NOK] {}: {}".format(repo, msg_nok))
        return (status, msg_todo)

    # On official branch
    path = pmb.helpers.git.get_path(args, repo)
    branches = pmb.helpers.git.get_branches_official(args, repo)
    ref = pmb.helpers.git.rev_parse(args, path, extra_args=["--abbrev-ref"])
    if ref not in branches:
        return log_nok_ret(-1, "not on official channel branch",
                           "consider checking out: " + ", ".join(branches))
    log_ok("on official channel branch")

    # Workdir clean
    if not pmb.helpers.git.clean_worktree(args, path):
        return log_nok_ret(-2, "workdir is not clean",
                           "consider cleaning your workdir")
    log_ok("workdir is clean")

    # Tracking proper remote
    remote_upstream = pmb.helpers.git.get_upstream_remote(args, repo)
    branch_upstream = remote_upstream + "/" + ref
    remote_ref = pmb.helpers.git.rev_parse(args, path, ref + "@{u}",
                                           ["--abbrev-ref"])
    if remote_ref != branch_upstream:
        return log_nok_ret(-3, "tracking unexpected remote branch",
                           "consider tracking remote branch '{}' instead of"
                           " '{}'".format(branch_upstream, remote_ref))
    log_ok("tracking proper remote branch '{}'".format(branch_upstream))

    # Up to date
    ref_branch = pmb.helpers.git.rev_parse(args, path, ref)
    ref_branch_upstream = pmb.helpers.git.rev_parse(args, path,
                                                    branch_upstream)
    if ref_branch != ref_branch_upstream:
        return log_nok_ret(-4, "not up to date with remote branch",
                           "update with 'pmbootstrap pull'")
    log_ok("up to date with remote branch")

    # Outdated remote information
    if pmb.helpers.git.is_outdated(path):
        return log_nok_ret(-5, "outdated remote information",
                           "update with 'pmbootstrap pull'")
    log_ok("remote information updated recently (via git fetch/pull)")

    return (0, "")


def print_checks_git_repos(args, details):
    """ Perform various checks on the checked out git repos.
        :param details: if True, print each passing check
        :returns: list of unresolved checklist items """
    ret = []
    for repo in pmb.config.git_repos.keys():
        path = pmb.helpers.git.get_path(args, repo)
        if not os.path.exists(path):
            continue
        status, todo_msg = print_checks_git_repo(args, repo, details)
        if status:
            ret += ["{}: {}".format(repo, todo_msg)]
    return ret


def print_checks_chroots_outdated(args, details):
    """ Check if chroots were zapped recently.
        :param details: if True, print each passing check instead of a summary
        :returns: list of unresolved checklist items """
    if pmb.config.workdir.chroots_outdated(args):
        logging.info("[NOK] Chroots not zapped recently")
        return ["Run 'pmbootstrap zap' to delete possibly outdated chroots"]
    elif details:
        logging.info("[OK ] Chroots zapped recently (or non-existing)")
    return []


def print_checks(args, details):
    """ :param details: if True, print each passing check instead of a summary
        :returns: True if all checks passed, False otherwise """
    logging.info("*** CHECKS ***")
    checklist = []
    checklist += print_checks_chroots_outdated(args, details)
    checklist += print_checks_git_repos(args, details)

    # All OK
    if not checklist:
        if not details:
            logging.info("All checks passed! \\o/")
        logging.info("")
        return True

    # Some NOK: print checklist
    logging.info("")
    logging.info("*** CHECKLIST ***")
    for item in checklist:
        logging.info("- " + item)
    logging.info("- Run 'pmbootstrap status' to verify that all is resolved")
    return False


def print_status(args, details=False):
    """ :param details: if True, print each passing check instead of a summary
        :returns: True if all checks passed, False otherwise """
    print_config(args)
    logging.info("")
    print_git_repos(args)
    logging.info("")
    ret = print_checks(args, details)

    return ret
