# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import os
import re
import glob
import shlex
import sys

import pmb.chroot
import pmb.chroot.apk
import pmb.chroot.other
import pmb.chroot.initfs
import pmb.config
import pmb.config.pmaports
import pmb.helpers.devices
import pmb.helpers.run
import pmb.install.blockdevice
import pmb.install.recovery
import pmb.install.ui
import pmb.install

# Keep track of the packages we already visited in get_recommends() to avoid
# infinite recursion
get_recommends_visited = []


def mount_device_rootfs(args, suffix_rootfs, suffix_mount="native"):
    """
    Mount the device rootfs.
    :param suffix_rootfs: the chroot suffix, where the rootfs that will be
                          installed on the device has been created (e.g.
                          "rootfs_qemu-amd64")
    :param suffix_mount: the chroot suffix, where the device rootfs will be
                         mounted (e.g. "native")
    """
    mountpoint = f"/mnt/{suffix_rootfs}"
    pmb.helpers.mount.bind(args, f"{args.work}/chroot_{suffix_rootfs}",
                           f"{args.work}/chroot_{suffix_mount}{mountpoint}")
    return mountpoint


def get_subpartitions_size(args, suffix):
    """
    Calculate the size of the boot and root subpartition.

    :param suffix: the chroot suffix, e.g. "rootfs_qemu-amd64"
    :returns: (boot, root) the size of the boot and root
              partition as integer in MiB
    """
    boot = int(args.boot_size)

    # Estimate root partition size, then add some free space. The size
    # calculation is not as trivial as one may think, and depending on the
    # file system etc it seems to be just impossible to get it right.
    chroot = f"{args.work}/chroot_{suffix}"
    root = pmb.helpers.other.folder_size(args, chroot) / 1024
    root *= 1.20
    root += 50 + int(args.extra_space)
    return (boot, root)


def get_nonfree_packages(args, device):
    """
    Get any legacy non-free subpackages in the APKBUILD.
    Also see: https://postmarketos.org/edge/2024/02/15/default-nonfree-fw/

    :returns: list of non-free packages to be installed. Example:
              ["device-nokia-n900-nonfree-firmware"]
    """
    # Read subpackages
    apkbuild = pmb.parse.apkbuild(pmb.helpers.devices.find_path(args, device,
                                                                'APKBUILD'))
    subpackages = apkbuild["subpackages"]

    # Check for firmware and userland
    ret = []
    prefix = "device-" + device + "-nonfree-"
    if prefix + "firmware" in subpackages:
        ret += [prefix + "firmware"]
    if prefix + "userland" in subpackages:
        ret += [prefix + "userland"]
    return ret


def get_kernel_package(args, device):
    """
    Get the device's kernel subpackage based on the user's choice in
    "pmbootstrap init".

    :param device: code name, e.g. "sony-amami"
    :returns: [] or the package in a list, e.g.
              ["device-sony-amami-kernel-mainline"]
    """
    # Empty list: single kernel devices / "none" selected
    kernels = pmb.parse._apkbuild.kernels(args, device)
    if not kernels or args.kernel == "none":
        return []

    # Sanity check
    if args.kernel not in kernels:
        raise RuntimeError("Selected kernel (" + args.kernel + ") is not"
                           " valid for device " + device + ". Please"
                           " run 'pmbootstrap init' to select a valid kernel.")

    # Selected kernel subpackage
    return ["device-" + device + "-kernel-" + args.kernel]


def copy_files_from_chroot(args, suffix):
    """
    Copy all files from the rootfs chroot to /mnt/install, except
    for the home folder (because /home will contain some empty
    mountpoint folders).

    :param suffix: the chroot suffix, e.g. "rootfs_qemu-amd64"
    """
    # Mount the device rootfs
    logging.info(f"(native) copy {suffix} to /mnt/install/")
    mountpoint = mount_device_rootfs(args, suffix)
    mountpoint_outside = args.work + "/chroot_native" + mountpoint

    # Remove empty qemu-user binary stub (where the binary was bind-mounted)
    arch_qemu = pmb.parse.arch.alpine_to_qemu(args.deviceinfo["arch"])
    qemu_binary = mountpoint_outside + "/usr/bin/qemu-" + arch_qemu + "-static"
    if os.path.exists(qemu_binary):
        pmb.helpers.run.root(args, ["rm", qemu_binary])

    # Remove apk progress fifo
    fifo = f"{args.work}/chroot_{suffix}/tmp/apk_progress_fifo"
    if os.path.exists(fifo):
        pmb.helpers.run.root(args, ["rm", fifo])

    # Get all folders inside the device rootfs (except for home)
    folders = []
    for path in glob.glob(mountpoint_outside + "/*"):
        if path.endswith("/home"):
            continue
        folders += [os.path.basename(path)]

    # Update or copy all files
    if args.rsync:
        pmb.chroot.apk.install(args, ["rsync"])
        rsync_flags = "-a"
        if args.verbose:
            rsync_flags += "vP"
        pmb.chroot.root(args, ["rsync", rsync_flags, "--delete"] + folders +
                        ["/mnt/install/"], working_dir=mountpoint)
        pmb.chroot.root(args, ["rm", "-rf", "/mnt/install/home"])
    else:
        pmb.chroot.root(args, ["cp", "-a"] + folders + ["/mnt/install/"],
                        working_dir=mountpoint)


def create_home_from_skel(args):
    """
    Create /home/{user} from /etc/skel
    """
    rootfs = args.work + "/chroot_native/mnt/install"
    # In btrfs, home subvol & home dir is created in format.py
    if args.filesystem != "btrfs":
        pmb.helpers.run.root(args, ["mkdir", rootfs + "/home"])
    homedir = rootfs + "/home/" + args.user
    if os.path.exists(f"{rootfs}/etc/skel"):
        pmb.helpers.run.root(args, ["cp", "-a", f"{rootfs}/etc/skel", homedir])
    else:
        pmb.helpers.run.root(args, ["mkdir", homedir])
    pmb.helpers.run.root(args, ["chown", "-R", "10000", homedir])


