# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import sys
import pytest

import pmb_test  # noqa
import pmb.helpers.logging
import pmb.helpers.pmaports


@pytest.fixture
def args(request, tmpdir):
    import pmb.parse
    sys.argv = ["pmbootstrap.py", "chroot"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)

    # Create an empty APKINDEX.tar.gz file, so we can use its path and
    # timestamp to put test information in the cache.
    apkindex_path = str(tmpdir) + "/APKINDEX.tar.gz"
    open(apkindex_path, "a").close()
    lastmod = os.path.getmtime(apkindex_path)
    pmb.helpers.other.cache["apkindex"][apkindex_path] = {"lastmod": lastmod,
                                                          "multiple": {}}
    return args


def cache_apkindex(version):
    """
    Modify the cache of the parsed binary package repository's APKINDEX
    for the "hello-world" package.
    :param version: full version string, includes pkgver and pkgrl (e.g. 1-r2)
    """
    apkindex_path = list(pmb.helpers.other.cache["apkindex"].keys())[0]

    providers = pmb.helpers.other.cache[
        "apkindex"][apkindex_path]["multiple"]["hello-world"]
    providers["hello-world"]["version"] = version


def test_build_is_necessary(args):
    # Prepare APKBUILD and APKINDEX data
    aport = pmb.helpers.pmaports.find(args, "hello-world")
    apkbuild = pmb.parse.apkbuild(f"{aport}/APKBUILD")
    apkbuild["pkgver"] = "1"
    apkbuild["pkgrel"] = "2"
    indexes = list(pmb.helpers.other.cache["apkindex"].keys())
    apkindex_path = indexes[0]
    cache = {"hello-world": {"hello-world": {"pkgname": "hello-world",
                                             "version": "1-r2"}}}
    pmb.helpers.other.cache["apkindex"][apkindex_path]["multiple"] = cache

    # Binary repo has a newer version
    cache_apkindex("999-r1")
    assert pmb.build.is_necessary(args, None, apkbuild, indexes) is False

    # Aports folder has a newer version
    cache_apkindex("0-r0")
    assert pmb.build.is_necessary(args, None, apkbuild, indexes) is True

    # Same version
    cache_apkindex("1-r2")
    assert pmb.build.is_necessary(args, None, apkbuild, indexes) is False


def test_build_is_necessary_no_binary_available(args):
    """
    APKINDEX cache is set up to fake an empty APKINDEX, which means that the
    hello-world package has not been built yet.
    """
    indexes = list(pmb.helpers.other.cache["apkindex"].keys())
    aport = pmb.helpers.pmaports.find(args, "hello-world")
    apkbuild = pmb.parse.apkbuild(f"{aport}/APKBUILD")
    assert pmb.build.is_necessary(args, None, apkbuild, indexes) is True


def test_build_is_necessary_cant_build_pmaport_for_arch(args):
    """ pmaport version is higher than Alpine's binary package, but pmaport
        can't be built for given arch. (#1897) """

    apkbuild = {"pkgname": "alpine-base",
                "arch": "armhf",  # can't build for x86_64!
                "pkgver": "9999",
                "pkgrel": "0"}
    assert pmb.build.is_necessary(args, "x86_64", apkbuild) is False
    assert pmb.build.is_necessary(args, "armhf", apkbuild) is True
