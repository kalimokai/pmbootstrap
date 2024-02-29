# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import glob
import json
import logging
import os
import sys

import pmb.aportgen
import pmb.build
import pmb.build.autodetect
import pmb.chroot
import pmb.chroot.initfs
import pmb.chroot.other
import pmb.ci
import pmb.config
import pmb.export
import pmb.flasher
import pmb.helpers.aportupgrade
import pmb.helpers.devices
import pmb.helpers.git
import pmb.helpers.lint
import pmb.helpers.logging
import pmb.helpers.pkgrel_bump
import pmb.helpers.pmaports
import pmb.helpers.repo
import pmb.helpers.repo_missing
import pmb.helpers.run
import pmb.helpers.status
import pmb.install
import pmb.install.blockdevice
import pmb.netboot
import pmb.parse
import pmb.qemu
import pmb.sideload


def _parse_flavor(args, autoinstall=True):
    """
    Verify the flavor argument if specified, or return a default value.
    :param autoinstall: make sure that at least one kernel flavor is installed
    """
    # Install a kernel and get its "flavor", where flavor is a pmOS-specific
    # identifier that is typically in the form
    # "postmarketos-<manufacturer>-<device/chip>", e.g.
    # "postmarketos-qcom-sdm845"
    suffix = "rootfs_" + args.device
    flavor = pmb.chroot.other.kernel_flavor_installed(
        args, suffix, autoinstall)

    if not flavor:
        raise RuntimeError(
            "No kernel flavors installed in chroot " + suffix + "! Please let"
            " your device package depend on a package starting with 'linux-'.")
    return flavor


def _parse_suffix(args):
    if "rootfs" in args and args.rootfs:
        return "rootfs_" + args.device
    elif args.buildroot:
        if args.buildroot == "device":
            return "buildroot_" + args.deviceinfo["arch"]
        else:
            return "buildroot_" + args.buildroot
    elif args.suffix:
        return args.suffix
    else:
        return "native"


def _install_ondev_verify_no_rootfs(args):
    chroot_dest = "/var/lib/rootfs.img"
    dest = f"{args.work}/chroot_installer_{args.device}{chroot_dest}"
    if os.path.exists(dest):
        return

    if args.ondev_cp:
        for _, chroot_dest_cp in args.ondev_cp:
            if chroot_dest_cp == chroot_dest:
                return

    raise ValueError(f"--no-rootfs set, but rootfs.img not found in install"
                     " chroot. Either run 'pmbootstrap install' without"
                     " --no-rootfs first to let it generate the postmarketOS"
                     " rootfs once, or supply a rootfs file with:"
                     f" --cp os.img:{chroot_dest}")


def aportgen(args):
    for package in args.packages:
        logging.info("Generate aport: " + package)
        pmb.aportgen.generate(args, package)


def build(args):
    # Strict mode: zap everything
    if args.strict:
        pmb.chroot.zap(args, False)

    if args.envkernel:
        pmb.build.envkernel.package_kernel(args)
        return

    # Set src and force
    src = os.path.realpath(os.path.expanduser(args.src[0])) \
        if args.src else None
    force = True if src else args.force
    if src and not os.path.exists(src):
        raise RuntimeError("Invalid path specified for --src: " + src)

    # Build all packages
    for package in args.packages:
        arch_package = args.arch or pmb.build.autodetect.arch(args, package)
        if not pmb.build.package(args, package, arch_package, force,
                                 args.strict, src=src):
            logging.info("NOTE: Package '" + package + "' is up to date. Use"
                         " 'pmbootstrap build " + package + " --force'"
                         " if needed.")


def build_init(args):
    suffix = _parse_suffix(args)
    pmb.build.init(args, suffix)


def checksum(args):
    for package in args.packages:
        if args.verify:
            pmb.build.checksum.verify(args, package)
        else:
            pmb.build.checksum.update(args, package)


def sideload(args):
    arch = args.deviceinfo["arch"]
    if args.arch:
        arch = args.arch
    user = args.user
    host = args.host
    pmb.sideload.sideload(args, user, host, args.port, arch, args.install_key,
                          args.packages)


def netboot(args):
    if args.action_netboot == "serve":
        pmb.netboot.start_nbd_server(args)


