# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import multiprocessing
import os
import pmb.parse.arch
import sys
from typing import List

#
# Exported functions
#
from pmb.config.load import load
from pmb.config.save import save
from pmb.config.merge_with_args import merge_with_args
from pmb.config.sudo import which_sudo


#
# Exported variables (internal configuration)
#
pmb_src = os.path.normpath(os.path.realpath(__file__) + "/../../..")
apk_keys_path = pmb_src + "/pmb/data/keys"
arch_native = pmb.parse.arch.alpine_native()

# apk-tools minimum version
# https://pkgs.alpinelinux.org/packages?name=apk-tools&branch=edge
# Update this frequently to prevent a MITM attack with an outdated version
# (which may contain a vulnerable apk/openssl, and allows an attacker to
# exploit the system!)
apk_tools_min_version = {"edge": "2.14.0-r5",
                         "v3.19": "2.14.0-r5",
                         "v3.18": "2.14.0-r2",
                         "v3.17": "2.12.10-r1",
                         "v3.16": "2.12.9-r3",
                         "v3.15": "2.12.7-r3",
                         "v3.14": "2.12.7-r0",
                         "v3.13": "2.12.7-r0",
                         "v3.12": "2.10.8-r1"}

# postmarketOS aports compatibility (checked against "version" in pmaports.cfg)
pmaports_min_version = "7"

# Version of the work folder (as asked during 'pmbootstrap init'). Increase
# this number, whenever migration is required and provide the migration code,
# see migrate_work_folder()).
work_version = 6

# Minimum required version of postmarketos-ondev (pmbootstrap install --ondev).
# Try to support the current versions of all channels (edge, v21.03). When
# bumping > 0.4.0, remove compat code in pmb/install/_install.py (search for
# get_ondev_pkgver).
ondev_min_version = "0.2.0"

# Programs that pmbootstrap expects to be available from the host system. Keep
# in sync with README.md, and try to keep the list as small as possible. The
# idea is to run almost everything in Alpine chroots.
required_programs = [
    "git",
    "openssl",
    "ps",
    "tar",
]


def sudo(cmd: List[str]) -> List[str]:
    """Adapt a command to run as root."""
    sudo = which_sudo()
    if sudo:
        return [sudo, *cmd]
    else:
        return cmd


# Keys saved in the config file (mostly what we ask in 'pmbootstrap init')
config_keys = [
    "aports",
    "boot_size",
    "build_default_device_arch",
    "build_pkgs_on_install",
    "ccache_size",
    "device",
    "extra_packages",
    "extra_space",
    "hostname",
    "is_default_channel",
    "jobs",
    "kernel",
    "keymap",
    "locale",
    "mirror_alpine",
    "mirrors_postmarketos",
    "qemu_redir_stdio",
    "ssh_key_glob",
    "ssh_keys",
    "sudo_timer",
    "timezone",
    "ui",
    "ui_extras",
    "user",
    "work",
]

# Config file/commandline default values
# $WORK gets replaced with the actual value for args.work (which may be
# overridden on the commandline)
defaults = {
    # This first chunk matches config_keys
    "aports": "$WORK/cache_git/pmaports",
    "boot_size": "256",
    "build_default_device_arch": False,
    "build_pkgs_on_install": True,
    "ccache_size": "5G",
    "device": "qemu-amd64",
    "extra_packages": "none",
    "extra_space": "0",
    "hostname": "",
    "is_default_channel": True,
    "jobs": str(multiprocessing.cpu_count() + 1),
    "kernel": "stable",
    "keymap": "",
    "locale": "en_US.UTF-8",
    # NOTE: mirrors use http by default to leverage caching
    "mirror_alpine": "http://dl-cdn.alpinelinux.org/alpine/",
    # NOTE: mirrors_postmarketos variable type is supposed to be
    #       comma-separated string, not a python list or any other type!
    "mirrors_postmarketos": "http://mirror.postmarketos.org/postmarketos/",
    "qemu_redir_stdio": False,
    "ssh_key_glob": "~/.ssh/id_*.pub",
    "ssh_keys": False,
    "sudo_timer": False,
    "timezone": "GMT",
    "ui": "console",
    "ui_extras": False,
    "user": "user",
    "work": os.path.expanduser("~") + "/.local/var/pmbootstrap",

    # These values are not part of config_keys
    "cipher": "aes-xts-plain64",
    "config": (os.environ.get('XDG_CONFIG_HOME') or
               os.path.expanduser("~/.config")) + "/pmbootstrap.cfg",
    "fork_alpine": False,
    # A higher value is typically desired, but this can lead to VERY long open
    # times on slower devices due to host systems being MUCH faster than the
    # target device (see issue #429).
    "iter_time": "200",
    "log": "$WORK/log.txt",
}


# Whether we're connected to a TTY (which allows things like e.g. printing
# progress bars)
is_interactive = sys.stdout.isatty() and \
    sys.stderr.isatty() and \
    sys.stdin.isatty()


# ANSI escape codes to highlight stdout
styles = {
    "BLUE": '\033[94m',
    "BOLD": '\033[1m',
    "GREEN": '\033[92m',
    "RED": '\033[91m',
    "YELLOW": '\033[93m',
    "END": '\033[0m'
}

if "NO_COLOR" in os.environ:
    for style in styles.keys():
        styles[style] = ""