def configure_apk(args):
    """
    Copy over all official keys, and the keys used to compile local packages
    (unless --no-local-pkgs is set). Then copy the corresponding APKINDEX files
    and remove the /mnt/pmbootstrap/packages repository.
    """
    # Official keys
    pattern = f"{pmb.config.apk_keys_path}/*.pub"

    # Official keys + local keys
    if args.install_local_pkgs:
        pattern = f"{args.work}/config_apk_keys/*.pub"

    # Copy over keys
    rootfs = args.work + "/chroot_native/mnt/install"
    for key in glob.glob(pattern):
        pmb.helpers.run.root(args, ["cp", key, rootfs + "/etc/apk/keys/"])

    # Copy over the corresponding APKINDEX files from cache
    index_files = pmb.helpers.repo.apkindex_files(args,
                                                  arch=args.deviceinfo["arch"],
                                                  user_repository=False)
    for f in index_files:
        pmb.helpers.run.root(args, ["cp", f, rootfs + "/var/cache/apk/"])

    # Disable pmbootstrap repository
    pmb.helpers.run.root(args, ["sed", "-i", r"/\/mnt\/pmbootstrap\/packages/d",
                                rootfs + "/etc/apk/repositories"])
    pmb.helpers.run.user(args, ["cat", rootfs + "/etc/apk/repositories"])


def set_user(args):
    """
    Create user with UID 10000 if it doesn't exist.
    Usually the ID for the first user created is 1000, but higher ID is
    chosen here to not cause issues with existing installations. Historically,
    this was done to avoid conflict with Android UIDs/GIDs, but pmOS has since
    dropped support for hybris/Halium.
    """
    suffix = "rootfs_" + args.device
    if not pmb.chroot.user_exists(args, args.user, suffix):
        pmb.chroot.root(args, ["adduser", "-D", "-u", "10000", args.user],
                        suffix)

    pmaports_cfg = pmb.config.pmaports.read_config(args)
    groups = []
    groups += pmaports_cfg.get("install_user_groups",
                               "audio,input,netdev,plugdev,video,wheel").split(",")
    groups += pmb.install.ui.get_groups(args)

    for group in groups:
        pmb.chroot.root(args, ["addgroup", "-S", group], suffix,
                        check=False)
        pmb.chroot.root(args, ["addgroup", args.user, group], suffix)


def setup_login_chpasswd_user_from_arg(args, suffix):
    """
    Set the user's password from what the user passed as --password. Make an
    effort to not have the password end up in the log file by writing it to
    a temp file, instead of "echo user:$pass | chpasswd". The user should of
    course only use this with a test password anyway, but let's be nice and try
    to have the user protected from accidentally posting their password in
    any case.

    :param suffix: of the chroot, where passwd will be execute (either the
                   f"rootfs_{args.device}", or f"installer_{args.device}")
    """
    path = "/tmp/pmbootstrap_chpasswd_in"
    path_outside = f"{args.work}/chroot_{suffix}{path}"

    with open(path_outside, "w", encoding="utf-8") as handle:
        handle.write(f"{args.user}:{args.password}")

    pmb.chroot.root(args, ["sh", "-c", f"cat {shlex.quote(path)} | chpasswd"],
                    suffix)

    os.unlink(path_outside)


def is_root_locked(args, suffix):
    """
    Figure out from /etc/shadow if root is already locked. The output of this
    is stored in the log, so use grep to only log the line for root, not the
    line for the user which contains a hash of the user's password.

    :param suffix: either rootfs_{args.device} or installer_{args.device}
    """
    shadow_root = pmb.chroot.root(args, ["grep", "^root:!:", "/etc/shadow"],
                                  suffix, output_return=True, check=False)
    return shadow_root.startswith("root:!:")


def setup_login(args, suffix):
    """
    Loop until the password for user has been set successfully, and disable
    root login.

    :param suffix: of the chroot, where passwd will be execute (either the
                   f"rootfs_{args.device}", or f"installer_{args.device}")
    """
    if not args.on_device_installer:
        # User password
        logging.info(f" *** SET LOGIN PASSWORD FOR: '{args.user}' ***")
        if args.password:
            setup_login_chpasswd_user_from_arg(args, suffix)
        else:
            while True:
                try:
                    pmb.chroot.root(args, ["passwd", args.user], suffix,
                                    output="interactive")
                    break
                except RuntimeError:
                    logging.info("WARNING: Failed to set the password. Try it"
                                 " one more time.")

    # Disable root login
    if is_root_locked(args, suffix):
        logging.debug(f"({suffix}) root is already locked")
    else:
        logging.debug(f"({suffix}) locking root")
        pmb.chroot.root(args, ["passwd", "-l", "root"], suffix)


def copy_ssh_keys(args):
    """
    If requested, copy user's SSH public keys to the device if they exist
    """
    if not args.ssh_keys:
        return
    keys = []
    for key in glob.glob(os.path.expanduser(args.ssh_key_glob)):
        with open(key, "r") as infile:
            keys += infile.readlines()

    if not len(keys):
        logging.info("NOTE: Public SSH keys not found. Since no SSH keys "
                     "were copied, you will need to use SSH password "
                     "authentication!")
        return

    authorized_keys = args.work + "/chroot_native/tmp/authorized_keys"
    outfile = open(authorized_keys, "w")
    for key in keys:
        outfile.write("%s" % key)
    outfile.close()

    target = f"{args.work}/chroot_native/mnt/install/home/{args.user}/.ssh"
    pmb.helpers.run.root(args, ["mkdir", target])
    pmb.helpers.run.root(args, ["chmod", "700", target])
    pmb.helpers.run.root(args, ["cp", authorized_keys, target +
                                "/authorized_keys"])
    pmb.helpers.run.root(args, ["rm", authorized_keys])
    pmb.helpers.run.root(args, ["chown", "-R", "10000:10000", target])


def setup_keymap(args):
    """
    Set the keymap with the setup-keymap utility if the device requires it
    """
    suffix = "rootfs_" + args.device
    info = pmb.parse.deviceinfo(args, device=args.device)
    if "keymaps" not in info or info["keymaps"].strip() == "":
        logging.info("NOTE: No valid keymap specified for device")
        return
    options = info["keymaps"].split(' ')
    if (args.keymap != "" and
            args.keymap is not None and
            args.keymap in options):
        layout, variant = args.keymap.split("/")
        pmb.chroot.root(args, ["setup-keymap", layout, variant], suffix,
                        output="interactive")

        # Check xorg config
        config = None
        if os.path.exists(f"{args.work}/chroot_{suffix}/etc/X11/xorg.conf.d"):
            config = pmb.chroot.root(args, ["grep", "-rl", "XkbLayout",
                                            "/etc/X11/xorg.conf.d/"],
                                     suffix, check=False, output_return=True)
        if config:
            # Nokia n900 (RX-51) randomly merges some keymaps so we
            # have to specify a composite keymap for a few countries. See:
            # https://gitlab.freedesktop.org/xkeyboard-config/xkeyboard-config/-/blob/master/symbols/nokia_vndr/rx-51
            if variant == "rx51_fi" or variant == "rx51_se":
                layout = "fise"
            if variant == "rx51_da" or variant == "rx51_no":
                layout = "dano"
            if variant == "rx51_pt" or variant == "rx51_es":
                layout = "ptes"
            # Multiple files can contain the keyboard layout, take last
            config = config.splitlines()[-1]
            old_text = "Option *\\\"XkbLayout\\\" *\\\".*\\\""
            new_text = "Option \\\"XkbLayout\\\" \\\"" + layout + "\\\""
            pmb.chroot.root(args, ["sed", "-i", "s/" + old_text + "/" +
                            new_text + "/", config], suffix)
    else:
        logging.info("NOTE: No valid keymap specified for device")