def chroot(args):
    # Suffix
    suffix = _parse_suffix(args)
    if (args.user and suffix != "native" and
            not suffix.startswith("buildroot_")):
        raise RuntimeError("--user is only supported for native or"
                           " buildroot_* chroots.")
    if args.xauth and suffix != "native":
        raise RuntimeError("--xauth is only supported for native chroot.")

    # apk: check minimum version, install packages
    pmb.chroot.apk.check_min_version(args, suffix)
    if args.add:
        pmb.chroot.apk.install(args, args.add.split(","), suffix)

    # Xauthority
    env = {}
    if args.xauth:
        pmb.chroot.other.copy_xauthority(args)
        env["DISPLAY"] = os.environ.get("DISPLAY")
        env["XAUTHORITY"] = "/home/pmos/.Xauthority"

    # Install blockdevice
    if args.install_blockdev:
        size_boot = 128  # 128 MiB
        size_root = 4096  # 4 GiB
        size_reserve = 2048  # 2 GiB
        pmb.install.blockdevice.create_and_mount_image(args, size_boot,
                                                       size_root, size_reserve)

    # Run the command as user/root
    if args.user:
        logging.info("(" + suffix + ") % su pmos -c '" +
                     " ".join(args.command) + "'")
        pmb.chroot.user(args, args.command, suffix, output=args.output,
                        env=env)
    else:
        logging.info("(" + suffix + ") % " + " ".join(args.command))
        pmb.chroot.root(args, args.command, suffix, output=args.output,
                        env=env)


def config(args):
    keys = pmb.config.config_keys
    if args.name and args.name not in keys:
        logging.info("NOTE: Valid config keys: " + ", ".join(keys))
        raise RuntimeError("Invalid config key: " + args.name)

    cfg = pmb.config.load(args)
    if args.reset:
        if args.name is None:
            raise RuntimeError("config --reset requires a name to be given.")
        value = pmb.config.defaults[args.name]
        cfg["pmbootstrap"][args.name] = value
        logging.info(f"Config changed to default: {args.name}='{value}'")
        pmb.config.save(args, cfg)
    elif args.value is not None:
        cfg["pmbootstrap"][args.name] = args.value
        logging.info("Config changed: " + args.name + "='" + args.value + "'")
        pmb.config.save(args, cfg)
    elif args.name:
        value = cfg["pmbootstrap"].get(args.name, "")
        print(value)
    else:
        cfg.write(sys.stdout)

    # Don't write the "Done" message
    pmb.helpers.logging.disable()


def repo_missing(args):
    missing = pmb.helpers.repo_missing.generate(args, args.arch, args.overview,
                                                args.package, args.built)
    print(json.dumps(missing, indent=4))


def index(args):
    pmb.build.index_repo(args)


def initfs(args):
    pmb.chroot.initfs.frontend(args)


