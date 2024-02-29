# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import pytest
import sys

import pmb_test  # noqa
import pmb.build.other


@pytest.fixture
def args(request):
    import pmb.parse
    sys.argv = ["pmbootstrap", "init"]
    args = pmb.parse.arguments()
    args.log = args.work + "/log_testsuite.txt"
    pmb.helpers.logging.init(args)
    request.addfinalizer(pmb.helpers.logging.logfd.close)
    return args


def test_filter_missing_packages_invalid(args):
    """ Test ...repo_missing.filter_missing_packages(): invalid package """
    func = pmb.helpers.repo_missing.filter_missing_packages
    with pytest.raises(RuntimeError) as e:
        func(args, "armhf", ["invalid-package-name"])
    assert str(e.value).startswith("Could not find aport")


def test_filter_missing_packages_binary_exists(args):
    """ Test ...repo_missing.filter_missing_packages(): binary exists """
    func = pmb.helpers.repo_missing.filter_missing_packages
    assert func(args, "armhf", ["busybox"]) == []


def test_filter_missing_packages_pmaports(args, monkeypatch):
    """ Test ...repo_missing.filter_missing_packages(): pmaports """
    build_is_necessary = None
    func = pmb.helpers.repo_missing.filter_missing_packages

    def stub(args, arch, pmaport):
        return build_is_necessary
    monkeypatch.setattr(pmb.build, "is_necessary", stub)

    build_is_necessary = True
    assert func(args, "x86_64", ["busybox", "hello-world"]) == ["hello-world"]

    build_is_necessary = False
    assert func(args, "x86_64", ["busybox", "hello-world"]) == []


def test_filter_aport_packages(args):
    """ Test ...repo_missing.filter_aport_packages() """
    func = pmb.helpers.repo_missing.filter_aport_packages
    assert func(args, "armhf", ["busybox", "hello-world"]) == ["hello-world"]


def test_filter_arch_packages(args, monkeypatch):
    """ Test ...repo_missing.filter_arch_packages() """
    func = pmb.helpers.repo_missing.filter_arch_packages
    check_arch = None

    def stub(args, arch, pmaport, binary=True):
        return check_arch
    monkeypatch.setattr(pmb.helpers.package, "check_arch", stub)

    check_arch = False
    assert func(args, "armhf", ["hello-world"]) == []

    check_arch = True
    assert func(args, "armhf", []) == []


def test_get_relevant_packages(args, monkeypatch):
    """ Test ...repo_missing.get_relevant_packages() """

    # Set up fake return values
    stub_data = {"check_arch": False,
                 "depends_recurse": ["a", "b", "c", "d"],
                 "filter_arch_packages": ["a", "b", "c"],
                 "filter_aport_packages": ["b", "a"],
                 "filter_missing_packages": ["a"]}

    def stub(args, arch, pmaport, binary=True):
        return stub_data["check_arch"]
    monkeypatch.setattr(pmb.helpers.package, "check_arch", stub)

    def stub(args, arch, pmaport):
        return stub_data["depends_recurse"]
    monkeypatch.setattr(pmb.helpers.package, "depends_recurse", stub)

    def stub(args, arch, pmaport):
        return stub_data["filter_arch_packages"]
    monkeypatch.setattr(pmb.helpers.repo_missing, "filter_arch_packages", stub)

    def stub(args, arch, pmaport):
        return stub_data["filter_aport_packages"]
    monkeypatch.setattr(pmb.helpers.repo_missing, "filter_aport_packages",
                        stub)

    def stub(args, arch, pmaport):
        return stub_data["filter_missing_packages"]
    monkeypatch.setattr(pmb.helpers.repo_missing, "filter_missing_packages",
                        stub)

    # No given package
    func = pmb.helpers.repo_missing.get_relevant_packages
    assert func(args, "armhf") == ["a"]
    assert func(args, "armhf", built=True) == ["a", "b"]

    # Package can't be built for given arch
    with pytest.raises(RuntimeError) as e:
        func(args, "armhf", "a")
    assert "can't be built" in str(e.value)

    # Package can be built for given arch
    stub_data["check_arch"] = True
    assert func(args, "armhf", "a") == ["a"]
    assert func(args, "armhf", "a", True) == ["a", "b"]


def test_generate_output_format(args, monkeypatch):
    """ Test ...repo_missing.generate_output_format() """

    def stub(args, pkgname, arch, replace_subpkgnames=False):
        return {"pkgname": "hello-world", "version": "1.0-r0",
                "depends": ["depend1", "depend2"]}
    monkeypatch.setattr(pmb.helpers.package, "get", stub)

    def stub(args, pkgname):
        return "main"
    monkeypatch.setattr(pmb.helpers.pmaports, "get_repo", stub)

    func = pmb.helpers.repo_missing.generate_output_format
    ret = [{"pkgname": "hello-world",
            "repo": "main",
            "version": "1.0-r0",
            "depends": ["depend1", "depend2"]}]
    assert func(args, "armhf", ["hello-world"]) == ret