def setup_timezone(args):
    suffix = f"rootfs_{args.device}"

    arch = args.deviceinfo["arch"]
    alpine_conf = pmb.helpers.package.get(args, "alpine-conf", arch)
    version = alpine_conf["version"].split("-r")[0]

    setup_tz_cmd = ["setup-timezone"]
    # setup-timezone will, by default, copy the timezone to /etc/zoneinfo
    # and disregard tzdata, to save space. If we actually have tzdata
    # installed, make sure that setup-timezone makes use of it, since
    # there's no space to be saved.
    if "tzdata" in pmb.chroot.apk.installed(args, suffix):
        setup_tz_cmd += ["-i"]
    if not pmb.parse.version.check_string(version, ">=3.14.0"):
        setup_tz_cmd += ["-z"]
    setup_tz_cmd += [args.timezone]
    pmb.chroot.root(args, setup_tz_cmd, suffix)


def setup_hostname(args):
    """
    Set the hostname and update localhost address in /etc/hosts
    """
    # Default to device name. If device name is not a valid hostname then
    # default to a static default.
    hostname = args.hostname
    if not hostname:
        hostname = args.device
        if not pmb.helpers.other.validate_hostname(hostname):
            # A valid host name, see:
            # https://datatracker.ietf.org/doc/html/rfc1035#section-2.3.1
            hostname = "postmarketos-device"
    elif not pmb.helpers.other.validate_hostname(hostname):
        # Invalid hostname set by the user e.g., via pmb init, this should
        # fail so they can fix it
        raise RuntimeError("Hostname '" + hostname + "' is not valid, please"
                           " run 'pmbootstrap init' to configure it.")

    suffix = "rootfs_" + args.device
    # Generate /etc/hostname
    pmb.chroot.root(args, ["sh", "-c", "echo " + shlex.quote(hostname) +
                           " > /etc/hostname"], suffix)
    # Update /etc/hosts
    regex = (r"s/^127\.0\.0\.1.*/127.0.0.1\t" + re.escape(hostname) +
             " localhost.localdomain localhost/")
    pmb.chroot.root(args, ["sed", "-i", "-e", regex, "/etc/hosts"], suffix)


def setup_appstream(args):
    """
    If alpine-appstream-downloader has been downloaded, execute it to have
    update AppStream data on new installs
    """
    suffix = "rootfs_" + args.device
    installed_pkgs = pmb.chroot.apk.installed(args, suffix)

    if "alpine-appstream-downloader" not in installed_pkgs or args.offline:
        return

    if not pmb.chroot.root(args, ["alpine-appstream-downloader",
                                  "/mnt/appstream-data"], suffix, check=False):
        pmb.chroot.root(args, ["mkdir", "-p", "/var/lib/swcatalog"], suffix)
        pmb.chroot.root(args, ["cp", "-r", "/mnt/appstream-data/icons",
                               "/mnt/appstream-data/xml",
                               "-t", "/var/lib/swcatalog"], suffix)


def disable_sshd(args):
    if not args.no_sshd:
        return

    # check=False: rc-update doesn't exit with 0 if already disabled
    suffix = f"rootfs_{args.device}"
    pmb.chroot.root(args, ["rc-update", "del", "sshd", "default"], suffix,
                    check=False)

    # Verify that it's gone
    sshd_files = pmb.helpers.run.root(
        args, ["find", "-name", "sshd"], output_return=True,
        working_dir=f"{args.work}/chroot_{suffix}/etc/runlevels")
    if sshd_files:
        raise RuntimeError(f"Failed to disable sshd service: {sshd_files}")


def print_sshd_info(args):
    logging.info("")  # make the note stand out
    logging.info("*** SSH DAEMON INFORMATION ***")

    if not args.ondev_no_rootfs:
        if args.no_sshd:
            logging.info("SSH daemon is disabled (--no-sshd).")
        else:
            logging.info("SSH daemon is enabled (disable with --no-sshd).")
            logging.info(f"Login as '{args.user}' with the password given"
                         " during installation.")

    if args.on_device_installer:
        # We don't disable sshd in the installer OS. If the device is reachable
        # on the network by default (e.g. Raspberry Pi), one can lock down the
        # installer OS down by disabling the debug user (see wiki page).
        logging.info("SSH daemon is enabled in the installer OS, to allow"
                     " debugging the installer image.")
        logging.info("More info: https://postmarketos.org/ondev-debug")


def disable_firewall(args):
    if not args.no_firewall:
        return

    # check=False: rc-update doesn't exit with 0 if already disabled
    suffix = f"rootfs_{args.device}"
    pmb.chroot.root(args, ["rc-update", "del", "nftables", "default"], suffix,
                    check=False)

    # Verify that it's gone
    nftables_files = pmb.helpers.run.root(
        args, ["find", "-name", "nftables"], output_return=True,
        working_dir=f"{args.work}/chroot_{suffix}/etc/runlevels")
    if nftables_files:
        raise RuntimeError(f"Failed to disable firewall: {nftables_files}")


