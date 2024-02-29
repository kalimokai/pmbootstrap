# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Functions that work with binary package repos. See also:
- pmb/helpers/pmaports.py (work with pmaports)
- pmb/helpers/package.py (work with both)
"""
import os
import hashlib
import logging
import pmb.config.pmaports
import pmb.helpers.http
import pmb.helpers.run


def hash(url, length=8):
    """
    Generate the hash that APK adds to the APKINDEX and apk packages
    in its apk cache folder. It is the "12345678" part in this example:
    "APKINDEX.12345678.tar.gz".

    :param length: The length of the hash in the output file.

    See also: official implementation in apk-tools:
    <https://git.alpinelinux.org/cgit/apk-tools/>

    blob.c: apk_blob_push_hexdump(), "const char *xd"
    apk_defines.h: APK_CACHE_CSUM_BYTES
    database.c: apk_repo_format_cache_index()
    """
    binary = hashlib.sha1(url.encode("utf-8")).digest()
    xd = "0123456789abcdefghijklmnopqrstuvwxyz"
    csum_bytes = int(length / 2)

    ret = ""
    for i in range(csum_bytes):
        ret += xd[(binary[i] >> 4) & 0xf]
        ret += xd[binary[i] & 0xf]

    return ret


def urls(args, user_repository=True, postmarketos_mirror=True, alpine=True):
    """
    Get a list of repository URLs, as they are in /etc/apk/repositories.
    :param user_repository: add /mnt/pmbootstrap/packages
    :param postmarketos_mirror: add postmarketos mirror URLs
    :param alpine: add alpine mirror URLs
    :returns: list of mirror strings, like ["/mnt/pmbootstrap/packages",
                                            "http://...", ...]
    """
    ret = []

    # Get mirrordirs from channels.cfg (postmarketOS mirrordir is the same as
    # the pmaports branch of the channel, no need to make it more complicated)
    channel_cfg = pmb.config.pmaports.read_config_channel(args)
    mirrordir_pmos = channel_cfg["branch_pmaports"]
    mirrordir_alpine = channel_cfg["mirrordir_alpine"]

    # Local user repository (for packages compiled with pmbootstrap)
    if user_repository:
        ret.append("/mnt/pmbootstrap/packages")

    # Upstream postmarketOS binary repository
    if postmarketos_mirror:
        for mirror in args.mirrors_postmarketos:
            # Remove "master" mirrordir to avoid breakage until bpo is adjusted
            # (build.postmarketos.org#63) and to give potential other users of
            # this flag a heads up.
            if mirror.endswith("/master"):
                logging.warning("WARNING: 'master' at the end of"
                                " --mirror-pmOS is deprecated, the branch gets"
                                " added automatically now!")
                mirror = mirror[:-1 * len("master")]
            ret.append(f"{mirror}{mirrordir_pmos}")

    # Upstream Alpine Linux repositories
    if alpine:
        directories = ["main", "community"]
        if mirrordir_alpine == "edge":
            directories.append("testing")
        for dir in directories:
            ret.append(f"{args.mirror_alpine}{mirrordir_alpine}/{dir}")
    return ret


def apkindex_files(args, arch=None, user_repository=True, pmos=True,
                   alpine=True):
    """
    Get a list of outside paths to all resolved APKINDEX.tar.gz files for a
    specific arch.
    :param arch: defaults to native
    :param user_repository: add path to index of locally built packages
    :param pmos: add paths to indexes of postmarketos mirrors
    :param alpine: add paths to indexes of alpine mirrors
    :returns: list of absolute APKINDEX.tar.gz file paths
    """
    if not arch:
        arch = pmb.config.arch_native

    ret = []
    # Local user repository (for packages compiled with pmbootstrap)
    if user_repository:
        channel = pmb.config.pmaports.read_config(args)["channel"]
        ret = [f"{args.work}/packages/{channel}/{arch}/APKINDEX.tar.gz"]

    # Resolve the APKINDEX.$HASH.tar.gz files
    for url in urls(args, False, pmos, alpine):
        ret.append(args.work + "/cache_apk_" + arch + "/APKINDEX." +
                   hash(url) + ".tar.gz")

    return ret


def update(args, arch=None, force=False, existing_only=False):
    """
    Download the APKINDEX files for all URLs depending on the architectures.

    :param arch: * one Alpine architecture name ("x86_64", "armhf", ...)
                 * None for all architectures
    :param force: even update when the APKINDEX file is fairly recent
    :param existing_only: only update the APKINDEX files that already exist,
                          this is used by "pmbootstrap update"

    :returns: True when files have been downloaded, False otherwise
    """
    # Skip in offline mode, only show once
    cache_key = "pmb.helpers.repo.update"
    if args.offline:
        if not pmb.helpers.other.cache[cache_key]["offline_msg_shown"]:
            logging.info("NOTE: skipping package index update (offline mode)")
            pmb.helpers.other.cache[cache_key]["offline_msg_shown"] = True
        return False

    # Architectures and retention time
    architectures = [arch] if arch else pmb.config.build_device_architectures
    retention_hours = pmb.config.apkindex_retention_time
    retention_seconds = retention_hours * 3600

    # Find outdated APKINDEX files. Formats:
    # outdated: {URL: apkindex_path, ... }
    # outdated_arches: ["armhf", "x86_64", ... ]
    outdated = {}
    outdated_arches = []
    for url in urls(args, False):
        for arch in architectures:
            # APKINDEX file name from the URL
            url_full = url + "/" + arch + "/APKINDEX.tar.gz"
            cache_apk_outside = args.work + "/cache_apk_" + arch
            apkindex = cache_apk_outside + "/APKINDEX." + hash(url) + ".tar.gz"

            # Find update reason, possibly skip non-existing or known 404 files
            reason = None
            if url_full in pmb.helpers.other.cache[cache_key]["404"]:
                # We already attempted to download this file once in this
                # session
                continue
            elif not os.path.exists(apkindex):
                if existing_only:
                    continue
                reason = "file does not exist yet"
            elif force:
                reason = "forced update"
            elif pmb.helpers.file.is_older_than(apkindex, retention_seconds):
                reason = "older than " + str(retention_hours) + "h"
            if not reason:
                continue

            # Update outdated and outdated_arches
            logging.debug("APKINDEX outdated (" + reason + "): " + url_full)
            outdated[url_full] = apkindex
            if arch not in outdated_arches:
                outdated_arches.append(arch)

    # Bail out or show log message
    if not len(outdated):
        return False
    logging.info("Update package index for " + ", ".join(outdated_arches) +
                 " (" + str(len(outdated)) + " file(s))")

    # Download and move to right location
    for (i, (url, target)) in enumerate(outdated.items()):
        pmb.helpers.cli.progress_print(args, i / len(outdated))
        temp = pmb.helpers.http.download(args, url, "APKINDEX", False,
                                         logging.DEBUG, True)
        if not temp:
            pmb.helpers.other.cache[cache_key]["404"].append(url)
            continue
        target_folder = os.path.dirname(target)
        if not os.path.exists(target_folder):
            pmb.helpers.run.root(args, ["mkdir", "-p", target_folder])
        pmb.helpers.run.root(args, ["cp", temp, target])
    pmb.helpers.cli.progress_flush(args)

    return True


def alpine_apkindex_path(args, repo="main", arch=None):
    """
    Get the path to a specific Alpine APKINDEX file on disk and download it if
    necessary.

    :param repo: Alpine repository name (e.g. "main")
    :param arch: Alpine architecture (e.g. "armhf"), defaults to native arch.
    :returns: full path to the APKINDEX file
    """
    # Repo sanity check
    if repo not in ["main", "community", "testing", "non-free"]:
        raise RuntimeError("Invalid Alpine repository: " + repo)

    # Download the file
    arch = arch or pmb.config.arch_native
    update(args, arch)

    # Find it on disk
    channel_cfg = pmb.config.pmaports.read_config_channel(args)
    repo_link = f"{args.mirror_alpine}{channel_cfg['mirrordir_alpine']}/{repo}"
    cache_folder = args.work + "/cache_apk_" + arch
    return cache_folder + "/APKINDEX." + hash(repo_link) + ".tar.gz"
