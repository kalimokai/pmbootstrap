# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Functions that work with both pmaports and binary package repos. See also:
- pmb/helpers/pmaports.py (work with pmaports)
- pmb/helpers/repo.py (work with binary package repos)
"""
import copy
import logging

import pmb.helpers.pmaports
import pmb.helpers.repo


def remove_operators(package):
    for operator in [">", ">=", "<=", "=", "<", "~"]:
        if operator in package:
            package = package.split(operator)[0]
            break
    return package


def get(args, pkgname, arch, replace_subpkgnames=False, must_exist=True):
    """ Find a package in pmaports, and as fallback in the APKINDEXes of the
        binary packages.
        :param pkgname: package name (e.g. "hello-world")
        :param arch: preferred architecture of the binary package. When it
                     can't be found for this arch, we'll still look for another
                     arch to see whether the package exists at all. So make
                     sure to check the returned arch against what you wanted
                     with check_arch(). Example: "armhf"
        :param replace_subpkgnames: replace all subpkgnames with their main
                                    pkgnames in the depends (see #1733)
        :param must_exist: raise an exception, if not found
        :returns: * data from the parsed APKBUILD or APKINDEX in the following
                    format: {"arch": ["noarch"],
                             "depends": ["busybox-extras", "lddtree", ...],
                             "pkgname": "postmarketos-mkinitfs",
                             "provides": ["mkinitfs=0..1"],
                             "version": "0.0.4-r10"}
                  * None if the package was not found """
    # Cached result
    cache_key = "pmb.helpers.package.get"
    if (
        arch in pmb.helpers.other.cache[cache_key] and
        pkgname in pmb.helpers.other.cache[cache_key][arch] and
        replace_subpkgnames in pmb.helpers.other.cache[cache_key][arch][
            pkgname
        ]
    ):
        return pmb.helpers.other.cache[cache_key][arch][pkgname][
            replace_subpkgnames
        ]

    # Find in pmaports
    ret = None
    pmaport = pmb.helpers.pmaports.get(args, pkgname, False)
    if pmaport:
        ret = {"arch": pmaport["arch"],
               "depends": pmb.build._package.get_depends(args, pmaport),
               "pkgname": pmaport["pkgname"],
               "provides": pmaport["provides"],
               "version": pmaport["pkgver"] + "-r" + pmaport["pkgrel"]}

    # Find in APKINDEX (given arch)
    if not ret or not pmb.helpers.pmaports.check_arches(ret["arch"], arch):
        pmb.helpers.repo.update(args, arch)
        ret_repo = pmb.parse.apkindex.package(args, pkgname, arch, False)

        # Save as result if there was no pmaport, or if the pmaport can not be
        # built for the given arch, but there is a binary package for that arch
        # (e.g. temp/mesa can't be built for x86_64, but Alpine has it)
        if not ret or (ret_repo and ret_repo["arch"] == arch):
            ret = ret_repo

    # Find in APKINDEX (other arches)
    if not ret:
        pmb.helpers.repo.update(args)
        for arch_i in pmb.config.build_device_architectures:
            if arch_i != arch:
                ret = pmb.parse.apkindex.package(args, pkgname, arch_i, False)
            if ret:
                break

    # Copy ret (it might have references to caches of the APKINDEX or APKBUILDs
    # and we don't want to modify those!)
    if ret:
        ret = copy.deepcopy(ret)

    # Make sure ret["arch"] is a list (APKINDEX code puts a string there)
    if ret and isinstance(ret["arch"], str):
        ret["arch"] = [ret["arch"]]

    # Replace subpkgnames if desired
    if replace_subpkgnames:
        depends_new = []
        for depend in ret["depends"]:
            depend_data = get(args, depend, arch, must_exist=False)
            if not depend_data:
                logging.warning(f"WARNING: {pkgname}: failed to resolve"
                                f" dependency '{depend}'")
                # Can't replace potential subpkgname
                if depend not in depends_new:
                    depends_new += [depend]
                continue
            depend_pkgname = depend_data["pkgname"]
            if depend_pkgname not in depends_new:
                depends_new += [depend_pkgname]
        ret["depends"] = depends_new

    # Save to cache and return
    if ret:
        if arch not in pmb.helpers.other.cache[cache_key]:
            pmb.helpers.other.cache[cache_key][arch] = {}
        if pkgname not in pmb.helpers.other.cache[cache_key][arch]:
            pmb.helpers.other.cache[cache_key][arch][pkgname] = {}
        pmb.helpers.other.cache[cache_key][arch][pkgname][
            replace_subpkgnames
        ] = ret
        return ret

    # Could not find the package
    if not must_exist:
        return None
    raise RuntimeError("Package '" + pkgname + "': Could not find aport, and"
                       " could not find this package in any APKINDEX!")


def depends_recurse(args, pkgname, arch):
    """ Recursively resolve all of the package's dependencies.
        :param pkgname: name of the package (e.g. "device-samsung-i9100")
        :param arch: preferred architecture for binary packages
        :returns: a list of pkgname_start and all its dependencies, e.g:
                  ["busybox-static-armhf", "device-samsung-i9100",
                   "linux-samsung-i9100", ...] """
    # Cached result
    cache_key = "pmb.helpers.package.depends_recurse"
    if (arch in pmb.helpers.other.cache[cache_key] and
            pkgname in pmb.helpers.other.cache[cache_key][arch]):
        return pmb.helpers.other.cache[cache_key][arch][pkgname]

    # Build ret (by iterating over the queue)
    queue = [pkgname]
    ret = []
    while len(queue):
        pkgname_queue = queue.pop()
        package = get(args, pkgname_queue, arch)

        # Add its depends to the queue
        for depend in package["depends"]:
            if depend not in ret:
                queue += [depend]

        # Add the pkgname (not possible subpkgname) to ret
        if package["pkgname"] not in ret:
            ret += [package["pkgname"]]
    ret.sort()

    # Save to cache and return
    if arch not in pmb.helpers.other.cache[cache_key]:
        pmb.helpers.other.cache[cache_key][arch] = {}
    pmb.helpers.other.cache[cache_key][arch][pkgname] = ret
    return ret


def check_arch(args, pkgname, arch, binary=True):
    """ Can a package be built for a certain architecture, or is there a binary
        package for it?

        :param pkgname: name of the package
        :param arch: architecture to check against
        :param binary: set to False to only look at the pmaports, not at binary
                       packages
        :returns: True when the package can be built, or there is a binary
                  package, False otherwise
    """
    if binary:
        arches = get(args, pkgname, arch)["arch"]
    else:
        arches = pmb.helpers.pmaports.get(args, pkgname)["arch"]
    return pmb.helpers.pmaports.check_arches(arches, arch)
