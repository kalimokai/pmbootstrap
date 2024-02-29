# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
""" Test pmb.helpers.repo """
import pytest
import sys

import pmb_test  # noqa
import pmb_test.const
import pmb.helpers.repo


@pytest.fixture
def args(tmpdir, request):
    import pmb.parse
    cfg = f"{pmb_test.const.testdata}/channels.cfg"
    sys.argv = ["pmbootstrap.py", "--config-channels", cfg, "chroot"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)
    return args


def test_hash():
    url = "https://nl.alpinelinux.org/alpine/edge/testing"
    hash = "865a153c"
    assert pmb.helpers.repo.hash(url, 8) == hash


def test_alpine_apkindex_path(args):
    func = pmb.helpers.repo.alpine_apkindex_path
    args.mirror_alpine = "http://dl-cdn.alpinelinux.org/alpine/"
    ret = args.work + "/cache_apk_armhf/APKINDEX.30e6f5af.tar.gz"
    assert func(args, "testing", "armhf") == ret


def test_urls(args, monkeypatch):
    func = pmb.helpers.repo.urls
    channel = "v20.05"
    args.mirror_alpine = "http://localhost/alpine/"

    # Second mirror with /master at the end is legacy, gets fixed by func.
    # Note that bpo uses multiple postmarketOS mirrors at the same time, so it
    # can use its WIP repository together with the final repository.
    args.mirrors_postmarketos = ["http://localhost/pmos1/",
                                 "http://localhost/pmos2/master"]

    # Pretend to have a certain channel in pmaports.cfg
    def read_config(args):
        return {"channel": channel}
    monkeypatch.setattr(pmb.config.pmaports, "read_config", read_config)

    # Channel: v20.05
    assert func(args) == ["/mnt/pmbootstrap/packages",
                          "http://localhost/pmos1/v20.05",
                          "http://localhost/pmos2/v20.05",
                          "http://localhost/alpine/v3.11/main",
                          "http://localhost/alpine/v3.11/community"]

    # Channel: edge (has Alpine's testing)
    channel = "edge"
    assert func(args) == ["/mnt/pmbootstrap/packages",
                          "http://localhost/pmos1/master",
                          "http://localhost/pmos2/master",
                          "http://localhost/alpine/edge/main",
                          "http://localhost/alpine/edge/community",
                          "http://localhost/alpine/edge/testing"]

    # Only Alpine's URLs
    exp = ["http://localhost/alpine/edge/main",
           "http://localhost/alpine/edge/community",
           "http://localhost/alpine/edge/testing"]
    assert func(args, False, False) == exp