def print_firewall_info(args):
    pmaports_cfg = pmb.config.pmaports.read_config(args)
    pmaports_ok = pmaports_cfg.get("supported_firewall", None) == "nftables"

    # Find kernel pmaport (will not be found if Alpine kernel is used)
    apkbuild_found = False
    apkbuild_has_opt = False

    arch = args.deviceinfo["arch"]
    kernel = get_kernel_package(args, args.device)
    if kernel:
        kernel_apkbuild = pmb.build._package.get_apkbuild(args, kernel[0],
                                                          arch)
        if kernel_apkbuild:
            opts = kernel_apkbuild["options"]
            apkbuild_has_opt = "pmb:kconfigcheck-nftables" in opts
            apkbuild_found = True

    # Print the note and make it stand out
    logging.info("")
    logging.info("*** FIREWALL INFORMATION ***")

    if not pmaports_ok:
        logging.info("Firewall is not supported in checked out pmaports"
                     " branch.")
    elif args.no_firewall:
        logging.info("Firewall is disabled (--no-firewall).")
    elif not apkbuild_found:
        logging.info("Firewall is enabled, but may not work (couldn't"
                     " determine if kernel supports nftables).")
    elif apkbuild_has_opt:
        logging.info("Firewall is enabled and supported by kernel.")
    else:
        logging.info("Firewall is enabled, but will not work (no support in"
                     " kernel config for nftables).")
        logging.info("If/when the kernel supports it in the future, it"
                     " will work automatically.")

    logging.info("For more information: https://postmarketos.org/firewall")


def generate_binary_list(args, suffix, step):
    """
    Perform three checks prior to writing binaries to disk: 1) that binaries
    exist, 2) that binaries do not extend into the first partition, 3) that
    binaries do not overlap each other.

    :param suffix: of the chroot, which holds the firmware files (either the
                   f"rootfs_{args.device}", or f"installer_{args.device}")
    :param step: partition step size in bytes
    """
    binary_ranges = {}
    binary_list = []
    binaries = args.deviceinfo["sd_embed_firmware"].split(",")

    for binary_offset in binaries:
        binary, offset = binary_offset.split(':')
        try:
            offset = int(offset)
        except ValueError:
            raise RuntimeError("Value for firmware binary offset is "
                               f"not valid: {offset}")
        binary_path = os.path.join(args.work, f"chroot_{suffix}", "usr/share",
                                   binary)
        if not os.path.exists(binary_path):
            raise RuntimeError("The following firmware binary does not "
                               f"exist in the {suffix} chroot: "
                               f"/usr/share/{binary}")
        # Insure that embedding the firmware will not overrun the
        # first partition
        boot_part_start = args.deviceinfo["boot_part_start"] or "2048"
        max_size = (int(boot_part_start) * 512) - (offset * step)
        binary_size = os.path.getsize(binary_path)
        if binary_size > max_size:
            raise RuntimeError("The firmware is too big to embed in the "
                               f"disk image {binary_size}B > {max_size}B")
        # Insure that the firmware does not conflict with any other firmware
        # that will be embedded
        binary_start = offset * step
        binary_end = binary_start + binary_size
        for start, end in binary_ranges.items():
            if ((binary_start >= start and binary_start < end) or
                    (binary_end > start and binary_end <= end)):
                raise RuntimeError("The firmware overlaps with at least one "
                                   f"other firmware image: {binary}")

        binary_ranges[binary_start] = binary_end
        binary_list.append((binary, offset))

    return binary_list


def embed_firmware(args, suffix):
    """
    This method will embed firmware, located at /usr/share, that are specified
    by the "sd_embed_firmware" deviceinfo parameter into the SD card image
    (e.g. u-boot). Binaries that would overwrite the first partition are not
    accepted, and if multiple binaries are specified then they will be checked
    for collisions with each other.

    :param suffix: of the chroot, which holds the firmware files (either the
                   f"rootfs_{args.device}", or f"installer_{args.device}")
    """
    if not args.deviceinfo["sd_embed_firmware"]:
        return

    step = 1024
    if args.deviceinfo["sd_embed_firmware_step_size"]:
        try:
            step = int(args.deviceinfo["sd_embed_firmware_step_size"])
        except ValueError:
            raise RuntimeError("Value for "
                               "deviceinfo_sd_embed_firmware_step_size "
                               "is not valid: {}".format(step))

    device_rootfs = mount_device_rootfs(args, suffix)
    binary_list = generate_binary_list(args, suffix, step)

    # Write binaries to disk
    for binary, offset in binary_list:
        binary_file = os.path.join("/usr/share", binary)
        logging.info("Embed firmware {} in the SD card image at offset {} with"
                     " step size {}".format(binary, offset, step))
        filename = os.path.join(device_rootfs, binary_file.lstrip("/"))
        pmb.chroot.root(args, ["dd", "if=" + filename, "of=/dev/install",
                               "bs=" + str(step), "seek=" + str(offset)])


def write_cgpt_kpart(args, layout, suffix):
    """
    Write the kernel to the ChromeOS kernel partition.

    :param layout: partition layout from get_partition_layout()
    :param suffix: of the chroot, which holds the image file to be flashed
    """
    if not args.deviceinfo["cgpt_kpart"] or not args.install_cgpt:
        return

    device_rootfs = mount_device_rootfs(args, suffix)
    filename = f"{device_rootfs}{args.deviceinfo['cgpt_kpart']}"
    pmb.chroot.root(
        args, ["dd", f"if={filename}", f"of=/dev/installp{layout['kernel']}"])


def sanity_check_boot_size(args):
    default = pmb.config.defaults["boot_size"]
    if int(args.boot_size) >= int(default):
        return
    logging.error("ERROR: your pmbootstrap has a small boot_size of"
                  f" {args.boot_size} configured, probably because the config"
                  " has been created with an old version.")
    logging.error("This can lead to problems later on, we recommend setting it"
                  f" to {default} MiB.")
    logging.error(f"Run 'pmbootstrap config boot_size {default}' and try again.")
    sys.exit(1)


def sanity_check_disk(args):
    device = args.disk
    device_name = os.path.basename(device)
    if not os.path.exists(device):
        raise RuntimeError(f"{device} doesn't exist, is the disk plugged?")
    if os.path.isdir('/sys/class/block/{}'.format(device_name)):
        with open('/sys/class/block/{}/ro'.format(device_name), 'r') as handle:
            ro = handle.read()
        if ro == '1\n':
            raise RuntimeError(f"{device} is read-only, maybe a locked SD card?")


def sanity_check_disk_size(args):
    device = args.disk
    devpath = os.path.realpath(device)
    sysfs = '/sys/class/block/{}/size'.format(devpath.replace('/dev/', ''))
    if not os.path.isfile(sysfs):
        # This is a best-effort sanity check, continue if it's not checkable
        return

    with open(sysfs) as handle:
        raw = handle.read()

    # Size is in 512-byte blocks
    size = int(raw.strip())
    human = "{:.2f} GiB".format(size / 2 / 1024 / 1024)

    # Warn if the size is larger than 100GiB
    if not args.assume_yes and size > (100 * 2 * 1024 * 1024):
        if not pmb.helpers.cli.confirm(args,
                                       f"WARNING: The target disk ({devpath}) "
                                       "is larger than a usual SD card "
                                       "(>100GiB). Are you sure you want to "
                                       f"overwrite this {human} disk?",
                                       no_assumptions=True):
            raise RuntimeError("Aborted.")


