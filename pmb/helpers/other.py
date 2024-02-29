# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import glob
import logging
import os
import re
import pmb.chroot
import pmb.config
import pmb.config.init
import pmb.helpers.pmaports
import pmb.helpers.run


def folder_size(args, path):
    """
    Run `du` to calculate the size of a folder (this is less code and
    faster than doing the same task in pure Python). This result is only
    approximatelly right, but good enough for pmbootstrap's use case (#760).

    :returns: folder size in kilobytes
    """
    output = pmb.helpers.run.root(args, ["du", "-ks",
                                         path], output_return=True)

    # Only look at last line to filter out sudo garbage (#1766)
    last_line = output.split("\n")[-2]

    ret = int(last_line.split("\t")[0])
    return ret


def check_grsec():
    """
    Check if the current kernel is based on the grsec patchset, and if
    the chroot_deny_chmod option is enabled. Raise an exception in that
    case, with a link to the issue. Otherwise, do nothing.
    """
    path = "/proc/sys/kernel/grsecurity/chroot_deny_chmod"
    if not os.path.exists(path):
        return

    raise RuntimeError("You're running a kernel based on the grsec"
                       " patchset. This is not supported.")


def check_binfmt_misc(args):
    """
    Check if the 'binfmt_misc' module is loaded by checking, if
    /proc/sys/fs/binfmt_misc/ exists. If it exists, then do nothing.
    Otherwise, load the module and mount binfmt_misc.
    If that fails as well, raise an exception pointing the user to the wiki.
    """
    path = "/proc/sys/fs/binfmt_misc/status"
    if os.path.exists(path):
        return

    # check=False: this might be built-in instead of being a module
    pmb.helpers.run.root(args, ["modprobe", "binfmt_misc"], check=False)

    # check=False: we check it below and print a more helpful message on error
    pmb.helpers.run.root(args, ["mount", "-t", "binfmt_misc", "none",
                                "/proc/sys/fs/binfmt_misc"], check=False)

    if not os.path.exists(path):
        link = "https://postmarketos.org/binfmt_misc"
        raise RuntimeError(f"Failed to set up binfmt_misc, see: {link}")


def migrate_success(args, version):
    logging.info("Migration to version " + str(version) + " done")
    with open(args.work + "/version", "w") as handle:
        handle.write(str(version) + "\n")


def migrate_work_folder(args):
    # Read current version
    current = 0
    path = args.work + "/version"
    if os.path.exists(path):
        with open(path, "r") as f:
            current = int(f.read().rstrip())

    # Compare version, print warning or do nothing
    required = pmb.config.work_version
    if current == required:
        return
    logging.info("WARNING: Your work folder version needs to be migrated"
                 " (from version " + str(current) + " to " + str(required) +
                 ")!")

    # 0 => 1
    if current == 0:
        # Ask for confirmation
        logging.info("Changelog:")
        logging.info("* Building chroots have a different username (#709)")
        logging.info("Migration will do the following:")
        logging.info("* Zap your chroots")
        logging.info("* Adjust '" + args.work + "/config_abuild/abuild.conf'")
        if not pmb.helpers.cli.confirm(args):
            raise RuntimeError("Aborted.")

        # Zap and update abuild.conf
        pmb.chroot.zap(args, False)
        conf = args.work + "/config_abuild/abuild.conf"
        if os.path.exists(conf):
            pmb.helpers.run.root(args, ["sed", "-i",
                                        "s./home/user/./home/pmos/.g", conf])
        # Update version file
        migrate_success(args, 1)
        current = 1

    # 1 => 2
    if current == 1:
        # Ask for confirmation
        logging.info("Changelog:")
        logging.info("* Fix: cache_distfiles was writable for everyone")
        logging.info("Migration will do the following:")
        logging.info("* Fix permissions of '" + args.work +
                     "/cache_distfiles'")
        if not pmb.helpers.cli.confirm(args):
            raise RuntimeError("Aborted.")

        # Fix permissions
        dir = "/var/cache/distfiles"
        for cmd in [["chown", "-R", "root:abuild", dir],
                    ["chmod", "-R", "664", dir],
                    ["chmod", "a+X", dir]]:
            pmb.chroot.root(args, cmd)
        migrate_success(args, 2)
        current = 2

    if current == 2:
        # Ask for confirmation
        logging.info("Changelog:")
        logging.info("* Device chroots have a different user UID (#1576)")
        logging.info("Migration will do the following:")
        logging.info("* Zap your chroots")
        if not pmb.helpers.cli.confirm(args):
            raise RuntimeError("Aborted.")

        # Zap chroots
        pmb.chroot.zap(args, False)

        # Update version file
        migrate_success(args, 3)
        current = 3

    if current == 3:
        # Ask for confirmation
        path = args.work + "/cache_git"
        logging.info("Changelog:")
        logging.info("* pmbootstrap clones repositories with host system's")
        logging.info("  'git' instead of using it from an Alpine chroot")
        logging.info("Migration will do the following:")
        logging.info("* Check if 'git' is installed")
        logging.info("* Change ownership to your user: " + path)
        if not pmb.helpers.cli.confirm(args):
            raise RuntimeError("Aborted.")

        # Require git, set cache_git ownership
        pmb.config.init.require_programs()
        if os.path.exists(path):
            uid_gid = "{}:{}".format(os.getuid(), os.getgid())
            pmb.helpers.run.root(args, ["chown", "-R", uid_gid, path])
        else:
            os.makedirs(path, 0o700, True)

        # Update version file
        migrate_success(args, 4)
        current = 4

    if current == 4:
        # Ask for confirmation
        logging.info("Changelog:")
        logging.info("* packages built by pmbootstrap are in a channel subdir")
        logging.info("Migration will do the following:")
        logging.info("* Move existing packages to edge subdir (if any)")
        logging.info("* Zap your chroots")
        if not pmb.helpers.cli.confirm(args):
            raise RuntimeError("Aborted.")

        # Zap chroots
        pmb.chroot.zap(args, False)

        # Move packages to edge subdir
        edge_path = f"{args.work}/packages/edge"
        pmb.helpers.run.root(args, ["mkdir", "-p", edge_path])
        for arch in pmb.config.build_device_architectures:
            old_path = f"{args.work}/packages/{arch}"
            new_path = f"{edge_path}/{arch}"
            if os.path.exists(old_path):
                if os.path.exists(new_path):
                    raise RuntimeError(f"Won't move '{old_path}' to"
                                       f" '{new_path}', destination already"
                                       " exists! Consider 'pmbootstrap zap -p'"
                                       f" to delete '{args.work}/packages'.")
                pmb.helpers.run.root(args, ["mv", old_path, new_path])
        pmb.helpers.run.root(args, ["chown", pmb.config.chroot_uid_user,
                                    edge_path])

        # Update version file
        migrate_success(args, 5)
        current = 5

    if current == 5:
        # Ask for confirmation
        logging.info("Changelog:")
        logging.info("* besides edge, pmaports channels have the same name")
        logging.info("  as the branch now (pmbootstrap#2015)")
        logging.info("Migration will do the following:")
        logging.info("* Zap your chroots")
        logging.info("* Adjust subdirs of your locally built packages dir:")
        logging.info(f"  {args.work}/packages")
        logging.info("  stable => v20.05")
        logging.info("  stable-next => v21.03")
        if not pmb.helpers.cli.confirm(args):
            raise RuntimeError("Aborted.")

        # Zap chroots to avoid potential "ERROR: Chroot 'native' was created
        # for the 'stable' channel, but you are on the 'v20.05' channel now."
        pmb.chroot.zap(args, False)

        # Migrate
        packages_dir = f"{args.work}/packages"
        for old, new in pmb.config.pmaports_channels_legacy.items():
            if os.path.exists(f"{packages_dir}/{old}"):
                pmb.helpers.run.root(args, ["mv", old, new], packages_dir)

        # Update version file
        migrate_success(args, 6)
        current = 6

    # Can't migrate, user must delete it
    if current != required:
        raise RuntimeError("Sorry, we can't migrate that automatically. Please"
                           " run 'pmbootstrap shutdown', then delete your"
                           " current work folder manually ('sudo rm -rf " +
                           args.work + "') and start over with 'pmbootstrap"
                           " init'. All your binary packages and caches will"
                           " be lost.")