def install(args):
    if args.no_fde:
        logging.warning("WARNING: --no-fde is deprecated,"
                        " as it is now the default.")
    if args.rsync and args.full_disk_encryption:
        raise ValueError("Installation using rsync is not compatible with full"
                         " disk encryption.")
    if args.rsync and not args.disk:
        raise ValueError("Installation using rsync only works with --disk.")

    if args.rsync and args.filesystem == "btrfs":
        raise ValueError("Installation using rsync"
                        " is not currently supported on btrfs filesystem.")

    # On-device installer checks
    # Note that this can't be in the mutually exclusive group that has most of
    # the conflicting options, because then it would not work with --disk.
    if args.on_device_installer:
        if args.full_disk_encryption:
            raise ValueError("--on-device-installer cannot be combined with"
                             " --fde. The user can choose to encrypt their"
                             " installation later in the on-device installer.")
        if args.android_recovery_zip:
            raise ValueError("--on-device-installer cannot be combined with"
                             " --android-recovery-zip (patches welcome)")
        if args.no_image:
            raise ValueError("--on-device-installer cannot be combined with"
                             " --no-image")
        if args.rsync:
            raise ValueError("--on-device-installer cannot be combined with"
                             " --rsync")
        if args.filesystem:
            raise ValueError("--on-device-installer cannot be combined with"
                             " --filesystem")

        if args.deviceinfo["cgpt_kpart"]:
            raise ValueError("--on-device-installer cannot be used with"
                             " ChromeOS devices")
    else:
        if args.ondev_cp:
            raise ValueError("--cp can only be combined with --ondev")
        if args.ondev_no_rootfs:
            raise ValueError("--no-rootfs can only be combined with --ondev."
                             " Do you mean --no-image?")
    if args.ondev_no_rootfs:
        _install_ondev_verify_no_rootfs(args)

    # On-device installer overrides
    if args.on_device_installer:
        # To make code for the on-device installer not needlessly complex, just
        # hardcode "user" as username here. (The on-device installer will set
        # a password for the user, disable SSH password authentication,
        # optionally add a new user for SSH that must not have the same
        # username etc.)
        if args.user != "user":
            logging.warning(f"WARNING: custom username '{args.user}' will be"
                            " replaced with 'user' for the on-device"
                            " installer.")
            args.user = "user"

    if not args.disk and args.split is None:
        # Default to split if the flash method requires it
        flasher = pmb.config.flashers.get(args.deviceinfo["flash_method"], {})
        if flasher.get("split", False):
            args.split = True

    # Android recovery zip related
    if args.android_recovery_zip and args.filesystem:
        raise ValueError("--android-recovery-zip cannot be combined with"
                         " --filesystem (patches welcome)")
    if args.android_recovery_zip and args.full_disk_encryption:
        logging.info("WARNING: --fde is rarely used in combination with"
                     " --android-recovery-zip. If this does not work, consider"
                     " using another method (e.g. installing via netcat)")
        logging.info("WARNING: the kernel of the recovery system (e.g. TWRP)"
                     f" must support the cryptsetup cipher '{args.cipher}'.")
        logging.info("If you know what you are doing, consider setting a"
                     " different cipher with 'pmbootstrap install --cipher=..."
                     " --fde --android-recovery-zip'.")

    # Don't install locally compiled packages and package signing keys
    if not args.install_local_pkgs:
        # Implies that we don't build outdated packages (overriding the answer
        # in 'pmbootstrap init')
        args.build_pkgs_on_install = False

        # Safest way to avoid installing local packages is having none
        if glob.glob(f"{args.work}/packages/*"):
            raise ValueError("--no-local-pkgs specified, but locally built"
                             " packages found. Consider 'pmbootstrap zap -p'"
                             " to delete them.")

    # Verify that the root filesystem is supported by current pmaports branch
    pmb.install.get_root_filesystem(args)

    pmb.install.install(args)


def flasher(args):
    pmb.flasher.frontend(args)


def export(args):
    pmb.export.frontend(args)


def update(args):
    existing_only = not args.non_existing
    if not pmb.helpers.repo.update(args, args.arch, True, existing_only):
        logging.info("No APKINDEX files exist, so none have been updated."
                     " The pmbootstrap command downloads the APKINDEX files on"
                     " demand.")
        logging.info("If you want to force downloading the APKINDEX files for"
                     " all architectures (not recommended), use:"
                     " pmbootstrap update --non-existing")


def newapkbuild(args):
    # Check for SRCURL usage
    is_url = False
    for prefix in ["http://", "https://", "ftp://"]:
        if args.pkgname_pkgver_srcurl.startswith(prefix):
            is_url = True
            break

    # Sanity check: -n is only allowed with SRCURL
    if args.pkgname and not is_url:
        raise RuntimeError("You can only specify a pkgname (-n) when using"
                           " SRCURL as last parameter.")

    # Passthrough: Strings (e.g. -d "my description")
    pass_through = []
    for entry in pmb.config.newapkbuild_arguments_strings:
        value = getattr(args, entry[1])
        if value:
            pass_through += [entry[0], value]

    # Passthrough: Switches (e.g. -C for CMake)
    for entry in (pmb.config.newapkbuild_arguments_switches_pkgtypes +
                  pmb.config.newapkbuild_arguments_switches_other):
        if getattr(args, entry[1]) is True:
            pass_through.append(entry[0])

    # Passthrough: PKGNAME[-PKGVER] | SRCURL
    pass_through.append(args.pkgname_pkgver_srcurl)
    pmb.build.newapkbuild(args, args.folder, pass_through, args.force)