def get_ondev_pkgver(args):
    arch = args.deviceinfo["arch"]
    package = pmb.helpers.package.get(args, "postmarketos-ondev", arch)
    return package["version"].split("-r")[0]


def sanity_check_ondev_version(args):
    ver_pkg = get_ondev_pkgver(args)
    ver_min = pmb.config.ondev_min_version
    if pmb.parse.version.compare(ver_pkg, ver_min) == -1:
        raise RuntimeError("This version of pmbootstrap requires"
                           f" postmarketos-ondev version {ver_min} or"
                           " higher. The postmarketos-ondev found in pmaports"
                           f" / in the binary packages has version {ver_pkg}.")


def get_partition_layout(reserve, kernel):
    """
    :param reserve: create an empty partition between root and boot (pma#463)
    :param kernel: create a separate kernel partition before all other
                   partitions, e.g. for the ChromeOS devices with cgpt
    :returns: the partition layout, e.g. without reserve and kernel:
              {"kernel": None, "boot": 1, "reserve": None, "root": 2}
    """
    ret = {}
    ret["kernel"] = None
    ret["boot"] = 1
    ret["reserve"] = None
    ret["root"] = 2

    if kernel:
        ret["kernel"] = 1
        ret["boot"] += 1
        ret["root"] += 1

    if reserve:
        ret["reserve"] = ret["root"]
        ret["root"] += 1
    return ret


def get_uuid(args, partition):
    """
    Get UUID of a partition

    :param partition: block device for getting UUID from
    """
    return pmb.chroot.root(
        args,
        [
            "blkid",
            "-s", "UUID",
            "-o", "value",
            partition,
        ],
        output_return=True
    ).rstrip()


def create_crypttab(args, layout, suffix):
    """
    Create /etc/crypttab config

    :param layout: partition layout from get_partition_layout()
    :param suffix: of the chroot, which crypttab will be created to
    """

    luks_uuid = get_uuid(args, f"/dev/installp{layout['root']}")

    crypttab = f"root UUID={luks_uuid} none luks\n"

    open(f"{args.work}/chroot_{suffix}/tmp/crypttab", "w").write(crypttab)
    pmb.chroot.root(args, ["mv", "/tmp/crypttab", "/etc/crypttab"], suffix)


def create_fstab(args, layout, suffix):
    """
    Create /etc/fstab config

    :param layout: partition layout from get_partition_layout()
    :param suffix: of the chroot, which fstab will be created to
    """

    # Do not install fstab into target rootfs when using on-device
    # installer. Provide fstab only to installer suffix
    if args.on_device_installer and "rootfs_" in suffix:
        return

    boot_dev = f"/dev/installp{layout['boot']}"
    root_dev = f"/dev/installp{layout['root']}"

    boot_mount_point = f"UUID={get_uuid(args, boot_dev)}"
    root_mount_point = "/dev/mapper/root" if args.full_disk_encryption \
        else f"UUID={get_uuid(args, root_dev)}"

    boot_filesystem = args.deviceinfo["boot_filesystem"] or "ext2"
    root_filesystem = pmb.install.get_root_filesystem(args)

    if root_filesystem == "btrfs":
        # btrfs gets separate subvolumes for root, var and home
        fstab = f"""
# <file system> <mount point> <type> <options> <dump> <pass>
{root_mount_point} / btrfs subvol=@,compress=zstd:2,ssd 0 0
{root_mount_point} /home btrfs subvol=@home,compress=zstd:2,ssd 0 0
{root_mount_point} /root btrfs subvol=@root,compress=zstd:2,ssd 0 0
{root_mount_point} /srv btrfs subvol=@srv,compress=zstd:2,ssd 0 0
{root_mount_point} /var btrfs subvol=@var,ssd 0 0
{root_mount_point} /.snapshots btrfs subvol=@snapshots,compress=zstd:2,ssd 0 0

{boot_mount_point} /boot {boot_filesystem} defaults 0 0
""".lstrip()

    else:
        fstab = f"""
# <file system> <mount point> <type> <options> <dump> <pass>
{root_mount_point} / {root_filesystem} defaults 0 0
{boot_mount_point} /boot {boot_filesystem} defaults 0 0
""".lstrip()

    with open(f"{args.work}/chroot_{suffix}/tmp/fstab", "w") as f:
        f.write(fstab)
    pmb.chroot.root(args, ["mv", "/tmp/fstab", "/etc/fstab"], suffix)