def check_old_devices(args):
    """
    Check if there are any device ports in device/*/APKBUILD,
    rather than device/*/*/APKBUILD (e.g. device/testing/...).
    """

    g = glob.glob(args.aports + "/device/*/APKBUILD")
    if not g:
        return

    raise RuntimeError("Found device ports outside device/testing/... "
                       "Please run 'pmbootstrap pull' and/or move the "
                       "following device ports to device/testing:\n - " +
                       '\n - '.join(g))


def validate_hostname(hostname):
    """
    Check whether the string is a valid hostname, according to
    <http://en.wikipedia.org/wiki/Hostname#Restrictions_on_valid_host_names>
    """
    # Check length
    if len(hostname) > 63:
        logging.fatal("ERROR: Hostname '" + hostname + "' is too long.")
        return False

    # Check that it only contains valid chars
    if not re.match(r"^[0-9a-z-\.]*$", hostname):
        logging.fatal("ERROR: Hostname must only contain letters (a-z),"
                      " digits (0-9), minus signs (-), or periods (.)")
        return False

    # Check that doesn't begin or end with a minus sign or period
    if re.search(r"^-|^\.|-$|\.$", hostname):
        logging.fatal("ERROR: Hostname must not begin or end with a minus"
                      " sign or period")
        return False

    return True


"""
pmbootstrap uses this dictionary to save the result of expensive
results, so they work a lot faster the next time they are needed in the
same session. Usually the cache is written to and read from in the same
Python file, with code similar to the following:

def lookup(key):
    if key in pmb.helpers.other.cache["mycache"]:
        return pmb.helpers.other.cache["mycache"][key]
    ret = expensive_operation(args, key)
    pmb.helpers.other.cache["mycache"][key] = ret
    return ret
"""
cache = None


def init_cache():
    global cache
    """ Add a caching dict (caches parsing of files etc. for the current
        session) """
    repo_update = {"404": [], "offline_msg_shown": False}
    cache = {"apkindex": {},
             "apkbuild": {},
             "apk_min_version_checked": [],
             "apk_repository_list_updated": [],
             "built": {},
             "find_aport": {},
             "pmb.helpers.package.depends_recurse": {},
             "pmb.helpers.package.get": {},
             "pmb.helpers.repo.update": repo_update,
             "pmb.helpers.git.parse_channels_cfg": {},
             "pmb.config.pmaports.read_config": None}
