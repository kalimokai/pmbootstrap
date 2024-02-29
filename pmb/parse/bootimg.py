# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import os
import logging
import pmb


def is_dtb(path):
    if not os.path.isfile(path):
        return False
    with open(path, 'rb') as f:
        # Check FDT magic identifier (0xd00dfeed)
        return f.read(4) == b'\xd0\x0d\xfe\xed'


def get_mtk_label(path):
    """ Read the label from the MediaTek header of the kernel or ramdisk inside
        an extracted boot.img.
        :param path: to either the kernel or ramdisk extracted from boot.img
        :returns: * None: file does not exist or does not have MediaTek header
                  * Label string (e.g. "ROOTFS", "KERNEL") """
    if not os.path.exists(path):
        return None

    with open(path, 'rb') as f:
        # Check Mediatek header (0x88168858)
        if not f.read(4) == b'\x88\x16\x88\x58':
            return None
        f.seek(8)
        label = f.read(32).decode("utf-8").rstrip('\0')

        if label == "RECOVERY":
            logging.warning(
                "WARNING: This boot.img has MediaTek headers. Since you passed a"
                " recovery image instead of a regular boot.img, we can't tell what"
                " the ramdisk signature label is supposed to be, so we assume that"
                " it's the most common value, ROOTFS. There is a chance that this"
                " is wrong and it may not boot; in that case, run bootimg_analyze"
                " again with a regular boot.img. If this *is* a regular boot.img,"
                " replace the value of deviceinfo_bootimg_mtk_label_ramdisk with"
                " 'RECOVERY'.")
            return "ROOTFS"
        else:
            return label


def bootimg(args, path):
    if not os.path.exists(path):
        raise RuntimeError("Could not find file '" + path + "'")

    logging.info("NOTE: You will be prompted for your sudo/doas password, so"
                 " we can set up a chroot to extract and analyze your"
                 " boot.img file")
    pmb.chroot.apk.install(args, ["file", "unpackbootimg"])

    temp_path = pmb.chroot.other.tempfolder(args, "/tmp/bootimg_parser")
    bootimg_path = f"{args.work}/chroot_native{temp_path}/boot.img"

    # Copy the boot.img into the chroot temporary folder
    # and make it world readable
    pmb.helpers.run.root(args, ["cp", path, bootimg_path])
    pmb.helpers.run.root(args, ["chmod", "a+r", bootimg_path])

    file_output = pmb.chroot.user(args, ["file", "-b", "boot.img"],
                                  working_dir=temp_path,
                                  output_return=True).rstrip()
    if "android bootimg" not in file_output.lower():
        if "force" in args and args.force:
            logging.warning("WARNING: boot.img file seems to be invalid, but"
                            " proceeding anyway (-f specified)")
        else:
            logging.info("NOTE: If you are sure that your file is a valid"
                         " boot.img file, you could force the analysis"
                         " with: 'pmbootstrap bootimg_analyze " + path +
                         " -f'")
            if ("linux kernel" in file_output.lower() or
                    "ARM OpenFirmware FORTH Dictionary" in file_output):
                raise RuntimeError("File is a Kernel image, you might need the"
                                   " 'heimdall-isorec' flash method. See also:"
                                   " <https://wiki.postmarketos.org/wiki/"
                                   "Deviceinfo_flash_methods>")
            else:
                raise RuntimeError("File is not an Android boot.img. (" +
                                   file_output + ")")

    # Extract all the files
    pmb.chroot.user(args, ["unpackbootimg", "-i", "boot.img"],
                    working_dir=temp_path)

    output = {}
    header_version = 0
    # Get base, offsets, pagesize, cmdline and qcdt info
    # This file does not exist for example for qcdt images
    if os.path.isfile(f"{bootimg_path}-header_version"):
        with open(f"{bootimg_path}-header_version", 'r') as f:
            header_version = int(f.read().replace('\n', ''))
            output["header_version"] = str(header_version)

    if header_version >= 3:
        output["pagesize"] = "4096"
    else:
        with open(f"{bootimg_path}-base", 'r') as f:
            output["base"] = ("0x%08x" % int(f.read().replace('\n', ''), 16))
        with open(f"{bootimg_path}-kernel_offset", 'r') as f:
            output["kernel_offset"] = ("0x%08x"
                                       % int(f.read().replace('\n', ''), 16))
        with open(f"{bootimg_path}-ramdisk_offset", 'r') as f:
            output["ramdisk_offset"] = ("0x%08x"
                                        % int(f.read().replace('\n', ''), 16))
        with open(f"{bootimg_path}-second_offset", 'r') as f:
            output["second_offset"] = ("0x%08x"
                                       % int(f.read().replace('\n', ''), 16))
        with open(f"{bootimg_path}-tags_offset", 'r') as f:
            output["tags_offset"] = ("0x%08x"
                                     % int(f.read().replace('\n', ''), 16))
        with open(f"{bootimg_path}-pagesize", 'r') as f:
            output["pagesize"] = f.read().replace('\n', '')

        if header_version == 2:
            with open(f"{bootimg_path}-dtb_offset", 'r') as f:
                output["dtb_offset"] = ("0x%08x"
                                        % int(f.read().replace('\n', ''), 16))

    if get_mtk_label(f"{bootimg_path}-kernel") is not None:
        output["mtk_label_kernel"] = get_mtk_label(f"{bootimg_path}-kernel")
    if get_mtk_label(f"{bootimg_path}-ramdisk") is not None:
        output["mtk_label_ramdisk"] = get_mtk_label(f"{bootimg_path}-ramdisk")

    output["qcdt"] = ("true" if os.path.isfile(f"{bootimg_path}-dt") and
                      os.path.getsize(f"{bootimg_path}-dt") > 0 else "false")

    output["dtb_second"] = ("true" if is_dtb(f"{bootimg_path}-second")
                            else "false")

    with open(f"{bootimg_path}-cmdline", 'r') as f:
        output["cmdline"] = f.read().replace('\n', '')

    # Cleanup
    pmb.chroot.root(args, ["rm", "-r", temp_path])

    return output
