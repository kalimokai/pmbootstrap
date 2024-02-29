# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import copy
import sys
import tarfile
import glob
import pytest

import pmb_test  # noqa
import pmb.chroot.apk_static
import pmb.config
import pmb.parse.apkindex
import pmb.helpers.logging


@pytest.fixture
def args(request):
    import pmb.parse
    sys.argv = ["pmbootstrap.py", "chroot"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)
    return args


def test_read_signature_info(args):
    # Tempfolder inside chroot for fake apk files
    tmp_path = "/tmp/test_read_signature_info"
    tmp_path_outside = args.work + "/chroot_native" + tmp_path
    if os.path.exists(tmp_path_outside):
        pmb.chroot.root(args, ["rm", "-r", tmp_path])
    pmb.chroot.user(args, ["mkdir", "-p", tmp_path])

    # No signature found
    pmb.chroot.user(args, ["tar", "-czf", tmp_path + "/no_sig.apk",
                           "/etc/issue"])
    with tarfile.open(tmp_path_outside + "/no_sig.apk", "r:gz") as tar:
        with pytest.raises(RuntimeError) as e:
            pmb.chroot.apk_static.read_signature_info(tar)
        assert "Could not find signature" in str(e.value)

    # Signature file with invalid name
    pmb.chroot.user(args, ["mkdir", "-p", tmp_path + "/sbin"])
    pmb.chroot.user(args, ["cp", "/etc/issue", tmp_path +
                           "/sbin/apk.static.SIGN.RSA.invalid.pub"])
    pmb.chroot.user(args, ["tar", "-czf", tmp_path + "/invalid_sig.apk",
                           "sbin/apk.static.SIGN.RSA.invalid.pub"],
                    working_dir=tmp_path)
    with tarfile.open(tmp_path_outside + "/invalid_sig.apk", "r:gz") as tar:
        with pytest.raises(RuntimeError) as e:
            pmb.chroot.apk_static.read_signature_info(tar)
        assert "Invalid signature key" in str(e.value)

    # Signature file with realistic name
    path = glob.glob(pmb.config.apk_keys_path + "/*.pub")[0]
    name = os.path.basename(path)
    path_archive = "sbin/apk.static.SIGN.RSA." + name
    pmb.chroot.user(args, ["mv",
                           f"{tmp_path}/sbin/apk.static.SIGN.RSA.invalid.pub",
                           f"{tmp_path}/{path_archive}"])
    pmb.chroot.user(args, ["tar", "-czf", tmp_path + "/realistic_name_sig.apk",
                           path_archive], working_dir=tmp_path)
    with tarfile.open(f"{tmp_path_outside}/realistic_name_sig.apk", "r:gz")\
            as tar:
        sigfilename, sigkey_path = pmb.chroot.apk_static.read_signature_info(
            tar)
        assert sigfilename == path_archive
        assert sigkey_path == path

    # Clean up
    pmb.chroot.user(args, ["rm", "-r", tmp_path])


def test_successful_extraction(args, tmpdir):
    if os.path.exists(args.work + "/apk.static"):
        os.remove(args.work + "/apk.static")

    pmb.chroot.apk_static.init(args)
    assert os.path.exists(args.work + "/apk.static")
    os.remove(args.work + "/apk.static")


def test_signature_verification(args, tmpdir):
    if os.path.exists(args.work + "/apk.static"):
        os.remove(args.work + "/apk.static")

    version = pmb.parse.apkindex.package(args, "apk-tools-static")["version"]
    apk_path = pmb.chroot.apk_static.download(
        args, f"apk-tools-static-{version}.apk")

    # Extract to temporary folder
    with tarfile.open(apk_path, "r:gz") as tar:
        sigfilename, sigkey_path = pmb.chroot.apk_static.read_signature_info(
            tar)
        files = pmb.chroot.apk_static.extract_temp(tar, sigfilename)

    # Verify signature (successful)
    pmb.chroot.apk_static.verify_signature(args, files, sigkey_path)

    # Append data to extracted apk.static
    with open(files["apk"]["temp_path"], "ab") as handle:
        handle.write("appended something".encode())

    # Verify signature again (fail) (this deletes the tempfiles)
    with pytest.raises(RuntimeError) as e:
        pmb.chroot.apk_static.verify_signature(args, files, sigkey_path)
    assert "Failed to validate signature" in str(e.value)

    #
    # Test "apk.static --version" check
    #
    with pytest.raises(RuntimeError) as e:
        pmb.chroot.apk_static.extract(args, "99.1.2-r1", apk_path)
    assert "downgrade attack" in str(e.value)


def test_outdated_version(args, monkeypatch):
    if os.path.exists(args.work + "/apk.static"):
        os.remove(args.work + "/apk.static")

    # Change min version for all branches
    min_copy = copy.copy(pmb.config.apk_tools_min_version)
    for key, old_ver in min_copy.items():
        min_copy[key] = "99.1.2-r1"
    monkeypatch.setattr(pmb.config, "apk_tools_min_version", min_copy)

    with pytest.raises(RuntimeError) as e:
        pmb.chroot.apk_static.init(args)
    assert "outdated version" in str(e.value)