def install_system_image(args, size_reserve, suffix, step, steps,
                         boot_label="pmOS_boot", root_label="pmOS_root",
                         split=False, disk=None):
    """
    :param size_reserve: empty partition between root and boot in MiB (pma#463)
    :param suffix: the chroot suffix, where the rootfs that will be installed
                   on the device has been created (e.g. "rootfs_qemu-amd64")
    :param step: next installation step
    :param steps: total installation steps
    :param boot_label: label of the boot partition (e.g. "pmOS_boot")
    :param root_label: label of the root partition (e.g. "pmOS_root")
    :param split: create separate images for boot and root partitions
    :param disk: path to disk block device (e.g. /dev/mmcblk0) or None
    """
    # Partition and fill image file/disk block device
    logging.info(f"*** ({step}/{steps}) PREPARE INSTALL BLOCKDEVICE ***")
    pmb.chroot.shutdown(args, True)
    (size_boot, size_root) = get_subpartitions_size(args, suffix)
    layout = get_partition_layout(size_reserve, args.deviceinfo["cgpt_kpart"] \
             and args.install_cgpt)
    if not args.rsync:
        pmb.install.blockdevice.create(args, size_boot, size_root,
                                       size_reserve, split, disk)
        if not split:
            if args.deviceinfo["cgpt_kpart"] and args.install_cgpt:
                pmb.install.partition_cgpt(
                    args, layout, size_boot, size_reserve)
            else:
                pmb.install.partition(args, layout, size_boot, size_reserve)
    if not split:
        pmb.install.partitions_mount(args, layout, disk)

    pmb.install.format(args, layout, boot_label, root_label, disk)

    # Create /etc/fstab and /etc/crypttab
    logging.info("(native) create /etc/fstab")
    create_fstab(args, layout, suffix)
    if args.full_disk_encryption:
        logging.info("(native) create /etc/crypttab")
        create_crypttab(args, layout, suffix)

    # Run mkinitfs to pass UUIDs to cmdline
    logging.info(f"({suffix}) mkinitfs")
    pmb.chroot.root(args, ["mkinitfs"], suffix)

    # Clean up after running mkinitfs in chroot
    pmb.helpers.mount.umount_all(args, f"{args.work}/chroot_{suffix}")
    pmb.helpers.run.root(args, ["rm", f"{args.work}/chroot_{suffix}/in-pmbootstrap"])
    pmb.chroot.remove_mnt_pmbootstrap(args, suffix)

    # Just copy all the files
    logging.info(f"*** ({step + 1}/{steps}) FILL INSTALL BLOCKDEVICE ***")
    copy_files_from_chroot(args, suffix)
    create_home_from_skel(args)
    configure_apk(args)
    copy_ssh_keys(args)

    # Don't try to embed firmware and cgpt on split images since there's no
    # place to put it and it will end up in /dev of the chroot instead
    if not split:
        embed_firmware(args, suffix)
        write_cgpt_kpart(args, layout, suffix)

    if disk:
        logging.info(f"Unmounting disk {disk} (this may take a while "
                     "to sync, please wait)")
    pmb.chroot.shutdown(args, True)

    # Convert rootfs to sparse using img2simg
    sparse = args.sparse
    if sparse is None:
        sparse = args.deviceinfo["flash_sparse"] == "true"

    if sparse and not split and not disk:
        logging.info("(native) make sparse rootfs")
        pmb.chroot.apk.install(args, ["android-tools"])
        sys_image = args.device + ".img"
        sys_image_sparse = args.device + "-sparse.img"
        pmb.chroot.user(args, ["img2simg", sys_image, sys_image_sparse],
                        working_dir="/home/pmos/rootfs/")
        pmb.chroot.user(args, ["mv", "-f", sys_image_sparse, sys_image],
                        working_dir="/home/pmos/rootfs/")

        # patch sparse image for Samsung devices if specified
        samsungify_strategy = args.deviceinfo["flash_sparse_samsung_format"]
        if samsungify_strategy:
            logging.info("(native) convert sparse image into Samsung's sparse image format")
            pmb.chroot.apk.install(args, ["sm-sparse-image-tool"])
            sys_image = f"{args.device}.img"
            sys_image_patched = f"{args.device}-patched.img"
            pmb.chroot.user(args, ["sm_sparse_image_tool", "samsungify", "--strategy",
                                   samsungify_strategy, sys_image, sys_image_patched],
                            working_dir="/home/pmos/rootfs/")
            pmb.chroot.user(args, ["mv", "-f", sys_image_patched, sys_image],
                            working_dir="/home/pmos/rootfs/")


def print_flash_info(args):
    """ Print flashing information, based on the deviceinfo data and the
        pmbootstrap arguments. """
    logging.info("")  # make the note stand out
    logging.info("*** FLASHING INFORMATION ***")

    # System flash information
    method = args.deviceinfo["flash_method"]
    flasher = pmb.config.flashers.get(method, {})
    flasher_actions = flasher.get("actions", {})
    requires_split = flasher.get("split", False)

    if method == "none":
        logging.info("Refer to the installation instructions of your device,"
                     " or the generic install instructions in the wiki.")
        logging.info("https://wiki.postmarketos.org/wiki/Installation_guide"
                     "#pmbootstrap_flash")
        return

    logging.info("Run the following to flash your installation to the"
                 " target device:")

    if "flash_rootfs" in flasher_actions and not args.disk and \
            bool(args.split) == requires_split:
        logging.info("* pmbootstrap flasher flash_rootfs")
        logging.info("  Flashes the generated rootfs image to your device:")
        if args.split:
            logging.info(f"  {args.work}/chroot_native/home/pmos/rootfs/"
                         f"{args.device}-rootfs.img")
        else:
            logging.info(f"  {args.work}/chroot_native/home/pmos/rootfs/"
                         f"{args.device}.img")
            logging.info("  (NOTE: This file has a partition table, which"
                         " contains /boot and / subpartitions. That way we"
                         " don't need to change the partition layout on your"
                         " device.)")

    # if current flasher supports vbmeta and partition is explicitly specified
    # in deviceinfo
    if "flash_vbmeta" in flasher_actions and \
            (args.deviceinfo["flash_fastboot_partition_vbmeta"] or
             args.deviceinfo["flash_heimdall_partition_vbmeta"]):
        logging.info("* pmbootstrap flasher flash_vbmeta")
        logging.info("  Flashes vbmeta image with verification disabled flag.")

    # if current flasher supports dtbo and partition is explicitly specified
    # in deviceinfo
    if "flash_dtbo" in flasher_actions and \
            (args.deviceinfo["flash_fastboot_partition_dtbo"] or
             args.deviceinfo["flash_heimdall_partition_dtbo"]):
        logging.info("* pmbootstrap flasher flash_dtbo")
        logging.info("  Flashes dtbo image.")

    # Most flash methods operate independently of the boot partition.
    # (e.g. an Android boot image is generated). In that case, "flash_kernel"
    # works even when partitions are split or installing to disk. This is not
    # possible if the flash method requires split partitions.
    if "flash_kernel" in flasher_actions and \
            (not requires_split or args.split):
        logging.info("* pmbootstrap flasher flash_kernel")
        logging.info("  Flashes the kernel + initramfs to your device:")
        if requires_split:
            logging.info(f"  {args.work}/chroot_native/home/pmos/rootfs/"
                         f"{args.device}-boot.img")
        else:
            logging.info(f"  {args.work}/chroot_rootfs_{args.device}/boot")

    if "boot" in flasher_actions:
        logging.info("  (NOTE: " + method + " also supports booting"
                     " the kernel/initramfs directly without flashing."
                     " Use 'pmbootstrap flasher boot' to do that.)")

    if "flash_lk2nd" in flasher_actions and \
            os.path.exists(args.work + "/chroot_rootfs_" + args.device +
                           "/boot/lk2nd.img"):
        logging.info("* Your device supports and may even require"
                     " flashing lk2nd. You should flash it before"
                     " flashing anything else. Use 'pmbootstrap flasher"
                     " flash_lk2nd' to do that.")

    # Export information
    logging.info("* If the above steps do not work, you can also create"
                 " symlinks to the generated files with 'pmbootstrap export'"
                 " and flash outside of pmbootstrap.")


