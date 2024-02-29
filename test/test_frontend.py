# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import sys
import pytest

import pmb_test  # noqa
import pmb.config
import pmb.parse
import pmb.helpers.frontend
import pmb.helpers.logging


def test_build_src_invalid_path():
    sys.argv = ["pmbootstrap.py", "build", "--src=/invalidpath", "hello-world"]
    args = pmb.parse.arguments()

    with pytest.raises(RuntimeError) as e:
        pmb.helpers.frontend.build(args)
    assert str(e.value).startswith("Invalid path specified for --src:")
