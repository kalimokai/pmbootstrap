# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import sys
import time
import pytest

import pmb_test  # noqa
import pmb.helpers.git
import pmb.helpers.logging
import pmb.parse.version


@pytest.fixture
def args(request):
    import pmb.parse
    sys.argv = ["pmbootstrap.py", "chroot"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)
    return args


def test_file_is_older_than(args, tmpdir):
    # Create a file last modified 10s ago
    tempfile = str(tmpdir) + "/test"
    pmb.helpers.run.user(args, ["touch", tempfile])
    past = time.time() - 10
    os.utime(tempfile, (-1, past))

    # Check the bounds
    func = pmb.helpers.file.is_older_than
    assert func(tempfile, 9) is True
    assert func(tempfile, 10) is True
    assert func(tempfile, 11) is False