def install_recovery_zip(args, steps):
    logging.info(f"*** ({steps}/{steps}) CREATING RECOVERY-FLASHABLE ZIP ***")
    suffix = "buildroot_" + args.deviceinfo["arch"]
    mount_device_rootfs(args, f"rootfs_{args.device}", suffix)
    pmb.install.recovery.create_zip(args, suffix)

    # Flash information
    logging.info("*** FLASHING INFORMATION ***")
    logging.info("Flashing with the recovery zip is explained here:")
    logging.info("https://postmarketos.org/recoveryzip")


def install_on_device_installer(args, step, steps):
    # Generate the rootfs image
    if not args.ondev_no_rootfs:
        suffix_rootfs = f"rootfs_{args.device}"
        install_system_image(args, 0, suffix_rootfs, step=step, steps=steps,
                             split=True)
        step += 2

    # Prepare the installer chroot
    logging.info(f"*** ({step}/{steps}) CREATE ON-DEVICE INSTALLER ROOTFS ***")
    step += 1
    packages = ([f"device-{args.device}",
                 "postmarketos-ondev"] +
                get_kernel_package(args, args.device) +
                get_nonfree_packages(args, args.device))

    suffix_installer = f"installer_{args.device}"
    pmb.chroot.apk.install(args, packages, suffix_installer)

    # Move rootfs image into installer chroot
    img_path_dest = f"{args.work}/chroot_{suffix_installer}/var/lib/rootfs.img"
    if not args.ondev_no_rootfs:
        img = f"{args.device}-root.img"
        img_path_src = f"{args.work}/chroot_native/home/pmos/rootfs/{img}"
        logging.info(f"({suffix_installer}) add {img} as /var/lib/rootfs.img")
        pmb.install.losetup.umount(args, img_path_src)
        pmb.helpers.run.root(args, ["mv", img_path_src, img_path_dest])

    # Run ondev-prepare, so it may generate nice configs from the channel
    # properties (e.g. to display the version number), or transform the image
    # file into another format. This can all be done without pmbootstrap
    # changes in the postmarketos-ondev package.
    logging.info(f"({suffix_installer}) ondev-prepare")
    channel = pmb.config.pmaports.read_config(args)["channel"]
    channel_cfg = pmb.config.pmaports.read_config_channel(args)
    env = {"ONDEV_CHANNEL": channel,
           "ONDEV_CHANNEL_BRANCH_APORTS": channel_cfg["branch_aports"],
           "ONDEV_CHANNEL_BRANCH_PMAPORTS": channel_cfg["branch_pmaports"],
           "ONDEV_CHANNEL_DESCRIPTION": channel_cfg["description"],
           "ONDEV_CHANNEL_MIRRORDIR_ALPINE": channel_cfg["mirrordir_alpine"],
           "ONDEV_CIPHER": args.cipher,
           "ONDEV_PMBOOTSTRAP_VERSION": pmb.__version__,
           "ONDEV_UI": args.ui}
    pmb.chroot.root(args, ["ondev-prepare"], suffix_installer, env=env)

    # Copy files specified with 'pmbootstrap install --ondev --cp'
    if args.ondev_cp:
        for host_src, chroot_dest in args.ondev_cp:
            host_dest = f"{args.work}/chroot_{suffix_installer}/{chroot_dest}"
            logging.info(f"({suffix_installer}) add {host_src} as"
                         f" {chroot_dest}")
            pmb.helpers.run.root(args, ["install", "-Dm644", host_src,
                                        host_dest])

    # Remove $DEVICE-boot.img (we will generate a new one if --split was
    # specified, otherwise the separate boot image is not needed)
    if not args.ondev_no_rootfs:
        img_boot = f"{args.device}-boot.img"
        logging.info(f"(native) rm {img_boot}")
        pmb.chroot.root(args, ["rm", f"/home/pmos/rootfs/{img_boot}"])

    # Disable root login
    setup_login(args, suffix_installer)

    # Generate installer image
    size_reserve = round(os.path.getsize(img_path_dest) / 1024 / 1024) + 200
    pmaports_cfg = pmb.config.pmaports.read_config(args)
    boot_label = pmaports_cfg.get("supported_install_boot_label",
                                  "pmOS_inst_boot")
    install_system_image(args, size_reserve, suffix_installer, step, steps,
                         boot_label, "pmOS_install", args.split, args.disk)


def get_selected_providers(args, packages, initial=True):
    """
    Look through the specified packages and see which providers were selected
    in "pmbootstrap init". Install those as extra packages to select them
    instead of the default provider. This function is called recursively on the
    dependencies of the given packages.

    :param packages: the packages that have selectable providers (_pmb_select)
    :param initial: used internally when the function calls itself
    :return: additional provider packages to install
    """
    global get_selected_providers_visited

    ret = []

    if initial:
        get_selected_providers_visited = []

    for package in packages:
        if package in get_selected_providers_visited:
            logging.debug(f"get_selected_providers: {package}: already visited")
            continue
        get_selected_providers_visited += [package]

        # Note that this ignores packages that don't exist. This means they
        # aren't in pmaports. This is fine, with the assumption that
        # installation will fail later in some other method if they truly don't
        # exist in any repo.
        apkbuild = pmb.helpers.pmaports.get(args, package, subpackages=False, must_exist=False)
        if not apkbuild:
            continue
        for select in apkbuild['_pmb_select']:
            if select in args.selected_providers:
                ret += [args.selected_providers[select]]
                logging.debug(f"{package}: install selected_providers:"
                              f" {', '.join(ret)}")
        # Also iterate through dependencies to collect any providers they have
        depends = apkbuild["depends"]
        if depends:
            ret += get_selected_providers(args, depends, False)

    return ret


