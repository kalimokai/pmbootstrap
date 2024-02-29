# SPDX-License-Identifier: GPL-3.0-or-later

import argparse

import pytest

from pmb.parse.arguments import toggle_other_boolean_flags


@pytest.fixture
def example_cli_with_flags():
    parser = argparse.ArgumentParser(prog="sample cli")
    parser.add_argument("-f1", "--flag1", action="store_true")
    parser.add_argument("-f2", "--flag2", action="store_true")
    return parser


def test_toggle_other_boolean_flags(example_cli_with_flags):
    other_flags = ["flag1", "flag2"]
    example_cli_with_flags.add_argument(
        "-f12", "--flag12",
        action=toggle_other_boolean_flags(*other_flags))
    args = example_cli_with_flags.parse_args(['-f12'])

    expected_flags_true = other_flags + ["flag12"]
    for flag in expected_flags_true:
        assert getattr(args, flag)
