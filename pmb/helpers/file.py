# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import time

import pmb.helpers.run


def replace(path, old, new):
    text = ""
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()

    text = text.replace(old, new)

    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def replace_apkbuild(args, pkgname, key, new, in_quotes=False):
    """ Replace one key=value line in an APKBUILD and verify it afterwards.
        :param pkgname: package name, e.g. "hello-world"
        :param key: key that should be replaced, e.g. "pkgver"
        :param new: new value
        :param in_quotes: expect the value to be in quotation marks ("") """
    # Read old value
    path = pmb.helpers.pmaports.find(args, pkgname) + "/APKBUILD"
    apkbuild = pmb.parse.apkbuild(path)
    old = apkbuild[key]

    # Prepare old/new strings
    if in_quotes:
        line_old = '{}="{}"'.format(key, old)
        line_new = '{}="{}"'.format(key, new)
    else:
        line_old = '{}={}'.format(key, old)
        line_new = '{}={}'.format(key, new)

    # Replace
    replace(path, "\n" + line_old + "\n", "\n" + line_new + "\n")

    # Verify
    del (pmb.helpers.other.cache["apkbuild"][path])
    apkbuild = pmb.parse.apkbuild(path)
    if apkbuild[key] != str(new):
        raise RuntimeError("Failed to set '{}' for pmaport '{}'. Make sure"
                           " that there's a line with exactly the string '{}'"
                           " and nothing else in: {}".format(key, pkgname,
                                                             line_old, path))


def is_up_to_date(path_sources, path_target=None, lastmod_target=None):
    """
    Check if a file is up-to-date by comparing the last modified timestamps
    (just like make does it).

    :param path_sources: list of full paths to the source files
    :param path_target: full path to the target file
    :param lastmod_target: the timestamp of the target file. specify this as
                           alternative to specifying path_target.
    """

    if path_target and lastmod_target:
        raise RuntimeError(
            "Specify path_target *or* lastmod_target, not both!")

    lastmod_source = None
    for path_source in path_sources:
        lastmod = os.path.getmtime(path_source)
        if not lastmod_source or lastmod > lastmod_source:
            lastmod_source = lastmod

    if path_target:
        lastmod_target = os.path.getmtime(path_target)

    return lastmod_target >= lastmod_source


def is_older_than(path, seconds):
    """
    Check if a single file is older than a given amount of seconds.
    """
    if not os.path.exists(path):
        return True
    lastmod = os.path.getmtime(path)
    return lastmod + seconds < time.time()


def symlink(args, file, link):
    """
    Checks if the symlink is already present, otherwise create it.
    """
    if os.path.exists(link):
        if (os.path.islink(link) and
                os.path.realpath(os.readlink(link)) == os.path.realpath(file)):
            return
        raise RuntimeError("File exists: " + link)
    elif os.path.islink(link):
        os.unlink(link)

    # Create the symlink
    pmb.helpers.run.user(args, ["ln", "-s", file, link])
