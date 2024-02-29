# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import configparser
import os
import pmb.config


def load(args):
    cfg = configparser.ConfigParser()
    if os.path.isfile(args.config):
        cfg.read(args.config)

    if "pmbootstrap" not in cfg:
        cfg["pmbootstrap"] = {}
    if "providers" not in cfg:
        cfg["providers"] = {}

    for key in pmb.config.defaults:
        if key in pmb.config.config_keys and key not in cfg["pmbootstrap"]:
            cfg["pmbootstrap"][key] = str(pmb.config.defaults[key])

        # We used to save default values in the config, which can *not* be
        # configured in "pmbootstrap init". That doesn't make sense, we always
        # want to use the defaults from pmb/config/__init__.py in that case,
        # not some outdated version we saved some time back (eg. aports folder,
        # postmarketOS binary packages mirror).
        if key not in pmb.config.config_keys and key in cfg["pmbootstrap"]:
            logging.debug("Ignored unconfigurable and possibly outdated"
                          " default value from config:"
                          f" {cfg['pmbootstrap'][key]}")
            del cfg["pmbootstrap"][key]

    return cfg
