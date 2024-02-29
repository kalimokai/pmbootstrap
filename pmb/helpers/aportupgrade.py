# Copyright 2023 Luca Weiss
# SPDX-License-Identifier: GPL-3.0-or-later
import datetime
import fnmatch
import logging
import os
import re
import urllib.parse
from typing import Optional

import pmb.helpers.file
import pmb.helpers.http
import pmb.helpers.pmaports

req_headers = None
req_headers_github = None

ANITYA_API_BASE = "https://release-monitoring.org/api/v2"
GITHUB_API_BASE = "https://api.github.com"
GITLAB_HOSTS = [
    "https://gitlab.com",
    "https://gitlab.freedesktop.org",
    "https://gitlab.gnome.org",
    "https://invent.kde.org",
    "https://source.puri.sm",
]


def init_req_headers() -> None:
    global req_headers
    global req_headers_github
    # Only initialize them once
    if req_headers is not None and req_headers_github is not None:
        return
    # Generic request headers
    req_headers = {
        'User-Agent': f'pmbootstrap/{pmb.__version__} aportupgrade'}

    # Request headers specific to GitHub
    req_headers_github = dict(req_headers)
    if os.getenv("GITHUB_TOKEN") is not None:
        token = os.getenv("GITHUB_TOKEN")
        req_headers_github['Authorization'] = f'token {token}'
    else:
        logging.info("NOTE: Consider using a GITHUB_TOKEN environment variable"
                     " to increase your rate limit")


def get_package_version_info_github(repo_name: str, ref: Optional[str]):
    logging.debug("Trying GitHub repository: {}".format(repo_name))

    # Get the URL argument to request a special ref, if needed
    ref_arg = ""
    if ref is not None:
        ref_arg = f"?sha={ref}"

    # Get the commits for the repository
    commits = pmb.helpers.http.retrieve_json(
        f"{GITHUB_API_BASE}/repos/{repo_name}/commits{ref_arg}",
        headers=req_headers_github)
    latest_commit = commits[0]
    commit_date = latest_commit["commit"]["committer"]["date"]
    # Extract the time from the field
    date = datetime.datetime.strptime(commit_date, "%Y-%m-%dT%H:%M:%SZ")
    return {
        "sha": latest_commit["sha"],
        "date": date,
    }


def get_package_version_info_gitlab(gitlab_host: str, repo_name: str,
                                    ref: Optional[str]):
    logging.debug("Trying GitLab repository: {}".format(repo_name))

    repo_name_safe = urllib.parse.quote(repo_name, safe='')

    # Get the URL argument to request a special ref, if needed
    ref_arg = ""
    if ref is not None:
        ref_arg = f"?ref_name={ref}"

    # Get the commits for the repository
    commits = pmb.helpers.http.retrieve_json(
        f"{gitlab_host}/api/v4/projects/{repo_name_safe}/repository"
        f"/commits{ref_arg}",
        headers=req_headers)
    latest_commit = commits[0]
    commit_date = latest_commit["committed_date"]
    # Extract the time from the field
    # 2019-10-14T09:32:00.000Z / 2019-12-27T07:58:53.000-05:00
    date = datetime.datetime.strptime(commit_date, "%Y-%m-%dT%H:%M:%S.000%z")
    return {
        "sha": latest_commit["id"],
        "date": date,
    }


def upgrade_git_package(args, pkgname: str, package) -> None:
    """
    Update _commit/pkgver/pkgrel in a git-APKBUILD (or pretend to do it if
    args.dry is set).
    :param pkgname: the package name
    :param package: a dict containing package information
    """
    # Get the wanted source line
    source = package["source"][0]
    source = re.split(r"::", source)
    if 1 <= len(source) <= 2:
        source = source[-1]
    else:
        raise RuntimeError("Unhandled number of source elements. Please open"
                           f" a bug report: {source}")

    verinfo = None

    github_match = re.match(
        r"https://github\.com/(.+)/(?:archive|releases)", source)
    gitlab_match = re.match(
        fr"({'|'.join(GITLAB_HOSTS)})/(.+)/-/archive/", source)
    if github_match:
        verinfo = get_package_version_info_github(
            github_match.group(1), args.ref)
    elif gitlab_match:
        verinfo = get_package_version_info_gitlab(
            gitlab_match.group(1), gitlab_match.group(2), args.ref)

    if verinfo is None:
        # ignore for now
        logging.warning("{}: source not handled: {}".format(pkgname, source))
        return

    # Get the new commit sha
    sha = package["_commit"]
    sha_new = verinfo["sha"]

    # Format the new pkgver, keep the value before _git the same
    if package["pkgver"] == "9999":
        pkgver = package["_pkgver"]
    else:
        pkgver = package["pkgver"]

    pkgver_match = re.match(r"([\d.]+)_git", pkgver)
    if pkgver_match is None:
        msg = "pkgver did not match the expected pattern!"
        raise RuntimeError(msg)

    date_pkgver = verinfo["date"].strftime("%Y%m%d")
    pkgver_new = f"{pkgver_match.group(1)}_git{date_pkgver}"

    # pkgrel will be zero
    pkgrel = int(package["pkgrel"])
    pkgrel_new = 0

    if sha == sha_new:
        logging.info("{}: up-to-date".format(pkgname))
        return

    logging.info("{}: upgrading pmaport".format(pkgname))
    if args.dry:
        logging.info(f"  Would change _commit from {sha} to {sha_new}")
        logging.info(f"  Would change pkgver from {pkgver} to {pkgver_new}")
        logging.info(f"  Would change pkgrel from {pkgrel} to {pkgrel_new}")
        return

    if package["pkgver"] == "9999":
        pmb.helpers.file.replace_apkbuild(args, pkgname, "_pkgver", pkgver_new)
    else:
        pmb.helpers.file.replace_apkbuild(args, pkgname, "pkgver", pkgver_new)
    pmb.helpers.file.replace_apkbuild(args, pkgname, "pkgrel", pkgrel_new)
    pmb.helpers.file.replace_apkbuild(args, pkgname, "_commit", sha_new, True)
    return


