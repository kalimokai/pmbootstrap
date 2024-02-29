# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import copy
import os
import pmb.config
import pmb.helpers.git

""" This file constructs the args variable, which is passed to almost all
    functions in the pmbootstrap code base. Here's a listing of the kind of
    information it stores.

    1. Argparse
       Variables directly from command line argument parsing (see
       pmb/parse/arguments.py, the "dest" parameter of the add_argument()
       calls defines where it is stored in args).

       Examples:
       args.action ("zap", "chroot", "build" etc.)
       args.as_root (True when --as-root is passed)
       ...

    2. Argparse merged with others
       Variables from the user's config file (~/.config/pmbootstrap.cfg) that
       can be overridden from the command line (pmb/parse/arguments.py) and
       fall back to the defaults defined in pmb/config/__init__.py (see
       "defaults = {..."). The user's config file gets generated interactively
        with "pmbootstrap init".

       Examples:
       args.aports ("$WORK/cache_git/pmaports", override with --aports)
       args.device ("samsung-i9100", "qemu-amd64" etc.)
       args.work ("/home/user/.local/var/pmbootstrap", override with --work)

    3. Parsed configs
       Similar to the cache above, specific config files get parsed and added
       to args, so they can get accessed quickly (without parsing the configs
       over and over). These configs are not only used in one specific
       location, so having a short name for them increases readability of the
       code as well.

       Examples:
       args.deviceinfo (e.g. {"name": "Mydevice", "arch": "armhf", ...})
"""


def fix_mirrors_postmarketos(args):
    """ Fix args.mirrors_postmarketos when it is supposed to be empty or the
        default value.

        In pmb/parse/arguments.py, we set the -mp/--mirror-pmOS argument to
        action="append" and start off with an empty list. That way, users can
        specify multiple custom mirrors by specifying -mp multiple times on the
        command line. Here we fix the default and no mirrors case.

        NOTE: we don't use nargs="+", because it does not play nicely with
        subparsers: <https://bugs.python.org/issue9338> """
    # -mp not specified: use default mirrors
    if not args.mirrors_postmarketos:
        cfg = pmb.config.load(args)
        args.mirrors_postmarketos = \
            cfg["pmbootstrap"]["mirrors_postmarketos"].split(",")

    # -mp="": use no postmarketOS mirrors (build everything locally)
    if args.mirrors_postmarketos == [""]:
        args.mirrors_postmarketos = []


def check_pmaports_path(args):
    """ Make sure that args.aports exists when it was overridden by --aports.
        Without this check, 'pmbootstrap init' would start cloning the
        pmaports into the default folder when args.aports does not exist. """
    if args.from_argparse.aports and not os.path.exists(args.aports):
        raise ValueError("pmaports path (specified with --aports) does"
                         " not exist: " + args.aports)


def replace_placeholders(args):
    """ Replace $WORK and ~ (for path variables) in variables from any config
        (user's config file, default config settings or config parameters
        specified on commandline) """

    # Replace $WORK
    for key, value in pmb.config.defaults.items():
        if key not in args:
            continue
        old = getattr(args, key)
        if isinstance(old, str):
            setattr(args, key, old.replace("$WORK", args.work))

    # Replace ~ (path variables only)
    for key in ["aports", "config", "log", "work"]:
        if key in args:
            setattr(args, key, os.path.expanduser(getattr(args, key)))


def add_deviceinfo(args):
    """ Add and verify the deviceinfo (only after initialization) """
    setattr(args, "deviceinfo", pmb.parse.deviceinfo(args))
    arch = args.deviceinfo["arch"]
    if (arch != pmb.config.arch_native and
            arch not in pmb.config.build_device_architectures):
        raise ValueError("Arch '" + arch + "' is not available in"
                         " postmarketOS. If you would like to add it, see:"
                         " <https://postmarketos.org/newarch>")


def init(args):
    # Basic initialization
    fix_mirrors_postmarketos(args)
    pmb.config.merge_with_args(args)
    replace_placeholders(args)
    pmb.helpers.other.init_cache()

    # Initialize logs (we could raise errors below)
    pmb.helpers.logging.init(args)

    # Initialization code which may raise errors
    check_pmaports_path(args)
    if args.action not in ["init", "checksum", "config", "bootimg_analyze", "log",
                           "pull", "shutdown", "zap"]:
        pmb.config.pmaports.read_config(args)
        add_deviceinfo(args)
        pmb.helpers.git.parse_channels_cfg(args)

    return args


def update_work(args, work):
    """ Update the work path in args.work and wherever $WORK was used. """
    # Start with the unmodified args from argparse
    args_new = copy.deepcopy(args.from_argparse)

    # Keep from the modified args:
    # * the unmodified args from argparse (to check if --aports was specified)
    args_new.from_argparse = args.from_argparse

    # Generate modified args again, replacing $WORK with the new work folder
    # When args.log is different, this also opens the log in the new location
    args_new.work = work
    args_new = pmb.helpers.args.init(args_new)

    # Overwrite old attributes of args with the new attributes
    for key in vars(args_new):
        setattr(args, key, getattr(args_new, key))
