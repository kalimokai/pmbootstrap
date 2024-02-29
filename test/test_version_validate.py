# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import pmb_test  # noqa
import pmb.parse.version


def test_version_validate():
    func = pmb.parse.version.validate

    assert func("6.0_1") is False
    assert func("6.0_invalidsuffix1") is False
    assert func("6.0.0002") is True
    assert func("6.0.234") is True

    # Issue #1144
    assert func("6.0_0002") is False
