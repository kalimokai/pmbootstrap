# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import sys
import pytest

import pmb_test  # noqa
import pmb.helpers.logging
import pmb.helpers.other
import pmb.helpers.run


@pytest.fixture
def args(request):
    import pmb.parse
    sys.argv = ["pmbootstrap.py", "chroot"]
    args = pmb.parse.arguments()
    args.details_to_stdout = True
    pmb.helpers.logging.init(args)
    return args


def test_get_folder_size(args, tmpdir):
    # Write five 200 KB files to tmpdir
    tmpdir = str(tmpdir)
    files = 5
    for i in range(files):
        pmb.helpers.run.user(args, ["dd", "if=/dev/zero", "of=" +
                                    tmpdir + "/" + str(i), "bs=1K",
                                    "count=200", "conv=notrunc"])

    # Check if the size is correct. Unfortunately, the `du` call
    # in pmb.helpers.other.folder_size is not very accurate, so we
    # allow 30kb of tolerance (good enough for our use case): #760 #1717
    tolerance = 30
    size = 200 * files
    result = pmb.helpers.other.folder_size(args, tmpdir)
    assert (result < size + tolerance and result > size - tolerance)