# Supported filesystems and their fstools packages
filesystems = {"btrfs": "btrfs-progs",
               "ext2": "e2fsprogs",
               "ext4": "e2fsprogs",
               "f2fs": "f2fs-tools",
               "fat16": "dosfstools",
               "fat32": "dosfstools"}

# Legacy channels and their new names (pmb#2015)
pmaports_channels_legacy = {"stable": "v20.05",
                            "stable-next": "v21.03"}
#
# CHROOT
#

# Usually the ID for the first user created is 1000. However, we want
# pmbootstrap to work even if the 'user' account inside the chroots has
# another UID, so we force it to be different.
chroot_uid_user = "12345"

# The PATH variable used inside all chroots
chroot_path = ":".join([
    "/usr/lib/ccache/bin",
    "/usr/local/sbin",
    "/usr/local/bin",
    "/usr/sbin:/usr/bin",
    "/sbin",
    "/bin"
])

# The PATH variable used on the host, to find the "chroot" and "sh"
# executables. As pmbootstrap runs as user, not as root, the location
# for the chroot executable may not be in the PATH (Debian).
chroot_host_path = os.environ["PATH"] + ":/usr/sbin/"

# Folders that get mounted inside the chroot
# $WORK gets replaced with args.work
# $ARCH gets replaced with the chroot architecture (eg. x86_64, armhf)
# $CHANNEL gets replaced with the release channel (e.g. edge, v21.03)
# Use no more than one dir after /mnt/pmbootstrap, see remove_mnt_pmbootstrap.
chroot_mount_bind = {
    "/proc": "/proc",
    "$WORK/cache_apk_$ARCH": "/var/cache/apk",
    "$WORK/cache_appstream/$ARCH/$CHANNEL": "/mnt/appstream-data",
    "$WORK/cache_ccache_$ARCH": "/mnt/pmbootstrap/ccache",
    "$WORK/cache_distfiles": "/var/cache/distfiles",
    "$WORK/cache_git": "/mnt/pmbootstrap/git",
    "$WORK/cache_go": "/mnt/pmbootstrap/go",
    "$WORK/cache_rust": "/mnt/pmbootstrap/rust",
    "$WORK/config_abuild": "/mnt/pmbootstrap/abuild-config",
    "$WORK/config_apk_keys": "/etc/apk/keys",
    "$WORK/cache_sccache": "/mnt/pmbootstrap/sccache",
    "$WORK/images_netboot": "/mnt/pmbootstrap/netboot",
    "$WORK/packages/$CHANNEL": "/mnt/pmbootstrap/packages",
}

# Building chroots (all chroots, except for the rootfs_ chroot) get symlinks in
# the "pmos" user's home folder pointing to mountfolders from above.
# Rust packaging is new and still a bit weird in Alpine and postmarketOS. As of
# writing, we only have one package (squeekboard), and use cargo to download
# the source of all dependencies at build time and compile it. Usually, this is
# a no-go, but at least until this is resolved properly, let's cache the
# dependencies and downloads as suggested in "Caching the Cargo home in CI":
# https://doc.rust-lang.org/cargo/guide/cargo-home.html
# Go: cache the directories "go env GOMODCACHE" and "go env GOCACHE" point to,
# to avoid downloading dependencies over and over (GOMODCACHE, similar to the
# rust depends caching described above) and to cache build artifacts (GOCACHE,
# similar to ccache).
chroot_home_symlinks = {
    "/mnt/pmbootstrap/abuild-config": "/home/pmos/.abuild",
    "/mnt/pmbootstrap/ccache": "/home/pmos/.ccache",
    "/mnt/pmbootstrap/go/gocache": "/home/pmos/.cache/go-build",
    "/mnt/pmbootstrap/go/gomodcache": "/home/pmos/go/pkg/mod",
    "/mnt/pmbootstrap/packages": "/home/pmos/packages/pmos",
    "/mnt/pmbootstrap/rust/git/db": "/home/pmos/.cargo/git/db",
    "/mnt/pmbootstrap/rust/registry/cache": "/home/pmos/.cargo/registry/cache",
    "/mnt/pmbootstrap/rust/registry/index": "/home/pmos/.cargo/registry/index",
    "/mnt/pmbootstrap/sccache": "/home/pmos/.cache/sccache",
}

# Device nodes to be created in each chroot. Syntax for each entry:
# [permissions, type, major, minor, name]
chroot_device_nodes = [
    [666, "c", 1, 3, "null"],
    [666, "c", 1, 5, "zero"],
    [666, "c", 1, 7, "full"],
    [644, "c", 1, 8, "random"],
    [644, "c", 1, 9, "urandom"],
]

# Age in hours that we keep the APKINDEXes before downloading them again.
# You can force-update them with 'pmbootstrap update'.
apkindex_retention_time = 4


# When chroot is considered outdated (in seconds)
chroot_outdated = 3600 * 24 * 2

#
# BUILD
#
# Officially supported host/target architectures for postmarketOS. Only
# specify architectures supported by Alpine here. For cross-compiling,
# we need to generate the "musl-$ARCH" and "gcc-$ARCH" packages (use
# "pmbootstrap aportgen musl-armhf" etc.).
build_device_architectures = ["armhf", "armv7", "aarch64", "x86_64", "x86", "riscv64"]