def kconfig(args):
    if args.action_kconfig == "check":
        details = args.kconfig_check_details
        # Build the components list from cli arguments (--waydroid etc.)
        components_list = []
        for name in pmb.parse.kconfig.get_all_component_names():
            if getattr(args, f"kconfig_check_{name}"):
                components_list += [name]

        # Handle passing a file directly
        if args.file:
            if pmb.parse.kconfig.check_file(args.file, components_list,
                                            details=details):
                logging.info("kconfig check succeeded!")
                return
            raise RuntimeError("kconfig check failed!")

        # Default to all kernel packages
        packages = args.package
        if not args.package:
            for aport in pmb.helpers.pmaports.get_list(args):
                if aport.startswith("linux-"):
                    packages.append(aport.split("linux-")[1])

        # Iterate over all kernels
        error = False
        skipped = 0
        packages.sort()
        for package in packages:
            if not args.force:
                pkgname = package if package.startswith("linux-") \
                    else "linux-" + package
                aport = pmb.helpers.pmaports.find(args, pkgname)
                apkbuild = pmb.parse.apkbuild(f"{aport}/APKBUILD")
                if "!pmb:kconfigcheck" in apkbuild["options"]:
                    skipped += 1
                    continue
            if not pmb.parse.kconfig.check(args, package, components_list,
                                           details=details):
                error = True

        # At least one failure
        if error:
            raise RuntimeError("kconfig check failed!")
        else:
            if skipped:
                logging.info("NOTE: " + str(skipped) + " kernel(s) was skipped"
                             " (consider 'pmbootstrap kconfig check -f')")
            logging.info("kconfig check succeeded!")
    elif args.action_kconfig in ["edit", "migrate"]:
        if args.package:
            pkgname = args.package
        else:
            pkgname = args.deviceinfo["codename"]
        use_oldconfig = args.action_kconfig == "migrate"
        pmb.build.menuconfig(args, pkgname, use_oldconfig)


def deviceinfo_parse(args):
    # Default to all devices
    devices = args.devices
    if not devices:
        devices = pmb.helpers.devices.list_codenames(args)

    # Iterate over all devices
    kernel = args.deviceinfo_parse_kernel
    for device in devices:
        print(f"{device}, with kernel={kernel}:")
        print(json.dumps(pmb.parse.deviceinfo(args, device, kernel), indent=4,
                         sort_keys=True))


def apkbuild_parse(args):
    # Default to all packages
    packages = args.packages
    if not packages:
        packages = pmb.helpers.pmaports.get_list(args)

    # Iterate over all packages
    for package in packages:
        print(package + ":")
        aport = pmb.helpers.pmaports.find(args, package)
        path = aport + "/APKBUILD"
        print(json.dumps(pmb.parse.apkbuild(path), indent=4,
                         sort_keys=True))


def apkindex_parse(args):
    result = pmb.parse.apkindex.parse(args.apkindex_path)
    if args.package:
        if args.package not in result:
            raise RuntimeError("Package not found in the APKINDEX: " +
                               args.package)
        result = result[args.package]
    print(json.dumps(result, indent=4))


def pkgrel_bump(args):
    would_bump = True
    if args.auto:
        would_bump = pmb.helpers.pkgrel_bump.auto(args, args.dry)
    else:
        # Each package must exist
        for package in args.packages:
            pmb.helpers.pmaports.find(args, package)

        # Increase pkgrel
        for package in args.packages:
            pmb.helpers.pkgrel_bump.package(args, package, dry=args.dry)

    if args.dry and would_bump:
        logging.info("Pkgrels of package(s) would have been bumped!")
        sys.exit(1)


def aportupgrade(args):
    if args.all or args.all_stable or args.all_git:
        pmb.helpers.aportupgrade.upgrade_all(args)
    else:
        # Each package must exist
        for package in args.packages:
            pmb.helpers.pmaports.find(args, package)

        # Check each package for a new version
        for package in args.packages:
            pmb.helpers.aportupgrade.upgrade(args, package)


def qemu(args):
    pmb.qemu.run(args)


def shutdown(args):
    pmb.chroot.shutdown(args)


def stats(args):
    # Chroot suffix
    suffix = "native"
    if args.arch != pmb.config.arch_native:
        suffix = "buildroot_" + args.arch

    # Install ccache and display stats
    pmb.chroot.apk.install(args, ["ccache"], suffix)
    logging.info("(" + suffix + ") % ccache -s")
    pmb.chroot.user(args, ["ccache", "-s"], suffix, output="stdout")


def work_migrate(args):
    # do nothing (pmb/__init__.py already did the migration)
    pmb.helpers.logging.disable()