def upgrade_stable_package(args, pkgname: str, package) -> None:
    """
    Update _commit/pkgver/pkgrel in an APKBUILD (or pretend to do it if
    args.dry is set).

    :param pkgname: the package name
    :param package: a dict containing package information
    """

    # Looking up if there's a custom mapping from postmarketOS package name
    # to Anitya project name.
    mappings = pmb.helpers.http.retrieve_json(
        f"{ANITYA_API_BASE}/packages/?distribution=postmarketOS"
        f"&name={pkgname}", headers=req_headers)
    if mappings["total_items"] < 1:
        projects = pmb.helpers.http.retrieve_json(
            f"{ANITYA_API_BASE}/projects/?name={pkgname}", headers=req_headers)
        if projects["total_items"] < 1:
            logging.warning(f"{pkgname}: failed to get Anitya project")
            return
    else:
        project_name = mappings["items"][0]["project"]
        ecosystem = mappings["items"][0]["ecosystem"]
        projects = pmb.helpers.http.retrieve_json(
            f"{ANITYA_API_BASE}/projects/?name={project_name}&"
            f"ecosystem={ecosystem}",
            headers=req_headers)

    if projects["total_items"] < 1:
        logging.warning(f"{pkgname}: didn't find any projects, can't upgrade!")
        return
    if projects["total_items"] > 1:
        logging.warning(f"{pkgname}: found more than one project, can't "
                        f"upgrade! Please create an explicit mapping of "
                        f"\"project\" to the package name.")
        return

    # Get the first, best-matching item
    project = projects["items"][0]

    # Check that we got a version number
    if len(project["stable_versions"]) < 1:
        logging.warning("{}: got no version number, ignoring".format(pkgname))
        return

    version = project["stable_versions"][0]

    # Compare the pmaports version with the project version
    if package["pkgver"] == version:
        logging.info("{}: up-to-date".format(pkgname))
        return

    if package["pkgver"] == "9999":
        pkgver = package["_pkgver"]
    else:
        pkgver = package["pkgver"]

    pkgver_new = version

    pkgrel = package["pkgrel"]
    pkgrel_new = 0

    if not pmb.parse.version.validate(pkgver_new):
        logging.warning(f"{pkgname}: would upgrade to invalid pkgver:"
                        f" {pkgver_new}, ignoring")
        return

    logging.info("{}: upgrading pmaport".format(pkgname))
    if args.dry:
        logging.info(f"  Would change pkgver from {pkgver} to {pkgver_new}")
        logging.info(f"  Would change pkgrel from {pkgrel} to {pkgrel_new}")
        return

    if package["pkgver"] == "9999":
        pmb.helpers.file.replace_apkbuild(args, pkgname, "_pkgver", pkgver_new)
    else:
        pmb.helpers.file.replace_apkbuild(args, pkgname, "pkgver", pkgver_new)

    pmb.helpers.file.replace_apkbuild(args, pkgname, "pkgrel", pkgrel_new)
    return


def upgrade(args, pkgname, git=True, stable=True) -> None:
    """
    Find new versions of a single package and upgrade it.

    :param pkgname: the name of the package
    :param git: True if git packages should be upgraded
    :param stable: True if stable packages should be upgraded
    """
    # Initialize request headers
    init_req_headers()

    package = pmb.helpers.pmaports.get(args, pkgname)
    # Run the correct function
    if "_git" in package["pkgver"]:
        if git:
            upgrade_git_package(args, pkgname, package)
    else:
        if stable:
            upgrade_stable_package(args, pkgname, package)


def upgrade_all(args) -> None:
    """
    Upgrade all packages, based on args.all, args.all_git and args.all_stable.
    """
    for pkgname in pmb.helpers.pmaports.get_list(args):
        # Always ignore postmarketOS-specific packages that have no upstream
        # source
        skip = False
        for pattern in pmb.config.upgrade_ignore:
            if fnmatch.fnmatch(pkgname, pattern):
                skip = True
        if skip:
            continue

        upgrade(args, pkgname, args.all or args.all_git,
                args.all or args.all_stable)
