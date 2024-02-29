# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import os
import pytest
import sys

import pmb_test
import pmb_test.const
import pmb.aportgen.device
import pmb.config
import pmb.config.init
import pmb.helpers.logging
import pmb.parse.deviceinfo


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


def fake_answers(monkeypatch, answers):
    """
    Patch pmb.helpers.cli.ask() function to return defined answers instead of
    asking the user for an answer.

    :param answers: list of answer strings, e.g. ["y", "n", "invalid-device"].
                    In this example, the first question is answered with "y",
                    the second question with "n" and so on.
    """
    def fake_ask(question="Continue?", choices=["y", "n"], default="n",
                 lowercase_answer=True, validation_regex=None, complete=None):
        answer = answers.pop(0)
        logging.info("pmb.helpers.cli.ask() fake answer: " + answer)
        return answer
    monkeypatch.setattr(pmb.helpers.cli, "ask", fake_ask)


def test_fake_answers_selftest(monkeypatch):
    fake_answers(monkeypatch, ["first", "second"])
    assert pmb.helpers.cli.ask() == "first"
    assert pmb.helpers.cli.ask() == "second"


def test_questions_booleans(args, monkeypatch):
    functions = [pmb.aportgen.device.ask_for_keyboard,
                 pmb.aportgen.device.ask_for_external_storage]
    for func in functions:
        fake_answers(monkeypatch, ["y", "n"])
        assert func(args) is True
        assert func(args) is False


def test_questions_strings(args, monkeypatch):
    functions = [pmb.aportgen.device.ask_for_manufacturer]
    for func in functions:
        fake_answers(monkeypatch, ["Simple string answer"])
        assert func() == "Simple string answer"


def test_questions_name(args, monkeypatch):
    func = pmb.aportgen.device.ask_for_name

    # Manufacturer should get added automatically, but not twice
    fake_answers(monkeypatch, ["Amazon Thor"])
    assert func("Amazon") == "Amazon Thor"
    fake_answers(monkeypatch, ["Thor"])
    assert func("Amazon") == "Amazon Thor"

    # Don't add the manufacturer when it starts with "Google"
    fake_answers(monkeypatch, ["Google Nexus 12345"])
    assert func("Amazon") == "Google Nexus 12345"


def test_questions_arch(args, monkeypatch):
    fake_answers(monkeypatch, ["invalid_arch", "aarch64"])
    assert pmb.aportgen.device.ask_for_architecture() == "aarch64"


def test_questions_bootimg(args, monkeypatch):
    func = pmb.aportgen.device.ask_for_bootimg
    fake_answers(monkeypatch, ["invalid_path", ""])
    assert func(args) is None

    bootimg_path = pmb_test.const.testdata + "/bootimg/normal-boot.img"
    fake_answers(monkeypatch, [bootimg_path])
    output = {"header_version": "0",
              "base": "0x80000000",
              "kernel_offset": "0x00008000",
              "ramdisk_offset": "0x04000000",
              "second_offset": "0x00f00000",
              "tags_offset": "0x0e000000",
              "pagesize": "2048",
              "cmdline": "bootopt=64S3,32S1,32S1",
              "qcdt": "false",
              "dtb_second": "false"}
    assert func(args) == output


def test_questions_device(args, monkeypatch):
    # Prepare args
    args.aports = pmb_test.const.testdata + "/init_questions_device/aports"
    args.device = "lg-mako"
    args.kernel = "downstream"

    # Do not generate aports
    def fake_generate(args, pkgname):
        return
    monkeypatch.setattr(pmb.aportgen, "generate", fake_generate)

    # Existing device (without non-free components so we have defaults there)
    func = pmb.config.init.ask_for_device
    fake_answers(monkeypatch, ["lg", "mako"])
    kernel = args.kernel
    assert func(args) == ("lg-mako", True, kernel)

    # Non-existing vendor, go back, existing vendor+device
    fake_answers(monkeypatch, ["whoops", "n", "lg", "mako"])
    assert func(args) == ("lg-mako", True, kernel)

    # Existing vendor, new device, go back, existing vendor+device
    fake_answers(monkeypatch, ["lg", "nonexistent", "n", "lg", "mako"])
    assert func(args) == ("lg-mako", True, kernel)

    # New vendor and new device (new port)
    fake_answers(monkeypatch, ["new", "y", "device", "y"])
    assert func(args) == ("new-device", False, kernel)

    # Existing vendor, new device (new port)
    fake_answers(monkeypatch, ["lg", "nonexistent", "y"])
    assert func(args) == ("lg-nonexistent", False, kernel)