# Packages that will be installed in a chroot before it builds packages
# for the first time
build_packages = ["abuild", "build-base", "ccache", "git"]

#
# KCONFIG CHECK
#
# Implemented value types:
# - boolean (e.g. '"ANDROID_PARANOID_NETWORK": False'):
#   - False: disabled
#   - True: enabled, either as module or built-in
# - array (e.g. '"ANDROID_BINDER_DEVICES": ["binder", "hwbinder"]'):
#   - each element of the array must be contained in the kernel config string,
#     in any order. The example above would accept the following in the config:
#       CONFIG_ANDROID_BINDER_DEVICES="hwbinder,vndbinder,binder"
# - string (e.g. '"LSM": "lockdown,yama,loadpin,safesetid,integrity"'):
#   - the value in the kernel config must be the same as the given string. Use
#     this e.g. if the order of the elements is important.

# Necessary kernel config options
kconfig_options = {
    ">=0.0.0": {  # all versions
        "all": {  # all arches
            "ANDROID_PARANOID_NETWORK": False,
            "BLK_DEV_INITRD": True,
            "CGROUPS": True,
            "CRYPTO_AES": True,
            "CRYPTO_XTS": True,
            "DEVTMPFS": True,
            "DM_CRYPT": True,
            "INPUT_EVDEV": True,
            "EXT4_FS": True,
            "KINETO_GAN": False,
            "PFT": False,
            "SEC_RESTRICT_ROOTING": False,
            "SYSVIPC": True,
            "TMPFS_POSIX_ACL": True,
            "USE_VFB": False,
            "VT": True,
        }
    },
    ">=2.6.0": {
        "all": {
            "BINFMT_ELF": True,
        },
    },
    ">=3.10.0": {
        "all": {
            "BINFMT_SCRIPT": True,
        },
    },
    ">=4.0.0": {
        "all": {
            "UEVENT_HELPER": True,
            "USER_NS": True,
        },
    },
    "<4.7.0": {
        "all": {
            "DEVPTS_MULTIPLE_INSTANCES": True,
        }
    },
    "<4.14.0": {
        "all": {
            "SAMSUNG_TUI": False,
            "TZDEV": False,
        }
    },
    "<5.2.0": {
        "armhf armv7 x86": {
            "LBDAF": True
        }
    }
}

# Necessary waydroid kernel config options (android app support)
kconfig_options_waydroid = {
    ">=0.0.0": {  # all versions
        "all": {  # all arches
            "ANDROID_BINDERFS": False,
            "ANDROID_BINDER_DEVICES": ["binder", "hwbinder", "vndbinder"],
            "ANDROID_BINDER_IPC": True,
            "ANDROID_BINDER_IPC_SELFTEST": False,
            "BLK_DEV_LOOP": True,
            "BPF_SYSCALL": True,
            "BRIDGE": True,
            "BRIDGE_VLAN_FILTERING": True,
            "CGROUP_BPF": True,
            "FUSE_FS": True,
            "IP_NF_MANGLE": True,
            "NETFILTER_XTABLES": True,
            "NETFILTER_XT_MATCH_COMMENT": True,
            "PSI": True,
            "PSI_DEFAULT_DISABLED": False,
            "SQUASHFS": True,
            "SQUASHFS_XATTR": True,
            "SQUASHFS_XZ": True,
            "TMPFS_XATTR": True,
            "TUN": True,
            "VETH": True,
            "VLAN_8021Q": True,  # prerequisite for bridge
        }
    },
    ">=3.5": {
        "all": {
            "CROSS_MEMORY_ATTACH": True,
        }
    },
    ">=4.20.0": {
        "all": {
            "PSI": True,  # required by userspace OOM killer
            "PSI_DEFAULT_DISABLED": False,
        }
    },
    "<5.18": {  # option has been dropped
        "all": {
            "ASHMEM": True,
        }
    }
}

# Necessary iwd kernel config options (inet wireless daemon)
# Obtained from 'grep ADD_MISSING src/main.c' in iwd.git
kconfig_options_iwd = {
    ">=0.0.0": {  # all versions
        "all": {  # all arches
            "ASYMMETRIC_KEY_TYPE": True,
            "ASYMMETRIC_PUBLIC_KEY_SUBTYPE": True,
            "CRYPTO_AES": True,
            "CRYPTO_CBC": True,
            "CRYPTO_CMAC": True,
            "CRYPTO_DES": True,
            "CRYPTO_ECB": True,
            "CRYPTO_HMAC": True,
            "CRYPTO_MD5": True,
            "CRYPTO_SHA1": True,
            "CRYPTO_SHA256": True,
            "CRYPTO_SHA512": True,
            "CRYPTO_USER_API_HASH": True,
            "CRYPTO_USER_API_SKCIPHER": True,
            "KEYS": True,
            "KEY_DH_OPERATIONS": True,
            "PKCS7_MESSAGE_PARSER": True,
            "PKCS8_PRIVATE_KEY_PARSER": True,
            "X509_CERTIFICATE_PARSER": True,
            "RFKILL": True,
        },
    },
}

