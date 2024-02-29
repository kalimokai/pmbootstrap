#!/usr/bin/env python3
# -*- encoding: UTF-8 -*-
# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
# PYTHON_ARGCOMPLETE_OK
import sys
import pmb

# A convenience wrapper for running pmbootstrap from the git repository. This
# script is not part of the python packaging, so don't add more logic here!
if __name__ == "__main__":
    sys.exit(pmb.main())