def test_questions_device_kernel(args, monkeypatch):
    # Prepare args
    args.aports = pmb_test.const.testdata + "/init_questions_device/aports"
    args.kernel = "downstream"

    # Kernel hardcoded in depends
    func = pmb.config.init.ask_for_device_kernel
    device = "lg-mako"
    assert func(args, device) == args.kernel

    # Choose "mainline"
    device = "sony-amami"
    fake_answers(monkeypatch, ["mainline"])
    assert func(args, device) == "mainline"

    # Choose "downstream"
    fake_answers(monkeypatch, ["downstream"])
    assert func(args, device) == "downstream"


def test_questions_flash_methods(args, monkeypatch):
    func = pmb.aportgen.device.ask_for_flash_method
    fake_answers(monkeypatch, ["invalid_flash_method", "fastboot"])
    assert func() == "fastboot"

    fake_answers(monkeypatch, ["0xffff"])
    assert func() == "0xffff"

    fake_answers(monkeypatch, ["heimdall", "invalid_type", "isorec"])
    assert func() == "heimdall-isorec"

    fake_answers(monkeypatch, ["heimdall", "bootimg"])
    assert func() == "heimdall-bootimg"


def test_questions_keymaps(args, monkeypatch):
    func = pmb.config.init.ask_for_keymaps
    fake_answers(monkeypatch, ["invalid_keymap", "us/rx51_us"])
    assert func(args, pmb.parse.deviceinfo(args, "nokia-n900")) == "us/rx51_us"
    assert func(args, pmb.parse.deviceinfo(args, "lg-mako")) == ""


def test_questions_ui(args, monkeypatch):
    args.aports = pmb_test.const.testdata + "/init_questions_device/aports"
    device = "lg-mako"
    info = pmb.parse.deviceinfo(args, device)

    fake_answers(monkeypatch, ["none"])
    assert pmb.config.init.ask_for_ui(args, info) == "none"

    fake_answers(monkeypatch, ["invalid_UI", "weston"])
    assert pmb.config.init.ask_for_ui(args, info) == "weston"


def test_questions_ui_extras(args, monkeypatch):
    args.aports = pmb_test.const.testdata + "/init_questions_device/aports"
    assert not pmb.config.init.ask_for_ui_extras(args, "none")

    fake_answers(monkeypatch, ["n"])
    assert not pmb.config.init.ask_for_ui_extras(args, "weston")

    fake_answers(monkeypatch, ["y"])
    assert pmb.config.init.ask_for_ui_extras(args, "weston")


def test_questions_work_path(args, monkeypatch, tmpdir):
    # Existing paths (triggering various errors)
    func = pmb.config.init.ask_for_work_path
    tmpdir = str(tmpdir)
    fake_answers(monkeypatch, ["/dev/null", os.path.dirname(__file__),
                               pmb.config.pmb_src, tmpdir])
    assert func(args) == (tmpdir, True)

    # Non-existing path
    work = tmpdir + "/non_existing_subfolder"
    fake_answers(monkeypatch, [work])
    assert func(args) == (work, False)


def test_questions_additional_options(args, monkeypatch):
    func = pmb.config.init.ask_for_additional_options
    cfg = {"pmbootstrap": {}}

    # Skip changing anything
    fake_answers(monkeypatch, ["n"])
    func(args, cfg)
    assert cfg == {"pmbootstrap": {}}

    # Answer everything
    fake_answers(monkeypatch, ["y", "128", "64", "5", "2G", "n", "y", "1",
                               "n"])
    func(args, cfg)
    mirror = pmb.config.defaults["mirrors_postmarketos"]
    assert cfg == {"pmbootstrap": {"extra_space": "128",
                                   "boot_size": "64",
                                   "jobs": "5",
                                   "ccache_size": "2G",
                                   "sudo_timer": "False",
                                   "mirrors_postmarketos": mirror}}


def test_questions_hostname(args, monkeypatch):
    func = pmb.config.init.ask_for_hostname
    device = "test-device"

    # Valid hostname
    fake_answers(monkeypatch, ["valid"])
    assert func(args, device) == "valid"

    # Hostname too long ("aaaaa...")
    fake_answers(monkeypatch, ["a" * 64, "a" * 63])
    assert func(args, device) == "a" * 63

    # Fail the regex
    fake_answers(monkeypatch, ["$invalid", "valid"])
    assert func(args, device) == "valid"

    # Begins or ends with minus
    fake_answers(monkeypatch, ["-invalid", "invalid-", "valid"])
    assert func(args, device) == "valid"

    # Device name: empty string
    fake_answers(monkeypatch, [device])
    assert func(args, device) == ""


def test_questions_channel(args, monkeypatch):
    fake_answers(monkeypatch, ["invalid-channel", "v20.05"])
    assert pmb.config.init.ask_for_channel(args) == "v20.05"