def get_recommends(args, packages, initial=True):
    """
    Look through the specified packages and collect additional packages
    specified under _pmb_recommends in them. This is recursive, so it will dive
    into packages that are listed under recommends to collect any packages they
    might also have listed under their own _pmb_recommends.

    Recursion is only done into packages found in pmaports.

    If running with pmbootstrap install --no-recommends, this function returns
    an empty list.

    :param packages: list of packages of which we want to get the recommends
    :param initial: used internally when the function calls itself
    :returns: list of pkgnames, e.g. ["chatty", "gnome-contacts"]
    """
    global get_recommends_visited

    ret = []
    if not args.install_recommends:
        return ret

    if initial:
        get_recommends_visited = []

    for package in packages:
        if package in get_recommends_visited:
            logging.debug(f"get_recommends: {package}: already visited")
            continue
        get_recommends_visited += [package]

        # Note that this ignores packages that don't exist. This means they
        # aren't in pmaports. This is fine, with the assumption that
        # installation will fail later in some other method if they truly don't
        # exist in any repo.
        apkbuild = pmb.helpers.pmaports.get(args, package, must_exist=False)
        if not apkbuild:
            continue
        if package in apkbuild["subpackages"]:
            # Just focus on the subpackage
            apkbuild = apkbuild["subpackages"][package]
            # The subpackage is None if the subpackage does not have a function
            # in the APKBUILD (uses the default function), e.g. for most openrc
            # subpackages. See pmb.parse._apkbuild._parse_subpackage().
            if not apkbuild:
                continue
        recommends = apkbuild["_pmb_recommends"]
        if recommends:
            logging.debug(f"{package}: install _pmb_recommends:"
                          f" {', '.join(recommends)}")
            ret += recommends
            # Call recursively in case recommends have pmb_recommends of their
            # own.
            ret += get_recommends(args, recommends, False)
        # Also iterate through dependencies to collect any recommends they have
        depends = apkbuild["depends"]
        if depends:
            ret += get_recommends(args, depends, False)

    return ret


def create_device_rootfs(args, step, steps):
    # List all packages to be installed (including the ones specified by --add)
    # and upgrade the installed packages/apkindexes
    logging.info(f'*** ({step}/{steps}) CREATE DEVICE ROOTFS ("{args.device}")'
                 ' ***')

    suffix = f"rootfs_{args.device}"
    # Create user before installing packages, so post-install scripts of
    # pmaports can figure out the username (legacy reasons: pmaports#820)
    set_user(args)

    # Fill install_packages
    install_packages = (pmb.config.install_device_packages +
                        ["device-" + args.device])
    if not args.install_base:
        install_packages = [p for p in install_packages
                            if p != "postmarketos-base"]
    if args.ui.lower() != "none":
        install_packages += ["postmarketos-ui-" + args.ui]

    # Add additional providers of base/device/UI package
    install_packages += get_selected_providers(args, install_packages)

    install_packages += get_kernel_package(args, args.device)
    install_packages += get_nonfree_packages(args, args.device)
    if args.ui.lower() != "none":
        if args.ui_extras:
            install_packages += ["postmarketos-ui-" + args.ui + "-extras"]
    if args.extra_packages.lower() != "none":
        install_packages += args.extra_packages.split(",")
    if args.add:
        install_packages += args.add.split(",")
    locale_is_set = (args.locale != pmb.config.defaults["locale"])
    if locale_is_set:
        install_packages += ["lang", "musl-locales"]

    pmaports_cfg = pmb.config.pmaports.read_config(args)
    # postmarketos-base supports a dummy package for blocking osk-sdl install
    # when not required
    if pmaports_cfg.get("supported_base_nofde", None):
        # The ondev installer *could* enable fde at runtime, so include it
        # explicitly in the rootfs until there's a mechanism to selectively
        # install it when the ondev installer is running.
        # Always install it when --fde is specified.
        if args.full_disk_encryption or args.on_device_installer:
            # Pick the most suitable unlocker depending on the packages
            # selected for installation
            unlocker = pmb.parse.depends.package_provider(
                args, "postmarketos-fde-unlocker", install_packages, suffix)
            if unlocker["pkgname"] not in install_packages:
                install_packages += [unlocker["pkgname"]]
        else:
            install_packages += ["postmarketos-base-nofde"]

    pmb.helpers.repo.update(args, args.deviceinfo["arch"])

    # Install uninstallable "dependencies" by default
    install_packages += get_recommends(args, install_packages)

    # Explicitly call build on the install packages, to re-build them or any
    # dependency, in case the version increased
    if args.build_pkgs_on_install:
        for pkgname in install_packages:
            pmb.build.package(args, pkgname, args.deviceinfo["arch"])

    # Install all packages to device rootfs chroot (and rebuild the initramfs,
    # because that doesn't always happen automatically yet, e.g. when the user
    # installed a hook without pmbootstrap - see #69 for more info)
    pmb.chroot.apk.install(args, install_packages, suffix)
    flavor = pmb.chroot.other.kernel_flavor_installed(args, suffix)
    pmb.chroot.initfs.build(args, flavor, suffix)

    # Set the user password
    setup_login(args, suffix)

    # Set the keymap if the device requires it
    setup_keymap(args)

    # Set timezone
    setup_timezone(args)

    # Set locale
    if locale_is_set:
        # 10locale-pmos.sh gets sourced before 20locale.sh from
        # alpine-baselayout by /etc/profile. Since they don't override the
        # locale if it exists, it warranties we have preference
        line = f"export LANG=${{LANG:-{shlex.quote(args.locale)}}}"
        pmb.chroot.root(args, ["sh", "-c", f"echo {shlex.quote(line)}"
                               " > /etc/profile.d/10locale-pmos.sh"], suffix)

    # Set the hostname as the device name
    setup_hostname(args)

    setup_appstream(args)

    disable_sshd(args)
    disable_firewall(args)


def install(args):
    # Sanity checks
    sanity_check_boot_size(args)
    if not args.android_recovery_zip and args.disk:
        sanity_check_disk(args)
        sanity_check_disk_size(args)
    if args.on_device_installer:
        sanity_check_ondev_version(args)

    # Number of steps for the different installation methods.
    if args.no_image:
        steps = 2
    elif args.android_recovery_zip:
        steps = 3
    elif args.on_device_installer:
        steps = 4 if args.ondev_no_rootfs else 7
    else:
        steps = 4

    if args.zap:
        pmb.chroot.zap(args, False)

    # Install required programs in native chroot
    step = 1
    logging.info(f"*** ({step}/{steps}) PREPARE NATIVE CHROOT ***")
    pmb.chroot.apk.install(args, pmb.config.install_native_packages,
                           build=False)
    step += 1

    if not args.ondev_no_rootfs:
        create_device_rootfs(args, step, steps)
        step += 1

    if args.no_image:
        return
    elif args.android_recovery_zip:
        return install_recovery_zip(args, steps)

    if args.on_device_installer:
        # Runs install_system_image twice
        install_on_device_installer(args, step, steps)
    else:
        install_system_image(args, 0, f"rootfs_{args.device}", step, steps,
                             split=args.split, disk=args.disk)

    print_flash_info(args)
    print_sshd_info(args)
    print_firewall_info(args)

    # Leave space before 'chroot still active' note
    logging.info("")
