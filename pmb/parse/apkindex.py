# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import collections
import logging
import os
import tarfile
import pmb.chroot.apk
import pmb.helpers.package
import pmb.helpers.repo
import pmb.parse.version


def parse_next_block(path, lines, start):
    """
    Parse the next block in an APKINDEX.

    :param path: to the APKINDEX.tar.gz
    :param start: current index in lines, gets increased in this
                  function. Wrapped into a list, so it can be modified
                  "by reference". Example: [5]
    :param lines: all lines from the "APKINDEX" file inside the archive
    :returns: a dictionary with the following structure:
              { "arch": "noarch",
                "depends": ["busybox-extras", "lddtree", ... ],
                "origin": "postmarketos-mkinitfs",
                "pkgname": "postmarketos-mkinitfs",
                "provides": ["mkinitfs=0.0.1"],
                "timestamp": "1500000000",
                "version": "0.0.4-r10" }
              NOTE: "depends" is not set for packages without any dependencies,
                    e.g. musl.
              NOTE: "timestamp" and "origin" are not set for virtual packages
                    (#1273). We use that information to skip these virtual
                    packages in parse().
    :returns: None, when there are no more blocks
    """

    # Parse until we hit an empty line or end of file
    ret = {}
    mapping = {
        "A": "arch",
        "D": "depends",
        "o": "origin",
        "P": "pkgname",
        "p": "provides",
        "k": "provider_priority",
        "t": "timestamp",
        "V": "version",
    }
    end_of_block_found = False
    for i in range(start[0], len(lines)):
        # Check for empty line
        start[0] = i + 1
        line = lines[i]
        if not isinstance(line, str):
            line = line.decode()
        if line == "\n":
            end_of_block_found = True
            break

        # Parse keys from the mapping
        for letter, key in mapping.items():
            if line.startswith(letter + ":"):
                if key in ret:
                    raise RuntimeError(
                        "Key " + key + " (" + letter + ":) specified twice"
                        " in block: " + str(ret) + ", file: " + path)
                ret[key] = line[2:-1]

    # Format and return the block
    if end_of_block_found:
        # Check for required keys
        for key in ["arch", "pkgname", "version"]:
            if key not in ret:
                raise RuntimeError(f"Missing required key '{key}' in block "
                                   f"{ret}, file: {path}")

        # Format optional lists
        for key in ["provides", "depends"]:
            if key in ret and ret[key] != "":
                # Ignore all operators for now
                values = ret[key].split(" ")
                ret[key] = []
                for value in values:
                    for operator in [">", "=", "<", "~"]:
                        if operator in value:
                            value = value.split(operator)[0]
                            break
                    ret[key].append(value)
            else:
                ret[key] = []
        return ret

    # No more blocks
    elif ret != {}:
        raise RuntimeError("Last block in " + path + " does not end"
                           " with a new line! Delete the file and"
                           " try again. Last block: " + str(ret))
    return None


def parse_add_block(ret, block, alias=None, multiple_providers=True):
    """
    Add one block to the return dictionary of parse().

    :param ret: dictionary of all packages in the APKINDEX that is
                getting built right now. This function will extend it.
    :param block: return value from parse_next_block().
    :param alias: defaults to the pkgname, could be an alias from the
                  "provides" list.
    :param multiple_providers: assume that there are more than one provider for
                               the alias. This makes sense when parsing the
                               APKINDEX files from a repository (#1122), but
                               not when parsing apk's installed packages DB.
    """

    # Defaults
    pkgname = block["pkgname"]
    alias = alias or pkgname

    # Get an existing block with the same alias
    block_old = None
    if multiple_providers and alias in ret and pkgname in ret[alias]:
        block_old = ret[alias][pkgname]
    elif not multiple_providers and alias in ret:
        block_old = ret[alias]

    # Ignore the block, if the block we already have has a higher version
    if block_old:
        version_old = block_old["version"]
        version_new = block["version"]
        if pmb.parse.version.compare(version_old, version_new) == 1:
            return

    # Add it to the result set
    if multiple_providers:
        if alias not in ret:
            ret[alias] = {}
        ret[alias][pkgname] = block
    else:
        ret[alias] = block


