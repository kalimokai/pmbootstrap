# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import sys
import pytest

import pmb_test
import pmb_test.const
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


def test_version(args):
    # Fail after the first error or print a grand total of failures
    keep_going = False

    # Iterate over the version tests from apk-tools
    path = pmb_test.const.testdata + "/version/version.data"
    mapping = {-1: "<", 0: "=", 1: ">"}
    count = 0
    errors = []
    with open(path) as handle:
        for line in handle:
            split = line.split(" ")
            a = split[0]
            b = split[2].split("#")[0].rstrip()
            expected = split[1]
            print("(#" + str(count) + ") " + line.rstrip())
            result = pmb.parse.version.compare(a, b)
            real = mapping[result]

            count += 1
            if real != expected:
                if keep_going:
                    errors.append(line.rstrip() + " (got: '" + real + "')")
                else:
                    assert real == expected

    print("---")
    print("total: " + str(count))
    print("errors: " + str(len(errors)))
    print("---")
    for error in errors:
        print(error)
    assert errors == []


def test_version_check_string():
    func = pmb.parse.version.check_string
    assert func("3.2.4", ">=0.0.0") is True
    assert func("3.2.4", ">=3.2.4") is True
    assert func("3.2.4", "<4.0.0") is True

    assert func("0.0.0", ">=0.0.1") is False
    assert func("4.0.0", "<4.0.0") is False
    assert func("4.0.1", "<4.0.0") is False

    assert func("5.2.0_rc3", "<5.2.0") is False
    assert func("5.2.0_rc3", ">=5.2.0") is True
