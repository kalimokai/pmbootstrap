# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import pmb.chroot
import pmb.chroot.apk
import pmb.helpers.pmaports
import pmb.parse.apkindex
import pmb.parse.arch


def package_from_aports(args, pkgname_depend):
    """
    :returns: None when there is no aport, or a dict with the keys pkgname,
              depends, version. The version is the combined pkgver and pkgrel.
    """
    # Get the aport
    aport = pmb.helpers.pmaports.find(args, pkgname_depend, False)
    if not aport:
        return None

    # Parse its version
    apkbuild = pmb.parse.apkbuild(f"{aport}/APKBUILD")
    pkgname = apkbuild["pkgname"]
    version = apkbuild["pkgver"] + "-r" + apkbuild["pkgrel"]

    # Return the dict
    logging.verbose(
        f"{pkgname_depend}: provided by: {pkgname}-{version} in {aport}")
    return {"pkgname": pkgname,
            "depends": apkbuild["depends"],
            "version": version}


def package_provider(args, pkgname, pkgnames_install, suffix="native"):
    """
    :param pkgnames_install: packages to be installed
    :returns: a block from the apkindex: {"pkgname": "...", ...}
              or None (no provider found)
    """
    # Get all providers
    arch = pmb.parse.arch.from_chroot_suffix(args, suffix)
    providers = pmb.parse.apkindex.providers(args, pkgname, arch, False)

    # 0. No provider
    if len(providers) == 0:
        return None

    # 1. Only one provider
    logging.verbose(f"{pkgname}: provided by: {', '.join(providers)}")
    if len(providers) == 1:
        return list(providers.values())[0]

    # 2. Provider with the same package name
    if pkgname in providers:
        logging.verbose(f"{pkgname}: choosing package of the same name as "
                        "provider")
        return providers[pkgname]

    # 3. Pick a package that will be installed anyway
    for provider_pkgname, provider in providers.items():
        if provider_pkgname in pkgnames_install:
            logging.verbose(f"{pkgname}: choosing provider '{provider_pkgname}"
                            "', because it will be installed anyway")
            return provider

    # 4. Pick a package that is already installed
    installed = pmb.chroot.apk.installed(args, suffix)
    for provider_pkgname, provider in providers.items():
        if provider_pkgname in installed:
            logging.verbose(f"{pkgname}: choosing provider '{provider_pkgname}"
                            f"', because it is installed in the '{suffix}' "
                            "chroot already")
            return provider

    # 5. Pick an explicitly selected provider
    provider_pkgname = args.selected_providers.get(pkgname, "")
    if provider_pkgname in providers:
        logging.verbose(f"{pkgname}: choosing provider '{provider_pkgname}', "
                        "because it was explicitly selected.")
        return providers[provider_pkgname]

    # 6. Pick the provider(s) with the highest priority
    providers = pmb.parse.apkindex.provider_highest_priority(
        providers, pkgname)
    if len(providers) == 1:
        return list(providers.values())[0]

    # 7. Pick the shortest provider. (Note: Normally apk would fail here!)
    return pmb.parse.apkindex.provider_shortest(providers, pkgname)


def package_from_index(args, pkgname_depend, pkgnames_install, package_aport,
                       suffix="native"):
    """
    :returns: None when there is no aport and no binary package, or a dict with
              the keys pkgname, depends, version from either the aport or the
              binary package provider.
    """
    # No binary package
    provider = package_provider(args, pkgname_depend, pkgnames_install, suffix)
    if not provider:
        return package_aport

    # Binary package outdated
    if (package_aport and pmb.parse.version.compare(package_aport["version"],
                                                    provider["version"]) == 1):
        logging.verbose(pkgname_depend + ": binary package is outdated")
        return package_aport

    # Binary up to date (#893: overrides aport, so we have sonames in depends)
    if package_aport:
        logging.verbose(pkgname_depend + ": binary package is"
                        " up to date, using binary dependencies"
                        " instead of the ones from the aport")
    return provider


def recurse(args, pkgnames, suffix="native"):
    """
    Find all dependencies of the given pkgnames.

    :param suffix: the chroot suffix to resolve dependencies for. If a package
                   has multiple providers, we look at the installed packages in
                   the chroot to make a decision (see package_provider()).
    :returns: list of pkgnames: consists of the initial pkgnames plus all
              depends. Dependencies explicitly marked as conflicting are
              prefixed with !.
    """
    logging.debug(f"({suffix}) calculate depends of {', '.join(pkgnames)} "
                  "(pmbootstrap -v for details)")

    # Iterate over todo-list until is is empty
    todo = list(pkgnames)
    required_by = {}
    ret = []
    while len(todo):
        # Skip already passed entries
        pkgname_depend = todo.pop(0)
        if pkgname_depend in ret:
            continue

        # Check if the dependency is explicitly marked as conflicting
        is_conflict = pkgname_depend.startswith("!")
        pkgname_depend = pkgname_depend.lstrip("!")

        # Get depends and pkgname from aports
        pkgnames_install = list(ret) + todo
        package = package_from_aports(args, pkgname_depend)
        package = package_from_index(args, pkgname_depend, pkgnames_install,
                                     package, suffix)

        # Nothing found
        if not package:
            if is_conflict:
                # This package was probably dropped from the repos, so we don't
                # care if it doesn't exist since it's a conflicting depend that
                # wouldn't be installed anyways.
                continue
            source = 'world'
            if pkgname_depend in required_by:
                source = ', '.join(required_by[pkgname_depend])
            raise RuntimeError(f"Could not find dependency '{pkgname_depend}' "
                               "in checked out pmaports dir or any APKINDEX. "
                               f"Required by '{source}'. See: "
                               "https://postmarketos.org/depends")

        # Determine pkgname
        pkgname = package["pkgname"]
        if is_conflict:
            pkgname = f"!{pkgname}"

        # Append to todo/ret (unless it is a duplicate)
        if pkgname in ret:
            logging.verbose(f"{pkgname}: already found")
        else:
            if not is_conflict:
                depends = package["depends"]
                logging.verbose(f"{pkgname}: depends on: {','.join(depends)}")
                if depends:
                    todo += depends
                    for dep in depends:
                        if dep not in required_by:
                            required_by[dep] = set()
                        required_by[dep].add(pkgname_depend)
            ret.append(pkgname)
    return ret
