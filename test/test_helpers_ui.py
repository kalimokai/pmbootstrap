# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import pytest
import sys

import pmb_test
import pmb_test.const
import pmb.helpers.logging
import pmb.helpers.ui


@pytest.fixture
def args(tmpdir, request):
    import pmb.parse
    cfg = f"{pmb_test.const.testdata}/channels.cfg"
    sys.argv = ["pmbootstrap.py", "--config-channels", cfg, "init"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)
    return args


def test_helpers_ui(args):
    """ Test the UIs returned by pmb.helpers.ui.list() with a testdata pmaports
        dir. That test dir has a plasma-mobile UI, which is disabled for armhf,
        so it must not be returned when querying the UI list for armhf. """
    args.aports = f"{pmb_test.const.testdata}/helpers_ui/pmaports"
    func = pmb.helpers.ui.list
    none_desc = "Bare minimum OS image for testing and manual" \
                " customization. The \"console\" UI should be selected if" \
                " a graphical UI is not desired."
    assert func(args, "armhf") == [("none", none_desc)]
    assert func(args, "x86_64") == [("none", none_desc),
                                    ("plasma-mobile", "cool pkgdesc")]