# Necessary nftables kernel config options (firewall)
kconfig_options_nftables = {
    ">=3.13.0": {  # nftables support introduced here
        "all": {  # all arches
            "NETFILTER": True,
            "NF_CONNTRACK": True,
            "NF_TABLES": True,
            "NF_TABLES_INET": True,
            "NFT_CT": True,
            "NFT_LOG": True,
            "NFT_LIMIT": True,
            "NFT_MASQ": True,
            "NFT_NAT": True,
            "NFT_REJECT": True,
            "NF_TABLES_IPV4": True,
            "NF_REJECT_IPV4": True,
            "IP_NF_IPTABLES": True,
            "IP_NF_FILTER": True,
            "IP_NF_TARGET_REJECT": True,
            "IP_NF_NAT": True,
            "NF_TABLES_IPV6": True,
            "NF_REJECT_IPV6": True,
            "IP6_NF_IPTABLES": True,
            "IP6_NF_FILTER": True,
            "IP6_NF_TARGET_REJECT": True,
            "IP6_NF_NAT": True,
        }
    },
    ">=3.13.0 <5.17": {  # option has been dropped
        "all": {  # all arches
            "NFT_COUNTER": True,
        },
    },
}

# Necessary kernel config options for containers (lxc, Docker)
kconfig_options_containers = {
    ">=0.0.0": {  # all versions, more specifically - since >=2.5~2.6
        "all": {  # all arches
            "NAMESPACES": True,
            "NET_NS": True,
            "PID_NS": True,
            "IPC_NS": True,
            "UTS_NS": True,
            "CGROUPS": True,
            "CGROUP_CPUACCT": True,
            "CGROUP_DEVICE": True,
            "CGROUP_FREEZER": True,
            "CGROUP_SCHED": True,
            "CPUSETS": True,
            "KEYS": True,
            "VETH": True,
            "BRIDGE": True,  # (also needed for waydroid)
            "BRIDGE_NETFILTER": True,
            "IP_NF_FILTER": True,
            "IP_NF_TARGET_MASQUERADE": True,
            "NETFILTER_XT_MATCH_ADDRTYPE": True,
            "NETFILTER_XT_MATCH_CONNTRACK": True,
            "NETFILTER_XT_MATCH_IPVS": True,
            "NETFILTER_XT_MARK": True,
            "NETFILTER_XT_TARGET_CHECKSUM": True,  # Needed for lxc
            "IP_NF_NAT": True,
            "NF_NAT": True,
            "POSIX_MQUEUE": True,
            "BLK_DEV_DM": True,  # Storage Drivers
            "DUMMY": True,  # Network Drivers
            # "USER_NS": True,  # This is already in pmOS kconfig check
            "BLK_CGROUP": True,  # Optional section
            "BLK_DEV_THROTTLING": True,  # Optional section
            "CGROUP_PERF": True,  # Optional section
            "NET_CLS_CGROUP": True,  # Optional section
            "FAIR_GROUP_SCHED": True,  # Optional section
            "RT_GROUP_SCHED": True,  # Optional section
            "IP_NF_TARGET_REDIRECT": True,  # Optional section
            "IP_VS": True,  # Optional section
            "IP_VS_NFCT": True,  # Optional section
            "IP_VS_PROTO_TCP": True,  # Optional section
            "IP_VS_PROTO_UDP": True,  # Optional section
            "IP_VS_RR": True,  # Optional section
            # "EXT4_FS": True,  # This is already in pmOS kconfig check
            "EXT4_FS_POSIX_ACL": True,  # Optional section
            "EXT4_FS_SECURITY": True,  # Optional section
        }
    },
    ">=3.2": {
        "all": {
            "CFS_BANDWIDTH": True,  # Optional section
        }
    },
    ">=3.3": {
        "all": {  # all arches
            "CHECKPOINT_RESTORE": True,  # Needed for lxc
        }
    },
    ">=3.6": {
        "all": {  # all arches
            "MEMCG": True,
            "DM_THIN_PROVISIONING": True,  # Storage Drivers
            "SWAP": True,
        },
        "x86 x86_64": {  # only for x86, x86_64 (and sparc64, ia64)
            "HUGETLB_PAGE": True,
            "CGROUP_HUGETLB": True,  # Optional section
        }
    },
    ">=3.6 <6.1_rc1": {  # option has been dropped
        "all": {
            "MEMCG_SWAP": True,
        }
    },
    ">=3.7 <5.0": {
        "all": {
            "NF_NAT_IPV4": True,  # Needed for lxc
            "NF_NAT_IPV6": True,  # Needed for lxc
        },
    },
    ">=3.7": {
        "all": {  # all arches
            "VXLAN": True,  # Network Drivers
            "IP6_NF_TARGET_MASQUERADE": True,  # Needed for lxc
        }
    },
    ">=3.9": {
        "all": {  # all arches
            "BRIDGE_VLAN_FILTERING": True,  # Network Drivers (also for waydroid)
            "MACVLAN": True,  # Network Drivers
        }
    },
    ">=3.13": {
        "all": { # needed for iptables-nft (used by docker,tailscale)
            "NFT_COMPAT": True,
        }
    },
    ">=3.14": {
        "all": {  # all arches
            "CGROUP_NET_PRIO": True,  # Optional section
        }
    },
    ">=3.18": {
        "all": {  # all arches
            "OVERLAY_FS": True,  # Storage Drivers
        }
    },
    ">=3.19": {
        "all": {  # all arches
            "IPVLAN": True,  # Network Drivers
            "SECCOMP": True,  # Optional section
        }
    },
    ">=4.4": {
        "all": {  # all arches
            "CGROUP_PIDS": True,  # Optional section
        }
    },
}