def parse(path, multiple_providers=True):
    """
    Parse an APKINDEX.tar.gz file, and return its content as dictionary.

    :param path: path to an APKINDEX.tar.gz file or apk package database
                 (almost the same format, but not compressed).
    :param multiple_providers: assume that there are more than one provider for
                               the alias. This makes sense when parsing the
                               APKINDEX files from a repository (#1122), but
                               not when parsing apk's installed packages DB.
    :returns: (without multiple_providers)
              generic format:
              { pkgname: block, ... }

              example:
              { "postmarketos-mkinitfs": block,
                "so:libGL.so.1": block, ...}

    :returns: (with multiple_providers)
              generic format:
              { provide: { pkgname: block, ... }, ... }

              example:
              { "postmarketos-mkinitfs": {"postmarketos-mkinitfs": block},
                "so:libGL.so.1": {"mesa-egl": block, "libhybris": block}, ...}

    NOTE: "block" is the return value from parse_next_block() above.
    """
    # Require the file to exist
    if not os.path.isfile(path):
        logging.verbose("NOTE: APKINDEX not found, assuming no binary packages"
                        " exist for that architecture: " + path)
        return {}

    # Try to get a cached result first
    lastmod = os.path.getmtime(path)
    cache_key = "multiple" if multiple_providers else "single"
    if path in pmb.helpers.other.cache["apkindex"]:
        cache = pmb.helpers.other.cache["apkindex"][path]
        if cache["lastmod"] == lastmod:
            if cache_key in cache:
                return cache[cache_key]
        else:
            clear_cache(path)

    # Read all lines
    if tarfile.is_tarfile(path):
        with tarfile.open(path, "r:gz") as tar:
            with tar.extractfile(tar.getmember("APKINDEX")) as handle:
                lines = handle.readlines()
    else:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()

    # Parse the whole APKINDEX file
    ret = collections.OrderedDict()
    start = [0]
    while True:
        block = parse_next_block(path, lines, start)
        if not block:
            break

        # Skip virtual packages
        if "timestamp" not in block:
            logging.verbose("Skipped virtual package " + str(block) + " in"
                            " file: " + path)
            continue

        # Add the next package and all aliases
        parse_add_block(ret, block, None, multiple_providers)
        if "provides" in block:
            for alias in block["provides"]:
                parse_add_block(ret, block, alias, multiple_providers)

    # Update the cache
    if path not in pmb.helpers.other.cache["apkindex"]:
        pmb.helpers.other.cache["apkindex"][path] = {"lastmod": lastmod}
    pmb.helpers.other.cache["apkindex"][path][cache_key] = ret
    return ret


def parse_blocks(path):
    """
    Read all blocks from an APKINDEX.tar.gz into a list.

    :path: full path to the APKINDEX.tar.gz file.
    :returns: all blocks in the APKINDEX, without restructuring them by
              pkgname or removing duplicates with lower versions (use
              parse() if you need these features). Structure:
              [block, block, ...]

    NOTE: "block" is the return value from parse_next_block() above.
    """
    # Parse all lines
    with tarfile.open(path, "r:gz") as tar:
        with tar.extractfile(tar.getmember("APKINDEX")) as handle:
            lines = handle.readlines()

    # Parse lines into blocks
    ret = []
    start = [0]
    while True:
        block = pmb.parse.apkindex.parse_next_block(path, lines, start)
        if not block:
            return ret
        ret.append(block)


def clear_cache(path):
    """
    Clear the APKINDEX parsing cache.

    :returns: True on successful deletion, False otherwise
    """
    logging.verbose("Clear APKINDEX cache for: " + path)
    if path in pmb.helpers.other.cache["apkindex"]:
        del pmb.helpers.other.cache["apkindex"][path]
        return True
    else:
        logging.verbose("Nothing to do, path was not in cache:" +
                        str(pmb.helpers.other.cache["apkindex"].keys()))
        return False


