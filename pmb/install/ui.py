# Copyright 2023 Dylan Van Assche
# SPDX-License-Identifier: GPL-3.0-or-later
import logging

import pmb.helpers.pmaports


def get_groups(args):
    """ Get all groups to which the user additionally must be added.
        The list of groups are listed in _pmb_groups of the UI and
        UI-extras package.

        :returns: list of groups, e.g. ["feedbackd", "udev"] """
    ret = []
    if args.ui == "none":
        return ret

    # UI package
    meta = f"postmarketos-ui-{args.ui}"
    apkbuild = pmb.helpers.pmaports.get(args, meta)
    groups = apkbuild["_pmb_groups"]
    if groups:
        logging.debug(f"{meta}: install _pmb_groups:"
                      f" {', '.join(groups)}")
        ret += groups

    # UI-extras subpackage
    meta_extras = f"{meta}-extras"
    if args.ui_extras and meta_extras in apkbuild["subpackages"]:
        groups = apkbuild["subpackages"][meta_extras]["_pmb_groups"]
        if groups:
            logging.debug(f"{meta_extras}: install _pmb_groups:"
                          f" {', '.join(groups)}")
            ret += groups

    return ret