# Necessary zram kernel config options (RAM disk with on-the-fly compression)
kconfig_options_zram = {
    ">=3.14.0": {  # zram support introduced here
        "all": {  # all arches
            "ZRAM": True,
            "ZSMALLOC": True,
            "CRYPTO_LZ4": True,
            "LZ4_COMPRESS": True,
            "SWAP": True,
        }
    },
}

# Necessary netboot kernel config options
kconfig_options_netboot = {
    ">=0.0.0": {  # all versions
        "all": {  # all arches
            "BLK_DEV_NBD": True,
        }
    },
}

# Necessary wireguard & wg-quick kernel config options
# From https://gitweb.gentoo.org/repo/gentoo.git/tree/net-vpn/wireguard-tools/wireguard-tools-1.0.20210914.ebuild?id=76aaa1eeb6f001baaa68e6946f917ebb091bbd9d # noqa
kconfig_options_wireguard = {
    ">=5.6_rc1": {  # all versions
        "all": {  # all arches
            "WIREGUARD": True,
            "IP_ADVANCED_ROUTER": True,
            "IP_MULTIPLE_TABLES": True,
            "IPV6_MULTIPLE_TABLES": True,
            "NF_TABLES": True,
            "NF_TABLES_IPV4": True,
            "NF_TABLES_IPV6": True,
            "NFT_CT": True,
            "NFT_FIB": True,
            "NFT_FIB_IPV4": True,
            "NFT_FIB_IPV6": True,
            "NF_CONNTRACK_MARK": True,
        },
    },
}

# Necessary file system config options
kconfig_options_filesystems = {
    ">=0.0.0": {  # all versions
        "all": {  # all arches
            "BTRFS_FS": True,
            "EXFAT_FS": True,
            "EXT4_FS": True,
            "F2FS_FS": True,
        },
    },
}

kconfig_options_usb_gadgets = {
    ">=0.0.0": {  # all versions
        "all": {  # all arches
            # disable legacy gadgets
            "USB_ETH": False,
            "USB_FUNCTIONFS": False,
            "USB_MASS_STORAGE": False,
            "USB_G_SERIAL": False,
            # enable configfs gadgets
            "USB_CONFIGFS_NCM": True,  # USB networking via NCM
            "USB_CONFIGFS_RNDIS": True,  # USB networking via RNDIS (legacy)
        },
    },
}

# Various other kernel config options
kconfig_options_community = {
    ">=0.0.0": {  # all versions
        "all": {  # all arches
            "BINFMT_MISC": True,  # register binary formats
            "CIFS": True,  # mount SMB shares
            "INPUT_UINPUT": True,  # buffyboard
            "LEDS_TRIGGER_PATTERN": True,  # feedbackd
            "LEDS_TRIGGER_TIMER": True,  # hfd-service
            "NETFILTER_XT_MATCH_STATISTIC": True,  # kube-proxy
            "NETFILTER_XT_MATCH_TCPMSS": True,  # change MTU, e.g. for Wireguard
            "NETFILTER_XT_TARGET_TCPMSS": True,  # change MTU, e.g. for Wireguard
            # TODO: Depends on SUSPEND which is not enabled for some devices
            # "PM_WAKELOCKS": True,  # Sxmo
            "SND_USB_AUDIO": True,  # USB audio devices
            "UCLAMP_TASK": True,  # Scheduler hints
            "UCLAMP_TASK_GROUP": True,  # Scheduler hints
            "UHID": True,  # e.g. Bluetooth input devices
        },
    },
}

# Necessary UEFI boot config options
kconfig_options_uefi = {
    ">=0.0.0": {  # all versions
        "all": {  # all arches
            "EFI_STUB": True,
            "EFI": True,
            "DMI": True,
            "EFI_ESRT": True,
            "EFI_VARS_PSTORE": True,
            "EFI_PARAMS_FROM_FDT": True,
            "EFI_RUNTIME_WRAPPERS": True,
            "EFI_GENERIC_STUB": True,
        },
        "x86_64": {
            "EFI_MIXED": True,
        },
    },
    ">=6.1.0": {
        "aarch64": {
            # Required EFI booting compressed kernels on this arch
            "EFI_ZBOOT": True,
        },
    },
}

#
# PARSE
#

# Variables belonging to a package or subpackage in APKBUILD files
apkbuild_package_attributes = {
    "pkgdesc": {},
    "depends": {"array": True},
    "provides": {"array": True},
    "provider_priority": {"int": True},
    "install": {"array": True},
    "triggers": {"array": True},

    # Packages can specify soft dependencies in "_pmb_recommends" to be
    # explicitly installed by default, and not implicitly as a hard dependency
    # of the package ("depends"). This makes these apps uninstallable, without
    # removing the meta-package. (#1933). To disable this feature, use:
    # "pmbootstrap install --no-recommends".
    "_pmb_recommends": {"array": True},

    # UI meta-packages can specify groups to which the user must be added
    # to access specific hardware such as LED indicators.
    "_pmb_groups": {"array": True},

    # postmarketos-base, UI and device packages can use _pmb_select to provide
    # additional configuration options in "pmbootstrap init" that allow
    # selecting alternative providers for a virtual APK package.
    "_pmb_select": {"array": True},
}