def providers(args, package, arch=None, must_exist=True, indexes=None):
    """
    Get all packages, which provide one package.

    :param package: of which you want to have the providers
    :param arch: defaults to native arch, only relevant for indexes=None
    :param must_exist: When set to true, raise an exception when the package is
                       not provided at all.
    :param indexes: list of APKINDEX.tar.gz paths, defaults to all index files
                    (depending on arch)
    :returns: list of parsed packages. Example for package="so:libGL.so.1":
                  {"mesa-egl": block, "libhybris": block}
              block is the return value from parse_next_block() above.
    """

    if not indexes:
        arch = arch or pmb.config.arch_native
        indexes = pmb.helpers.repo.apkindex_files(args, arch)

    package = pmb.helpers.package.remove_operators(package)

    ret = collections.OrderedDict()
    for path in indexes:
        # Skip indexes not providing the package
        index_packages = parse(path)
        if package not in index_packages:
            continue

        # Iterate over found providers
        for provider_pkgname, provider in index_packages[package].items():
            # Skip lower versions of providers we already found
            version = provider["version"]
            if provider_pkgname in ret:
                version_last = ret[provider_pkgname]["version"]
                if pmb.parse.version.compare(version, version_last) == -1:
                    logging.verbose(package + ": provided by: " +
                                    provider_pkgname + "-" + version + " in " +
                                    path + " (but " + version_last + " is"
                                    " higher)")
                    continue

            # Add the provider to ret
            logging.verbose(package + ": provided by: " + provider_pkgname +
                            "-" + version + " in " + path)
            ret[provider_pkgname] = provider

    if ret == {} and must_exist:
        logging.debug("Searched in APKINDEX files: " + ", ".join(indexes))
        raise RuntimeError("Could not find package '" + package + "'!")

    return ret


def provider_highest_priority(providers, pkgname):
    """
    Get the provider(s) with the highest provider_priority and log a message.

    :param providers: returned dict from providers(), must not be empty
    :param pkgname: the package name we are interested in (for the log message)
    """
    max_priority = 0
    priority_providers = collections.OrderedDict()
    for provider_name, provider in providers.items():
        priority = int(provider.get("provider_priority", -1))
        if priority > max_priority:
            priority_providers.clear()
            max_priority = priority
        if priority == max_priority:
            priority_providers[provider_name] = provider

    if priority_providers:
        logging.debug(
            f"{pkgname}: picked provider(s) with highest priority "
            f"{max_priority}: {', '.join(priority_providers.keys())}")
        return priority_providers

    # None of the providers seems to have a provider_priority defined
    return providers


def provider_shortest(providers, pkgname):
    """
    Get the provider with the shortest pkgname and log a message. In most cases
    this should be sufficient, e.g. 'mesa-purism-gc7000-egl, mesa-egl' or
    'gtk+2.0-maemo, gtk+2.0'.

    :param providers: returned dict from providers(), must not be empty
    :param pkgname: the package name we are interested in (for the log message)
    """
    ret = min(list(providers.keys()), key=len)
    if len(providers) != 1:
        logging.debug(
            f"{pkgname}: has multiple providers ("
            f"{', '.join(providers.keys())}), picked shortest: {ret}")
    return providers[ret]


def package(args, package, arch=None, must_exist=True, indexes=None):
    """
    Get a specific package's data from an apkindex.

    :param package: of which you want to have the apkindex data
    :param arch: defaults to native arch, only relevant for indexes=None
    :param must_exist: When set to true, raise an exception when the package is
                       not provided at all.
    :param indexes: list of APKINDEX.tar.gz paths, defaults to all index files
                    (depending on arch)
    :returns: a dictionary with the following structure:
              { "arch": "noarch",
                "depends": ["busybox-extras", "lddtree", ... ],
                "pkgname": "postmarketos-mkinitfs",
                "provides": ["mkinitfs=0.0.1"],
                "version": "0.0.4-r10" }
              or None when the package was not found.
    """
    # Provider with the same package
    package_providers = providers(args, package, arch, must_exist, indexes)
    if package in package_providers:
        return package_providers[package]

    # Any provider
    if package_providers:
        return pmb.parse.apkindex.provider_shortest(package_providers, package)

    # No provider
    if must_exist:
        raise RuntimeError("Package '" + package + "' not found in any"
                           " APKINDEX.")
    return None
