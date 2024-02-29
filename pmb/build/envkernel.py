# Copyright 2023 Robert Yang
# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import os
import re

import pmb.aportgen
import pmb.build
import pmb.chroot
import pmb.helpers
import pmb.helpers.pmaports
import pmb.parse


def match_kbuild_out(word):
    """
    Look for paths in the following formats:
      "<prefix>/<kbuild_out>/arch/<arch>/boot"
      "<prefix>/<kbuild_out>/include/config/kernel.release"

    :param word: space separated string cut out from a line from an APKBUILD
                 function body that might be the kbuild output path
    :returns: kernel build output directory.
              empty string when a separate build output directory isn't used.
              None, when no output directory is found.
    """
    prefix = "^\\\"?\\$({?builddir}?|{?srcdir}?)\\\"?/"
    kbuild_out = "(.*\\/)*"

    postfix = "(arch\\/.*\\/boot.*)\\\"?$"
    match = re.match(prefix + kbuild_out + postfix, word)

    if match is None:
        postfix = "(include\\/config\\/kernel\\.release)\\\"?$"
        match = re.match(prefix + kbuild_out + postfix, word)

    if match is None:
        return None

    groups = match.groups()
    if groups is None or len(groups) != 3:
        return None

    logging.debug("word = " + str(word))
    logging.debug("regex match groups = " + str(groups))
    out_dir = groups[1]
    return "" if out_dir is None else out_dir.strip("/")


def find_kbuild_output_dir(function_body):
    """
    Guess what the kernel build output directory is. Parses each line of the
    function word by word, looking for paths which contain the kbuild output
    directory.

    :param function_body: contents of a function from the kernel APKBUILD
    :returns: kbuild output dir
              None, when output dir is not found
    """

    guesses = []
    for line in function_body:
        for item in line.split():
            # Guess that any APKBUILD using downstreamkernel_package
            # uses the default kbuild out directory.
            if item == "downstreamkernel_package":
                guesses.append("")
                break
            kbuild_out = match_kbuild_out(item)
            if kbuild_out is not None:
                guesses.append(kbuild_out)
                break

    # Check if guesses are all the same
    it = iter(guesses)
    first = next(it, None)
    if first is None:
        raise RuntimeError("Couldn't find a kbuild out directory. Is your "
                           "APKBUILD messed up? If not, then consider "
                           "adjusting the patterns in pmb/build/envkernel.py "
                           "to work with your APKBUILD, or submit an issue.")
    if all(first == rest for rest in it):
        return first
    raise RuntimeError("Multiple kbuild out directories found. Can you modify "
                       "your APKBUILD so it only has one output path? If you "
                       "can't resolve it, please open an issue.")


def modify_apkbuild(args, pkgname, aport):
    """
    Modify kernel APKBUILD to package build output from envkernel.sh
    """
    apkbuild_path = aport + "/APKBUILD"
    apkbuild = pmb.parse.apkbuild(apkbuild_path)
    if os.path.exists(args.work + "/aportgen"):
        pmb.helpers.run.user(args, ["rm", "-r", args.work + "/aportgen"])

    pmb.helpers.run.user(args, ["mkdir", args.work + "/aportgen"])
    pmb.helpers.run.user(args, ["cp", "-r", apkbuild_path,
                         args.work + "/aportgen"])

    pkgver = pmb.build._package.get_pkgver(apkbuild["pkgver"],
                                           original_source=False)
    fields = {"pkgver": pkgver,
              "pkgrel": "0",
              "subpackages": "",
              "builddir": "/home/pmos/build/src"}

    pmb.aportgen.core.rewrite(args, pkgname, apkbuild_path, fields=fields)