# Variables in APKBUILD files that get parsed
apkbuild_attributes = {
    **apkbuild_package_attributes,

    "arch": {"array": True},
    "depends_dev": {"array": True},
    "makedepends": {"array": True},
    "checkdepends": {"array": True},
    "options": {"array": True},
    "triggers": {"array": True},
    "pkgname": {},
    "pkgrel": {},
    "pkgver": {},
    "subpackages": {},
    "url": {},

    # cross-compilers
    "makedepends_build": {"array": True},
    "makedepends_host": {"array": True},

    # kernels
    "_flavor": {},
    "_device": {},
    "_kernver": {},
    "_outdir": {},
    "_config": {},

    # linux-edge
    "_depends_dev": {"array": True},

    # mesa
    "_llvmver": {},

    # Overridden packages
    "_pkgver": {},
    "_pkgname": {},

    # git commit
    "_commit": {},
    "source": {"array": True},

    # gcc
    "_pkgbase": {},
    "_pkgsnap": {}
}

# Reference: https://postmarketos.org/apkbuild-options
apkbuild_custom_valid_options = [
    "!pmb:crossdirect",
    "!pmb:kconfigcheck",
    "pmb:kconfigcheck-community",
    "pmb:kconfigcheck-containers",
    "pmb:kconfigcheck-iwd",
    "pmb:kconfigcheck-netboot",
    "pmb:kconfigcheck-nftables",
    "pmb:kconfigcheck-uefi",
    "pmb:kconfigcheck-waydroid",
    "pmb:kconfigcheck-zram",
    "pmb:cross-native",
    "pmb:gpu-accel",
    "pmb:strict",
]

# Variables from deviceinfo. Reference: <https://postmarketos.org/deviceinfo>
deviceinfo_attributes = [
    # general
    "format_version",
    "name",
    "manufacturer",
    "codename",
    "year",
    "dtb",
    "arch",

    # device
    "chassis",
    "keyboard",
    "external_storage",
    "dev_touchscreen",
    "dev_touchscreen_calibration",
    "append_dtb",

    # bootloader
    "flash_method",
    "boot_filesystem",

    # flash
    "flash_heimdall_partition_kernel",
    "flash_heimdall_partition_initfs",
    "flash_heimdall_partition_rootfs",
    "flash_heimdall_partition_system", # deprecated
    "flash_heimdall_partition_vbmeta",
    "flash_heimdall_partition_dtbo",
    "flash_fastboot_partition_kernel",
    "flash_fastboot_partition_rootfs",
    "flash_fastboot_partition_system", # deprecated
    "flash_fastboot_partition_vbmeta",
    "flash_fastboot_partition_dtbo",
    "flash_rk_partition_kernel",
    "flash_rk_partition_rootfs",
    "flash_rk_partition_system", # deprecated
    "flash_mtkclient_partition_kernel",
    "flash_mtkclient_partition_rootfs",
    "flash_mtkclient_partition_vbmeta",
    "flash_mtkclient_partition_dtbo",
    "generate_legacy_uboot_initfs",
    "kernel_cmdline",
    "generate_bootimg",
    "header_version",
    "bootimg_qcdt",
    "bootimg_mtk_mkimage", # deprecated
    "bootimg_mtk_label_kernel",
    "bootimg_mtk_label_ramdisk",
    "bootimg_dtb_second",
    "bootimg_custom_args",
    "flash_offset_base",
    "flash_offset_dtb",
    "flash_offset_kernel",
    "flash_offset_ramdisk",
    "flash_offset_second",
    "flash_offset_tags",
    "flash_pagesize",
    "flash_fastboot_max_size",
    "flash_sparse",
    "flash_sparse_samsung_format",
    "rootfs_image_sector_size",
    "sd_embed_firmware",
    "sd_embed_firmware_step_size",
    "partition_blacklist",
    "boot_part_start",
    "partition_type",
    "root_filesystem",
    "flash_kernel_on_update",
    "cgpt_kpart",
    "cgpt_kpart_start",
    "cgpt_kpart_size",

    # weston
    "weston_pixman_type",

    # keymaps
    "keymaps",
]

# Valid types for the 'chassis' attribute in deviceinfo
# See https://www.freedesktop.org/software/systemd/man/machine-info.html
deviceinfo_chassis_types = [
    "desktop",
    "laptop",
    "convertible",
    "server",
    "tablet",
    "handset",
    "watch",
    "embedded",
    "vm"
]

#
# INITFS
#
initfs_hook_prefix = "postmarketos-mkinitfs-hook-"
default_ip = "172.16.42.1"


#
# INSTALL
#

# Packages that will be installed inside the native chroot to perform
# the installation to the device.
# util-linux: losetup, fallocate
install_native_packages = ["cryptsetup", "util-linux", "parted"]
install_device_packages = ["postmarketos-base"]

#
# FLASH
#

flash_methods = [
    "0xffff",
    "fastboot",
    "heimdall",
    "mtkclient",
    "none",
    "rkdeveloptool",
    "uuu",
]

# These folders will be mounted at the same location into the native
# chroot, before the flash programs get started.
flash_mount_bind = [
    "/sys/bus/usb/devices/",
    "/sys/dev/",
    "/sys/devices/",
    "/dev/bus/usb/"
]

