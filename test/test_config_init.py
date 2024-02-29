# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import pytest

import pmb_test  # noqa
import pmb.config.init


def test_require_programs(monkeypatch):
    func = pmb.config.init.require_programs

    # Nothing missing
    func()

    # Missing program
    invalid = "invalid-program-name-here-asdf"
    monkeypatch.setattr(pmb.config, "required_programs", [invalid])
    with pytest.raises(RuntimeError) as e:
        func()
    assert str(e.value).startswith("Can't find all programs")
