# pmbootstrap

Sophisticated chroot/build/flash tool to develop and install
[postmarketOS](https://postmarketos.org).

## Development

Find the location of the upstream repository for pmbootstrap on the
[postmarketOS homepage](https://postmarketos.org/source-code/).

Run CI scripts locally with:
```
$ pmbootstrap ci
```

Run a single test file:
```
$ pytest -vv ./test/test_keys.py
```

## Issues

Issues are being tracked
[here](https://gitlab.com/postmarketOS/pmbootstrap/-/issues).

## Requirements
* Linux distribution on the host system (`x86`, `x86_64`, `aarch64` or `armv7`)
  * [Windows subsystem for Linux (WSL)](https://en.wikipedia.org/wiki/Windows_Subsystem_for_Linux)
    does **not** work! Please use [VirtualBox](https://www.virtualbox.org/) instead.
  * [Linux kernel 3.17 or higher](https://postmarketos.org/oldkernel)
  * Note: kernel versions between 5.8.8 and 6.0 might 
    [have issues with parted](https://gitlab.com/postmarketOS/pmbootstrap/-/issues/2309).
* Python 3.7+
* OpenSSL
* git
* ps
* tar

## Usage Examples
Please refer to the [postmarketOS wiki](https://wiki.postmarketos.org) for
in-depth coverage of topics such as
[porting to a new device](https://wiki.postmarketos.org/wiki/Porting_to_a_new_device)
or [installation](https://wiki.postmarketos.org/wiki/Installation_guide). The
help output (`pmbootstrap -h`) has detailed usage instructions for every
command. Read on for some generic examples of what can be done with
`pmbootstrap`.

### Installing pmbootstrap
<https://wiki.postmarketos.org/wiki/Installing_pmbootstrap>

### Basics
Initial setup:
```
$ pmbootstrap init
```

Run this in a second window to see all shell commands that get executed:
```
$ pmbootstrap log
```

Quick health check and config overview:
```
$ pmbootstrap status
```

### Packages
Build `aports/main/hello-world`:
```
$ pmbootstrap build hello-world
```

Cross-compile to `armhf`:
```
$ pmbootstrap build --arch=armhf hello-world
```

Build with source code from local folder:
```
$ pmbootstrap build linux-postmarketos-mainline --src=~/code/linux
```

Update checksums:
```
$ pmbootstrap checksum hello-world
```

Generate a template for a new package:
```
$ pmbootstrap newapkbuild "https://gitlab.com/postmarketOS/osk-sdl/-/archive/0.52/osk-sdl-0.52.tar.bz2"
```

#### Default architecture

Packages will be compiled for the architecture of the device running
pmbootstrap by default. For example, if your `x86_64` PC runs pmbootstrap, it
would build a package for `x86_64` with this command:
```
$ pmbootstrap build hello-world
```

If you would rather build for the target device selected in `pmbootstrap init`
by default, then use the `build_default_device_arch` option:
```
$ pmbootstrap config build_default_device_arch True
```

If your target device is `pine64-pinephone` for example, pmbootstrap will now
build this package for `aarch64`:
```
$ pmbootstrap build hello-world
```

### Chroots
Enter the `armhf` building chroot:
```
$ pmbootstrap chroot -b armhf
```

Run a command inside a chroot:
```
$ pmbootstrap chroot -- echo test
```

Safely delete all chroots:
```
$ pmbootstrap zap
```

### Device Porting Assistance
Analyze Android
[`boot.img`](https://wiki.postmarketos.org/wiki/Glossary#boot.img) files (also
works with recovery OS images like TWRP):
```
$ pmbootstrap bootimg_analyze ~/Downloads/twrp-3.2.1-0-fp2.img
```

Check kernel configs:
```
$ pmbootstrap kconfig check
```

Edit a kernel config:
```
$ pmbootstrap kconfig edit --arch=armhf postmarketos-mainline
```

### Root File System
Build the rootfs:
```
$ pmbootstrap install
```

Build the rootfs with full disk encryption:
```
$ pmbootstrap install --fde
```

Update existing installation on SD card:
```
$ pmbootstrap install --disk=/dev/mmcblk0 --rsync
```

Run the image in QEMU:
```
$ pmbootstrap qemu --image-size=1G
```

Flash to the device:
```
$ pmbootstrap flasher flash_kernel
$ pmbootstrap flasher flash_rootfs --partition=userdata
```

Export the rootfs, kernel, initramfs, `boot.img` etc.:
```
$ pmbootstrap export
```

Extract the initramfs
```
$ pmbootstrap initfs extract
```

Build and flash Android recovery zip:
```
$ pmbootstrap install --android-recovery-zip
$ pmbootstrap flasher --method=adb sideload
```

### Repository Maintenance
List pmaports that don't have a binary package:
```
$ pmbootstrap repo_missing --arch=armhf --overview
```

Increase the `pkgrel` for each aport where the binary package has outdated
dependencies (e.g. after soname bumps):
```
$ pmbootstrap pkgrel_bump --auto
```

Generate cross-compiler aports based on the latest version from Alpine's
aports:
```
$ pmbootstrap aportgen gcc-armhf
```

Manually rebuild package index:
```
$ pmbootstrap index
```

Delete local binary packages without existing aport of same version:
```
$ pmbootstrap zap -m
```

### Debugging
Use `-v` on any action to get verbose logging:
```
$ pmbootstrap -v build hello-world
```

Parse a single deviceinfo and return it as JSON:
```
$ pmbootstrap deviceinfo_parse pine64-pinephone
```

Parse a single APKBUILD and return it as JSON:
```
$ pmbootstrap apkbuild_parse hello-world
```

Parse a package from an APKINDEX and return it as JSON:
```
$ pmbootstrap apkindex_parse $WORK/cache_apk_x86_64/APKINDEX.8b865e19.tar.gz hello-world
```

`ccache` statistics:
```
$ pmbootstrap stats --arch=armhf
```

### Use alternative sudo

pmbootstrap supports `doas` and `sudo`.
If multiple sudo implementations are installed, pmbootstrap will use `doas`.
You can set the `PMB_SUDO` environmental variable to define the sudo
implementation you want to use.

### Select SSH keys to include and make authorized in new images

If the config file option `ssh_keys` is set to `True` (it defaults to `False`),
then all files matching the glob `~/.ssh/id_*.pub` will be placed in
`~/.ssh/authorized_keys` in the user's home directory in newly-built images.

Sometimes, for example if you have a large number of SSH keys, you may wish to
select a different set of public keys to include in an image. To do this, set
the `ssh_key_glob` configuration parameter in the pmbootstrap config file to a
string containing a glob that is to match the file or files you wish to
include.

For example, a `~/.config/pmbootstrap.cfg` may contain:

    [pmbootstrap]
    # ...
    ssh_keys = True
    ssh_key_glob = ~/.ssh/postmarketos-dev.pub
    # ...

## License
[GPLv3](LICENSE)
