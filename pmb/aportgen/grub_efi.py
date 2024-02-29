# Copyright 2023 Nick Reitemeyer, Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import pmb.aportgen.core
import pmb.build
import pmb.chroot.apk
import pmb.chroot.apk_static
import pmb.helpers.run
import pmb.parse.apkindex


def generate(args, pkgname):
    arch = "x86"
    if pkgname != "grub-efi-x86":
        raise RuntimeError("only grub-efi-x86 is available")
    package_data = pmb.parse.apkindex.package(args, "grub")
    version = package_data["version"]
    pkgver = version.split("-r")[0]
    pkgrel = version.split("-r")[1]

    # Prepare aportgen tempdir inside and outside of chroot
    tempdir = "/tmp/aportgen"
    pmb.chroot.root(args, ["rm", "-rf", tempdir])
    pmb.helpers.run.user(args, ["mkdir", "-p", f"{args.work}/aportgen",
                                f"{args.work}/chroot_native/{tempdir}"])

    # Write the APKBUILD
    channel_cfg = pmb.config.pmaports.read_config_channel(args)
    mirrordir = channel_cfg["mirrordir_alpine"]
    apkbuild_path = f"{args.work}/chroot_native/{tempdir}/APKBUILD"
    apk_name = f'"$srcdir/grub-efi-$pkgver-r$pkgrel-$_arch-{mirrordir}.apk"'
    with open(apkbuild_path, "w", encoding="utf-8") as handle:
        apkbuild = f"""\
            # Automatically generated aport, do not edit!
            # Generator: pmbootstrap aportgen {pkgname}

            pkgname={pkgname}
            pkgver={pkgver}
            pkgrel={pkgrel}

            _arch="{arch}"
            _mirror="{pmb.config.aportgen_mirror_alpine}"

            pkgdesc="GRUB $_arch EFI files for every architecture"
            url="https://www.gnu.org/software/grub/"
            license="GPL-3.0-or-later"
            arch="{pmb.config.arch_native}"
            source="grub-efi-$pkgver-r$pkgrel-$_arch-{mirrordir}.apk::$_mirror/{mirrordir}/main/$_arch/grub-efi-$pkgver-r$pkgrel.apk"

            package() {{
                mkdir -p "$pkgdir"
                cd "$pkgdir"
                tar -xf {apk_name}
                rm .PKGINFO .SIGN.*
            }}
        """
        for line in apkbuild.split("\n"):
            handle.write(line[12:].replace(" " * 4, "\t") + "\n")

    # Generate checksums
    pmb.build.init_abuild_minimal(args)
    pmb.chroot.root(args, ["chown", "-R", "pmos:pmos", tempdir])
    pmb.chroot.user(args, ["abuild", "checksum"], working_dir=tempdir)
    pmb.helpers.run.user(args, ["cp", apkbuild_path, f"{args.work}/aportgen"])