def run_abuild(args, pkgname, arch, apkbuild_path, kbuild_out):
    """
    Prepare build environment and run abuild.

    :param pkgname: package name of a linux kernel aport
    :param arch: architecture for the kernel
    :param apkbuild_path: path to APKBUILD of the kernel aport
    :param kbuild_out: kernel build system output sub-directory
    """
    chroot = args.work + "/chroot_native"
    build_path = "/home/pmos/build"
    kbuild_out_source = "/mnt/linux/.output"

    # If the kernel was cross-compiled on the host rather than with the envkernel
    # helper, we can still use the envkernel logic to package the artifacts for
    # development, making it easy to quickly sideload a new kernel or pmbootstrap
    # to create a boot image.

    pmb.helpers.mount.bind(args, ".", f"{chroot}/mnt/linux")

    if not os.path.exists(chroot + kbuild_out_source):
        raise RuntimeError("No '.output' dir found in your kernel source dir. "
                           "Compile the " + args.device + " kernel first and "
                           "then try again. See https://postmarketos.org/envkernel"
                           "for details. If building on your host and only using "
                           "--envkernel for packaging, make sure you have O=.output "
                           "as an argument to make.")

    # Create working directory for abuild
    pmb.build.copy_to_buildpath(args, pkgname)

    # Create symlink from abuild working directory to envkernel build directory
    build_output = "" if kbuild_out == "" else "/" + kbuild_out
    if build_output != "":
        if os.path.islink(chroot + "/mnt/linux/" + build_output) and \
                os.path.lexists(chroot + "/mnt/linux/" + build_output):
            pmb.chroot.root(args, ["rm", "/mnt/linux/" + build_output])
        pmb.chroot.root(args, ["ln", "-s", "/mnt/linux",
                        build_path + "/src"])
    pmb.chroot.root(args, ["ln", "-s", kbuild_out_source,
                    build_path + "/src" + build_output])

    cmd = ["cp", apkbuild_path, chroot + build_path + "/APKBUILD"]
    pmb.helpers.run.root(args, cmd)

    # Create the apk package
    env = {"CARCH": arch,
           "CHOST": arch,
           "CBUILD": pmb.config.arch_native,
           "SUDO_APK": "abuild-apk --no-progress"}
    cmd = ["abuild", "rootpkg"]
    pmb.chroot.user(args, cmd, working_dir=build_path, env=env)

    # Clean up bindmount
    pmb.helpers.mount.umount_all(args, f"{chroot}/mnt/linux")

    # Clean up symlinks
    if build_output != "":
        if os.path.islink(chroot + "/mnt/linux/" + build_output) and \
                os.path.lexists(chroot + "/mnt/linux/" + build_output):
            pmb.chroot.root(args, ["rm", "/mnt/linux/" + build_output])
    pmb.chroot.root(args, ["rm", build_path + "/src"])


def package_kernel(args):
    """
    Frontend for 'pmbootstrap build --envkernel': creates a package from
    envkernel output.
    """
    pkgname = args.packages[0]
    if len(args.packages) > 1 or not pkgname.startswith("linux-"):
        raise RuntimeError("--envkernel needs exactly one linux-* package as "
                           "argument.")

    aport = pmb.helpers.pmaports.find(args, pkgname)

    modify_apkbuild(args, pkgname, aport)
    apkbuild_path = args.work + "/aportgen/APKBUILD"

    arch = args.deviceinfo["arch"]
    apkbuild = pmb.parse.apkbuild(apkbuild_path, check_pkgname=False)
    if apkbuild["_outdir"]:
        kbuild_out = apkbuild["_outdir"]
    else:
        function_body = pmb.parse.function_body(aport + "/APKBUILD", "package")
        kbuild_out = find_kbuild_output_dir(function_body)
    suffix = pmb.build.autodetect.suffix(apkbuild, arch)

    # Install package dependencies
    depends, _ = pmb.build._package.build_depends(
        args, apkbuild, pmb.config.arch_native, strict=False)
    pmb.build.init(args, suffix)
    if pmb.parse.arch.cpu_emulation_required(arch):
        depends.append("binutils-" + arch)
    pmb.chroot.apk.install(args, depends, suffix)

    output = (arch + "/" + apkbuild["pkgname"] + "-" + apkbuild["pkgver"] +
              "-r" + apkbuild["pkgrel"] + ".apk")
    message = "(" + suffix + ") build " + output
    logging.info(message)

    try:
        run_abuild(args, pkgname, arch, apkbuild_path, kbuild_out)
    except Exception as e:
        pmb.helpers.mount.umount_all(args, f"{args.work}/chroot_native/mnt/linux")
        raise e
    pmb.build.other.index_repo(args, arch)