def log(args):
    log_testsuite = f"{args.work}/log_testsuite.txt"

    if args.clear_log:
        pmb.helpers.run.user(args, ["truncate", "-s", "0", args.log])
        pmb.helpers.run.user(args, ["truncate", "-s", "0", log_testsuite])

    cmd = ["tail", "-n", args.lines, "-F"]

    # Follow the testsuite's log file too if it exists. It will be created when
    # starting a test case that writes to it (git -C test grep log_testsuite).
    if os.path.exists(log_testsuite):
        cmd += [log_testsuite]

    # tail writes the last lines of the files to the terminal. Put the regular
    # log at the end, so that output is visible at the bottom (where the user
    # looks for an error / what's currently going on).
    cmd += [args.log]

    pmb.helpers.run.user(args, cmd, output="tui")


def zap(args):
    pmb.chroot.zap(args, dry=args.dry, http=args.http,
                   distfiles=args.distfiles, pkgs_local=args.pkgs_local,
                   pkgs_local_mismatch=args.pkgs_local_mismatch,
                   pkgs_online_mismatch=args.pkgs_online_mismatch,
                   rust=args.rust, netboot=args.netboot)

    # Don't write the "Done" message
    pmb.helpers.logging.disable()


def bootimg_analyze(args):
    bootimg = pmb.parse.bootimg(args, args.path)
    tmp_output = "Put these variables in the deviceinfo file of your device:\n"
    for line in pmb.aportgen.device.\
            generate_deviceinfo_fastboot_content(bootimg).split("\n"):
        tmp_output += "\n" + line.lstrip()
    logging.info(tmp_output)


def pull(args):
    failed = []
    for repo in pmb.config.git_repos.keys():
        if pmb.helpers.git.pull(args, repo) < 0:
            failed.append(repo)

    if not failed:
        return True

    logging.info("---")
    logging.info("WARNING: failed to update: " + ", ".join(failed))
    logging.info("")
    logging.info("'pmbootstrap pull' will only update the repositories, if:")
    logging.info("* they are on an officially supported branch (e.g. master)")
    logging.info("* the history is not conflicting (fast-forward is possible)")
    logging.info("* the git workdirs are clean")
    logging.info("You have changed mentioned repositories, so they don't meet")
    logging.info("these conditions anymore.")
    logging.info("")
    logging.info("Fix and try again:")
    for name_repo in failed:
        logging.info("* " + pmb.helpers.git.get_path(args, name_repo))
    logging.info("---")
    return False


def lint(args):
    packages = args.packages
    if not packages:
        packages = pmb.helpers.pmaports.get_list(args)

    pmb.helpers.lint.check(args, packages)


def status(args):
    if not pmb.helpers.status.print_status(args, args.details):
        sys.exit(1)


def ci(args):
    topdir = pmb.helpers.git.get_topdir(args, os.getcwd())
    if not os.path.exists(topdir):
        logging.error("ERROR: change your current directory to a git"
                      " repository (e.g. pmbootstrap, pmaports) before running"
                      " 'pmbootstrap ci'.")
        exit(1)

    scripts_available = pmb.ci.get_ci_scripts(topdir)
    scripts_available = pmb.ci.sort_scripts_by_speed(scripts_available)
    if not scripts_available:
        logging.error("ERROR: no supported CI scripts found in current git"
                      " repository, see https://postmarketos.org/pmb-ci")
        exit(1)

    scripts_selected = {}
    if args.scripts:
        if args.all:
            raise RuntimeError("Combining --all with script names doesn't"
                               " make sense")
        for script in args.scripts:
            if script not in scripts_available:
                logging.error(f"ERROR: script '{script}' not found in git"
                              " repository, found these:"
                              f" {', '.join(scripts_available.keys())}")
                exit(1)
            scripts_selected[script] = scripts_available[script]
    elif args.all:
        scripts_selected = scripts_available

    if args.fast:
        for script, script_data in scripts_available.items():
            if "slow" not in script_data["options"]:
                scripts_selected[script] = script_data

    if not pmb.helpers.git.clean_worktree(args, topdir):
        logging.warning("WARNING: this git repository has uncommitted changes")

    if not scripts_selected:
        scripts_selected = pmb.ci.ask_which_scripts_to_run(scripts_available)

    pmb.ci.run_scripts(args, topdir, scripts_selected)
