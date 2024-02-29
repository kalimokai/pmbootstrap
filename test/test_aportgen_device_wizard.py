# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import pytest
import sys
import shutil

import pmb_test  # noqa
import pmb_test.git
import pmb_test.const
import pmb.aportgen
import pmb.config
import pmb.helpers.logging
import pmb.parse


@pytest.fixture
def args(tmpdir, request):
    cfg = f"{pmb_test.const.testdata}/channels.cfg"
    sys.argv = ["pmbootstrap.py", "--config-channels", cfg, "build", "-i",
                "device-testsuite-testdevice"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)

    # Fake aports folder:
    tmpdir = str(tmpdir)
    pmb_test.git.copy_dotgit(args, tmpdir)
    setattr(args, "_aports_real", args.aports)
    args.aports = tmpdir

    # Copy the devicepkg-dev package (shared device-* APKBUILD code)
    pmb.helpers.run.user(args, ["mkdir", "-p", tmpdir + "/main"])
    path_dev = args._aports_real + "/main/devicepkg-dev"
    pmb.helpers.run.user(args, ["cp", "-r", path_dev, tmpdir + "/main"])

    # Copy the linux-lg-mako aport (we currently copy patches from there)
    pmb.helpers.run.user(args, ["mkdir", "-p", tmpdir + "/device/testing"])
    path_mako = args._aports_real + "/device/testing/linux-lg-mako"
    pmb.helpers.run.user(args, ["cp", "-r", path_mako,
                                f"{tmpdir}/device/testing"])

    # Copy pmaports.cfg
    shutil.copy(f"{pmb_test.const.testdata}/pmaports.cfg", args.aports)
    return args


def generate(args, monkeypatch, answers):
    """
    Generate the device-new-device and linux-new-device aports (with a patched
    pmb.helpers.cli()).

    :returns: (deviceinfo, apkbuild, apkbuild_linux) - the parsed dictionaries
              of the created files, as returned by pmb.parse.apkbuild() and
              pmb.parse.deviceinfo().
    """
    # Patched function
    def fake_ask(question="Continue?", choices=["y", "n"], default="n",
                 lowercase_answer=True, validation_regex=None, complete=None):
        for substr, answer in answers.items():
            if substr in question:
                logging.info(question + ": " + answer)
                # raise RuntimeError("test>" + answer)
                return answer
        raise RuntimeError("This testcase didn't expect the question '" +
                           question + "', please add it to the mapping.")

    # Generate the aports
    monkeypatch.setattr(pmb.helpers.cli, "ask", fake_ask)
    pmb.aportgen.generate(args, "device-testsuite-testdevice")
    pmb.aportgen.generate(args, "linux-testsuite-testdevice")
    monkeypatch.undo()

    apkbuild_path = (f"{args.aports}/device/testing/"
                     "device-testsuite-testdevice/APKBUILD")
    apkbuild_path_linux = (args.aports + "/device/testing/"
                           "linux-testsuite-testdevice/APKBUILD")

    # The build fails if the email is not a valid email, so remove them just
    # for tests
    remove_contributor_maintainer_lines(args, apkbuild_path)
    remove_contributor_maintainer_lines(args, apkbuild_path_linux)

    # Parse the deviceinfo and apkbuilds
    pmb.helpers.other.cache["apkbuild"] = {}
    apkbuild = pmb.parse.apkbuild(apkbuild_path)
    apkbuild_linux = pmb.parse.apkbuild(apkbuild_path_linux,
                                        check_pkgver=False)
    deviceinfo = pmb.parse.deviceinfo(args, "testsuite-testdevice")
    return (deviceinfo, apkbuild, apkbuild_linux)


def remove_contributor_maintainer_lines(args, path):
    with open(path, "r+", encoding="utf-8") as handle:
        lines_new = []
        for line in handle.readlines():
            # Skip maintainer/contributor
            if line.startswith("# Maintainer") or line.startswith(
                    "# Contributor"):
                continue
            lines_new.append(line)
        # Write back
        handle.seek(0)
        handle.write("".join(lines_new))
        handle.truncate()


def test_aportgen_device_wizard(args, monkeypatch):
    """
    Generate a device-testsuite-testdevice and linux-testsuite-testdevice
    package multiple times and check if the output is correct. Also build the
    device package once.
    """
    # Answers to interactive questions
    answers = {
        "Device architecture": "armv7",
        "external storage": "y",
        "hardware keyboard": "n",
        "Flash method": "heimdall",
        "Manufacturer": "Testsuite",
        "Name": "Testsuite Testdevice",
        "Year": "1337",
        "Chassis": "handset",
        "Type": "isorec",
    }

    # First run
    deviceinfo, apkbuild, apkbuild_linux = generate(args, monkeypatch, answers)
    assert apkbuild["pkgname"] == "device-testsuite-testdevice"
    assert apkbuild["pkgdesc"] == "Testsuite Testdevice"
    assert apkbuild["depends"] == ["linux-testsuite-testdevice",
                                   "postmarketos-base"]

    assert apkbuild_linux["pkgname"] == "linux-testsuite-testdevice"
    assert apkbuild_linux["pkgdesc"] == "Testsuite Testdevice kernel fork"
    assert apkbuild_linux["arch"] == ["armv7"]
    assert apkbuild_linux["_flavor"] == "testsuite-testdevice"

    assert deviceinfo["name"] == "Testsuite Testdevice"
    assert deviceinfo["manufacturer"] == answers["Manufacturer"]
    assert deviceinfo["arch"] == "armv7"
    assert deviceinfo["year"] == "1337"
    assert deviceinfo["chassis"] == "handset"
    assert deviceinfo["keyboard"] == "false"
    assert deviceinfo["external_storage"] == "true"
    assert deviceinfo["flash_method"] == "heimdall-isorec"
    assert deviceinfo["generate_bootimg"] == ""
    assert deviceinfo["generate_legacy_uboot_initfs"] == ""

    # Build the device package
    pkgname = "device-testsuite-testdevice"
    pmb.build.checksum.update(args, pkgname)
    pmb.build.package(args, pkgname, "armv7", force=True)

    # Abort on overwrite confirmation
    answers["overwrite"] = "n"
    with pytest.raises(RuntimeError) as e:
        deviceinfo, apkbuild, apkbuild_linux = generate(args, monkeypatch,
                                                        answers)
    assert "Aborted." in str(e.value)

    # fastboot (mkbootimg)
    answers["overwrite"] = "y"
    answers["Flash method"] = "fastboot"
    answers["Path"] = ""
    deviceinfo, apkbuild, apkbuild_linux = generate(args, monkeypatch, answers)
    assert apkbuild["depends"] == ["linux-testsuite-testdevice",
                                   "mkbootimg",
                                   "postmarketos-base"]

    assert deviceinfo["flash_method"] == answers["Flash method"]
    assert deviceinfo["generate_bootimg"] == "true"

    # 0xffff (legacy uboot initfs)
    answers["Flash method"] = "0xffff"
    deviceinfo, apkbuild, apkbuild_linux = generate(args, monkeypatch, answers)
    assert apkbuild["depends"] == ["linux-testsuite-testdevice",
                                   "postmarketos-base",
                                   "uboot-tools"]

    assert deviceinfo["generate_legacy_uboot_initfs"] == "true"