"""
Flasher abstraction. Allowed variables:

$BOOT: Path to the /boot partition
$DTB: Set to "-dtb" if deviceinfo_append_dtb is set, otherwise ""
$FLAVOR: Backwards compatibility with old mkinitfs (pma#660)
$IMAGE: Path to the combined boot/rootfs image
$IMAGE_SPLIT_BOOT: Path to the (split) boot image
$IMAGE_SPLIT_ROOT: Path to the (split) rootfs image
$PARTITION_KERNEL: Partition to flash the kernel/boot.img to
$PARTITION_ROOTFS: Partition to flash the rootfs to

Fastboot specific: $KERNEL_CMDLINE
Heimdall specific: $PARTITION_INITFS
uuu specific: $UUU_SCRIPT
"""
flashers = {
    "fastboot": {
        "depends": [],  # pmaports.cfg: supported_fastboot_depends
        "actions": {
            "list_devices": [["fastboot", "devices", "-l"]],
            "flash_rootfs": [["fastboot", "flash", "$PARTITION_ROOTFS",
                              "$IMAGE"]],
            "flash_kernel": [["fastboot", "flash", "$PARTITION_KERNEL",
                              "$BOOT/boot.img$FLAVOR"]],
            "flash_vbmeta": [
                # Generate vbmeta image with "disable verification" flag
                ["avbtool", "make_vbmeta_image", "--flags", "2",
                    "--padding_size", "$FLASH_PAGESIZE",
                    "--output", "/vbmeta.img"],
                ["fastboot", "flash", "$PARTITION_VBMETA", "/vbmeta.img"],
                ["rm", "-f", "/vbmeta.img"]
            ],
            "flash_dtbo": [["fastboot", "flash", "$PARTITION_DTBO",
                            "$BOOT/dtbo.img"]],
            "boot": [["fastboot", "--cmdline", "$KERNEL_CMDLINE",
                      "boot", "$BOOT/boot.img$FLAVOR"]],
            "flash_lk2nd": [["fastboot", "flash", "$PARTITION_KERNEL",
                             "$BOOT/lk2nd.img"]]
        },
    },
    # Some devices provide Fastboot but using Android boot images is not
    # practical for them (e.g. because they support booting from FAT32
    # partitions directly and/or the Android boot partition is too small).
    # This can be implemented using --split (separate image files for boot and
    # rootfs).
    # This flasher allows flashing the split image files using Fastboot.
    "fastboot-bootpart": {
        "split": True,
        "depends": ["android-tools"],
        "actions": {
            "list_devices": [["fastboot", "devices", "-l"]],
            "flash_rootfs": [["fastboot", "flash", "$PARTITION_ROOTFS",
                              "$IMAGE_SPLIT_ROOT"]],
            "flash_kernel": [["fastboot", "flash", "$PARTITION_KERNEL",
                              "$IMAGE_SPLIT_BOOT"]],
            # TODO: Add support for boot
        },
    },
    # Some Samsung devices need the initramfs to be baked into the kernel (e.g.
    # i9070, i9100). We want the initramfs to be generated after the kernel was
    # built, so we put the real initramfs on another partition (e.g. RECOVERY)
    # and load it from the initramfs in the kernel. This method is called
    # "isorec" (isolated recovery), a term coined by Lanchon.
    "heimdall-isorec": {
        "depends": ["heimdall"],
        "actions": {
            "list_devices": [["heimdall", "detect"]],
            "flash_rootfs": [
                ["heimdall_wait_for_device.sh"],
                ["heimdall", "flash", "--$PARTITION_ROOTFS", "$IMAGE"]],
            "flash_kernel": [["heimdall_flash_kernel.sh",
                              "$BOOT/initramfs$FLAVOR", "$PARTITION_INITFS",
                              "$BOOT/vmlinuz$FLAVOR$DTB",
                              "$PARTITION_KERNEL"]]
        },
    },
    # Some Samsung devices need a 'boot.img' file, just like the one generated
    # fastboot compatible devices. Example: s7562, n7100
    "heimdall-bootimg": {
        "depends": [],  # pmaports.cfg: supported_heimdall_depends
        "actions": {
            "list_devices": [["heimdall", "detect"]],
            "flash_rootfs": [
                ["heimdall_wait_for_device.sh"],
                ["heimdall", "flash", "--$PARTITION_ROOTFS", "$IMAGE",
                 "$NO_REBOOT", "$RESUME"]],
            "flash_kernel": [
                ["heimdall_wait_for_device.sh"],
                ["heimdall", "flash", "--$PARTITION_KERNEL",
                 "$BOOT/boot.img$FLAVOR", "$NO_REBOOT", "$RESUME"]],
            "flash_vbmeta": [
                ["avbtool", "make_vbmeta_image", "--flags", "2",
                    "--padding_size", "$FLASH_PAGESIZE",
                    "--output", "/vbmeta.img"],
                ["heimdall", "flash", "--$PARTITION_VBMETA", "/vbmeta.img",
                 "$NO_REBOOT", "$RESUME"],
                ["rm", "-f", "/vbmeta.img"]],
            "flash_lk2nd": [
                ["heimdall_wait_for_device.sh"],
                ["heimdall", "flash", "--$PARTITION_KERNEL", "$BOOT/lk2nd.img",
                 "$NO_REBOOT", "$RESUME"]]
        },
    },
    "adb": {
        "depends": ["android-tools"],
        "actions": {
            "list_devices": [["adb", "-P", "5038", "devices"]],
            "sideload": [["echo", "< wait for any device >"],
                         ["adb", "-P", "5038", "wait-for-usb-sideload"],
                         ["adb", "-P", "5038", "sideload",
                          "$RECOVERY_ZIP"]],
        }
    },
    "uuu": {
        "depends": ["nxp-mfgtools-uuu"],
        "actions": {
            "flash_rootfs": [
                # There's a bug(?) in uuu where it clobbers the path in the cmd
                # script if the script is not in pwd...
                ["cp", "$UUU_SCRIPT", "./flash_script.lst"],
                ["uuu", "flash_script.lst"],
            ],
        },
    },
    "rkdeveloptool": {
        "split": True,
        "depends": ["rkdeveloptool"],
        "actions": {
            "list_devices": [["rkdeveloptool", "list"]],
            "flash_rootfs": [
                ["rkdeveloptool", "write-partition", "$PARTITION_ROOTFS",
                    "$IMAGE_SPLIT_ROOT"]
            ],
            "flash_kernel": [
                ["rkdeveloptool", "write-partition", "$PARTITION_KERNEL",
                    "$IMAGE_SPLIT_BOOT"]
            ],
        },
    },
    "mtkclient": {
        "depends": ["mtkclient"],
        "actions": {
            "flash_rootfs": [["mtk", "w", "$PARTITION_ROOTFS",
                              "$IMAGE"]],
            "flash_kernel": [["mtk", "w", "$PARTITION_KERNEL",
                              "$BOOT/boot.img$FLAVOR"]],
            "flash_vbmeta": [
                # Generate vbmeta image with "disable verification" flag
                ["avbtool", "make_vbmeta_image", "--flags", "2",
                    "--padding_size", "$FLASH_PAGESIZE",
                    "--output", "/vbmeta.img"],
                ["mtk", "w", "$PARTITION_VBMETA", "/vbmeta.img"],
                ["rm", "-f", "/vbmeta.img"]
            ],
            "flash_dtbo": [["mtk", "w", "$PARTITION_DTBO",
                            "$BOOT/dtbo.img"]],
            "flash_lk2nd": [["mtk", "w", "$PARTITION_KERNEL",
                             "$BOOT/lk2nd.img"]]
        }
    }
}

#
# GIT
#
git_repos = {
    "aports_upstream": "https://gitlab.alpinelinux.org/alpine/aports.git",
    "pmaports": "https://gitlab.com/postmarketOS/pmaports.git",
}

# When a git repository is considered outdated (in seconds)
# (Measuring timestamp of FETCH_HEAD: https://stackoverflow.com/a/9229377)
git_repo_outdated = 3600 * 24 * 2

#
# APORTGEN
#
aportgen = {
    "cross": {
        "prefixes": ["busybox-static", "gcc", "musl", "grub-efi"],
        "confirm_overwrite": False,
    },
    "device/testing": {
        "prefixes": ["device", "linux"],
        "confirm_overwrite": True,
    }
}

# Use a deterministic mirror URL instead of CDN for aportgen. Otherwise we may
# generate a pmaport that wraps an apk from Alpine (e.g. musl-armv7) locally
# with one up-to-date mirror given by the CDN. But then the build will fail if
# CDN picks an outdated mirror for CI or BPO.
aportgen_mirror_alpine = "http://dl-4.alpinelinux.org/alpine/"

#
# NEWAPKBUILD
# Options passed through to the "newapkbuild" command from Alpine Linux. They
# are duplicated here, so we can use Python's argparse for argument parsing and
# help page display. The -f (force) flag is not defined here, as we use that in
# the Python code only and don't pass it through.
#
newapkbuild_arguments_strings = [
    ["-n", "pkgname", "set package name (only use with SRCURL)"],
    ["-d", "pkgdesc", "set package description"],
    ["-l", "license", "set package license identifier from"
                      " <https://spdx.org/licenses/>"],
    ["-u", "url", "set package URL"],
]
newapkbuild_arguments_switches_pkgtypes = [
    ["-a", "autotools", "create autotools package (use ./configure ...)"],
    ["-C", "cmake", "create CMake package (assume cmake/ is there)"],
    ["-m", "meson", "create meson package (assume meson.build is there)"],
    ["-p", "perl", "create perl package (assume Makefile.PL is there)"],
    ["-y", "python", "create python package (assume setup.py is there)"],
    ["-e", "python_gpep517", "create python package (assume pyproject.toml is there)"],
    ["-r", "rust", "create rust package (assume Cargo.toml is there)"],
]
newapkbuild_arguments_switches_other = [
    ["-s", "sourceforge", "use sourceforge source URL"],
    ["-c", "copy_samples", "copy a sample init.d, conf.d and install script"],
]

#
# UPGRADE
#
# Patterns of package names to ignore for automatic pmaport upgrading
# ("pmbootstrap aportupgrade --all")
upgrade_ignore = ["device-*", "firmware-*", "linux-*", "postmarketos-*",
                  "*-aarch64", "*-armhf", "*-armv7", "*-riscv64"]

#
# SIDELOAD
#
sideload_sudo_prompt = "[sudo] password for %u@%h: "

#
# CI
#
# Valid options for 'pmbootstrap ci', see https://postmarketos.org/pmb-ci
ci_valid_options = ["native", "slow"]
