# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import logging
import glob
import json
import os
import shutil

import pmb.aportgen
import pmb.config
import pmb.config.pmaports
import pmb.helpers.cli
import pmb.helpers.devices
import pmb.helpers.git
import pmb.helpers.http
import pmb.helpers.logging
import pmb.helpers.other
import pmb.helpers.pmaports
import pmb.helpers.run
import pmb.helpers.ui
import pmb.chroot.zap
import pmb.parse.deviceinfo
import pmb.parse._apkbuild


def require_programs():
    missing = []
    for program in pmb.config.required_programs:
        if not shutil.which(program):
            missing.append(program)
    if missing:
        raise RuntimeError("Can't find all programs required to run"
                           " pmbootstrap. Please install first:"
                           f" {', '.join(missing)}")


def ask_for_username(args):
    """
    Ask for a reasonable username for the non-root user.

    :returns: the username
    """
    while True:
        ret = pmb.helpers.cli.ask("Username", None, args.user, False,
                                  "[a-z_][a-z0-9_-]*")
        if ret == "root":
            logging.fatal("ERROR: don't put \"root\" here. This is about"
                          " creating an additional non-root user. Don't worry,"
                          " the root user will also be created ;)")
            continue
        return ret


def ask_for_work_path(args):
    """
    Ask for the work path, until we can create it (when it does not exist) and
    write into it.
    :returns: (path, exists)
              * path: is the full path, with expanded ~ sign
              * exists: is False when the folder did not exist before we tested
                        whether we can create it
    """
    logging.info("Location of the 'work' path. Multiple chroots"
                 " (native, device arch, device rootfs) will be created"
                 " in there.")
    while True:
        try:
            work = os.path.expanduser(pmb.helpers.cli.ask(
                "Work path", None, args.work, False))
            work = os.path.realpath(work)
            exists = os.path.exists(work)

            # Work must not be inside the pmbootstrap path
            if (work == pmb.config.pmb_src or
                    work.startswith(f"{pmb.config.pmb_src}/")):
                logging.fatal("ERROR: The work path must not be inside the"
                              " pmbootstrap path. Please specify another"
                              " location.")
                continue

            # Create the folder with a version file
            if not exists:
                os.makedirs(work, 0o700, True)

            # If the version file doesn't exists yet because we either just
            # created the work directory or the user has deleted it for
            # whatever reason then we need to write initialize it.
            work_version_file = f"{work}/version"
            if not os.path.isfile(work_version_file):
                with open(work_version_file, "w") as handle:
                    handle.write(f"{pmb.config.work_version}\n")

            # Create cache_git dir, so it is owned by the host system's user
            # (otherwise pmb.helpers.mount.bind would create it as root)
            os.makedirs(f"{work}/cache_git", 0o700, True)
            return (work, exists)
        except OSError:
            logging.fatal("ERROR: Could not create this folder, or write"
                          " inside it! Please try again.")


def ask_for_channel(args):
    """ Ask for the postmarketOS release channel. The channel dictates, which
        pmaports branch pmbootstrap will check out, and which repository URLs
        will be used when initializing chroots.
        :returns: channel name (e.g. "edge", "v21.03") """
    channels_cfg = pmb.helpers.git.parse_channels_cfg(args)
    count = len(channels_cfg["channels"])

    # List channels
    logging.info("Choose the postmarketOS release channel.")
    logging.info(f"Available ({count}):")
    # Only show the first 3 releases. This includes edge, the latest supported
    # release plus one. Should be a good solution until new needs arrive when
    # we might want to have a custom channels.cfg attribute.
    for channel, channel_data in list(channels_cfg["channels"].items())[:3]:
        logging.info(f"* {channel}: {channel_data['description']}")

    # Default for first run: "recommended" from channels.cfg
    # Otherwise, if valid: channel from pmaports.cfg of current branch
    # The actual channel name is not saved in pmbootstrap.cfg, because then we
    # would need to sync it with what is checked out in pmaports.git.
    default = pmb.config.pmaports.read_config(args)["channel"]
    choices = channels_cfg["channels"].keys()
    if args.is_default_channel or default not in choices:
        default = channels_cfg["meta"]["recommended"]

    # Ask until user gives valid channel
    while True:
        ret = pmb.helpers.cli.ask("Channel", None, default,
                                  complete=choices)
        if ret in choices:
            return ret
        logging.fatal("ERROR: Invalid channel specified, please type in one"
                      " from the list above.")


def ask_for_ui(args, info):
    ui_list = pmb.helpers.ui.list(args, info["arch"])
    hidden_ui_count = 0
    device_is_accelerated = info.get("gpu_accelerated") == "true"
    if not device_is_accelerated:
        for i in reversed(range(len(ui_list))):
            pkgname = f"postmarketos-ui-{ui_list[i][0]}"
            apkbuild = pmb.helpers.pmaports.get(args, pkgname,
                                                subpackages=False,
                                                must_exist=False)
            if apkbuild and "pmb:gpu-accel" in apkbuild["options"]:
                ui_list.pop(i)
                hidden_ui_count += 1

    # Get default
    default = args.ui
    if default not in dict(ui_list).keys():
        default = pmb.config.defaults["ui"]

    logging.info(f"Available user interfaces ({len(ui_list) - 1}): ")
    ui_completion_list = []
    for ui in ui_list:
        logging.info(f"* {ui[0]}: {ui[1]}")
        ui_completion_list.append(ui[0])
    if hidden_ui_count > 0:
        logging.info(f"NOTE: {hidden_ui_count} UIs are hidden because"
                     " \"deviceinfo_gpu_accelerated\" is not set (see"
                     " https://postmarketos.org/deviceinfo).")
    while True:
        ret = pmb.helpers.cli.ask("User interface", None, default, True,
                                  complete=ui_completion_list)
        if ret in dict(ui_list).keys():
            return ret
        logging.fatal("ERROR: Invalid user interface specified, please type in"
                      " one from the list above.")


def ask_for_ui_extras(args, ui):
    apkbuild = pmb.helpers.pmaports.get(args, f"postmarketos-ui-{ui}",
                                        subpackages=False, must_exist=False)
    if not apkbuild:
        return False

    extra = apkbuild["subpackages"].get(f"postmarketos-ui-{ui}-extras")
    if extra is None:
        return False

    logging.info("This user interface has an extra package:"
                 f" {extra['pkgdesc']}")

    return pmb.helpers.cli.confirm(args, "Enable this package?",
                                   default=args.ui_extras)


def ask_for_keymaps(args, info):
    if "keymaps" not in info or info["keymaps"].strip() == "":
        return ""
    options = info["keymaps"].split(' ')
    logging.info(f"Available keymaps for device ({len(options)}): "
                 f"{', '.join(options)}")
    if args.keymap == "":
        args.keymap = options[0]

    while True:
        ret = pmb.helpers.cli.ask("Keymap", None, args.keymap,
                                  True, complete=options)
        if ret in options:
            return ret
        logging.fatal("ERROR: Invalid keymap specified, please type in"
                      " one from the list above.")


def ask_for_timezone(args):
    localtimes = ["/etc/zoneinfo/localtime", "/etc/localtime"]
    zoneinfo_path = "/usr/share/zoneinfo/"
    for localtime in localtimes:
        if not os.path.exists(localtime):
            continue
        tz = ""
        if os.path.exists(localtime):
            tzpath = os.path.realpath(localtime)
            tzpath = tzpath.rstrip()
            if os.path.exists(tzpath):
                try:
                    _, tz = tzpath.split(zoneinfo_path)
                except:
                    pass
        if tz:
            logging.info(f"Your host timezone: {tz}")
            if pmb.helpers.cli.confirm(args,
                                       "Use this timezone instead of GMT?",
                                       default="y"):
                return tz
    logging.info("WARNING: Unable to determine timezone configuration on host,"
                 " using GMT.")
    return "GMT"


def ask_for_provider_select(args, apkbuild, providers_cfg):
    """
    Ask for selectable providers that are specified using "_pmb_select"
    in a APKBUILD.

    :param apkbuild: the APKBUILD with the _pmb_select
    :param providers_cfg: the configuration section with previously selected
                          providers. Updated with new providers after selection
    """
    for select in apkbuild["_pmb_select"]:
        providers = pmb.helpers.pmaports.find_providers(args, select)
        logging.info(f"Available providers for {select} ({len(providers)}):")

        has_default = False
        providers_short = {}
        last_selected = providers_cfg.get(select, 'default')

        for pkgname, pkg in providers:
            # Strip provider prefix if possible
            short = pkgname
            if short.startswith(f'{select}-'):
                short = short[len(f"{select}-"):]

            # Allow selecting the package using both short and long name
            providers_short[pkgname] = pkgname
            providers_short[short] = pkgname

            if pkgname == last_selected:
                last_selected = short

            if not has_default and pkg.get('provider_priority', 0) != 0:
                # Display as default provider
                styles = pmb.config.styles
                logging.info(f"* {short}: {pkg['pkgdesc']} "
                             f"{styles['BOLD']}(default){styles['END']}")
                has_default = True
            else:
                logging.info(f"* {short}: {pkg['pkgdesc']}")

        while True:
            ret = pmb.helpers.cli.ask("Provider", None, last_selected, True,
                                      complete=providers_short.keys())

            if has_default and ret == 'default':
                # Selecting default means to not select any provider explicitly
                # In other words, apk chooses it automatically based on
                # "provider_priority"
                if select in providers_cfg:
                    del providers_cfg[select]
                break
            if ret in providers_short:
                providers_cfg[select] = providers_short[ret]
                break
            logging.fatal("ERROR: Invalid provider specified, please type in"
                          " one from the list above.")


def ask_for_provider_select_pkg(args, pkgname, providers_cfg):
    """
    Look up the APKBUILD for the specified pkgname and ask for selectable
    providers that are specified using "_pmb_select".

    :param pkgname: name of the package to search APKBUILD for
    :param providers_cfg: the configuration section with previously selected
                          providers. Updated with new providers after selection
    """
    apkbuild = pmb.helpers.pmaports.get(args, pkgname,
                                        subpackages=False, must_exist=False)
    if not apkbuild:
        return

    ask_for_provider_select(args, apkbuild, providers_cfg)


def ask_for_device_kernel(args, device):
    """
    Ask for the kernel that should be used with the device.

    :param device: code name, e.g. "lg-mako"
    :returns: None if the kernel is hardcoded in depends without subpackages
    :returns: kernel type ("downstream", "stable", "mainline", ...)
    """
    # Get kernels
    kernels = pmb.parse._apkbuild.kernels(args, device)
    if not kernels:
        return args.kernel

    # Get default
    default = args.kernel
    if default not in kernels:
        default = list(kernels.keys())[0]

    # Ask for kernel (extra message when downstream and upstream are available)
    logging.info("Which kernel do you want to use with your device?")
    if "downstream" in kernels:
        logging.info("Downstream kernels are typically the outdated Android"
                     " kernel forks.")
    if "downstream" in kernels and len(kernels) > 1:
        logging.info("Upstream kernels (mainline, stable, ...) get security"
                     " updates, but may have less working features than"
                     " downstream kernels.")

    # List kernels
    logging.info(f"Available kernels ({len(kernels)}):")
    for type in sorted(kernels.keys()):
        logging.info(f"* {type}: {kernels[type]}")
    while True:
        ret = pmb.helpers.cli.ask("Kernel", None, default, True,
                                  complete=kernels)
        if ret in kernels.keys():
            return ret
        logging.fatal("ERROR: Invalid kernel specified, please type in one"
                      " from the list above.")
    return ret


def ask_for_device(args):
    """
    Prompt for the device vendor, model, and kernel.

    :returns: Tuple consisting of: (device, device_exists, kernel)
        * device: "<vendor>-<codename>" string for device
        * device_exists: bool indicating if device port exists in repo
        * kernel: type of kernel (downstream, etc)
    """
    vendors = sorted(pmb.helpers.devices.list_vendors(args))
    logging.info("Choose your target device vendor (either an "
                 "existing one, or a new one for porting).")
    logging.info(f"Available vendors ({len(vendors)}): {', '.join(vendors)}")

    current_vendor = None
    current_codename = None
    if args.device:
        current_vendor = args.device.split("-", 1)[0]
        current_codename = args.device.split("-", 1)[1]

    while True:
        vendor = pmb.helpers.cli.ask("Vendor", None, current_vendor,
                                     False, r"[a-z0-9]+", vendors)

        new_vendor = vendor not in vendors
        codenames = []
        if new_vendor:
            logging.info("The specified vendor ({}) could not be found in"
                         " existing ports, do you want to start a new"
                         " port?".format(vendor))
            if not pmb.helpers.cli.confirm(args, default=True):
                continue
        else:
            # Unmaintained devices can be selected, but are not displayed
            devices = sorted(pmb.helpers.devices.list_codenames(
                args, vendor, unmaintained=False))
            # Remove "vendor-" prefixes from device list
            codenames = [x.split('-', 1)[1] for x in devices]
            logging.info(f"Available codenames ({len(codenames)}): " +
                         ", ".join(codenames))

        if current_vendor != vendor:
            current_codename = ''
        codename = pmb.helpers.cli.ask("Device codename", None,
                                       current_codename, False, r"[a-z0-9]+",
                                       codenames)

        device = f"{vendor}-{codename}"
        device_path = pmb.helpers.devices.find_path(args, device, 'deviceinfo')
        device_exists = device_path is not None
        if not device_exists:
            if device == args.device:
                raise RuntimeError(
                    "This device does not exist anymore, check"
                    " <https://postmarketos.org/renamed>"
                    " to see if it was renamed")
            logging.info("You are about to do"
                         f" a new device port for '{device}'.")
            if not pmb.helpers.cli.confirm(args, default=True):
                current_vendor = vendor
                continue

            # New port creation confirmed
            logging.info("Generating new aports for: {}...".format(device))
            pmb.aportgen.generate(args, f"device-{device}")
            pmb.aportgen.generate(args, f"linux-{device}")
        elif "/unmaintained/" in device_path:
            apkbuild = f"{device_path[:-len('deviceinfo')]}APKBUILD"
            unmaintained = pmb.parse._apkbuild.unmaintained(apkbuild)
            logging.info(f"WARNING: {device} is unmaintained: {unmaintained}")
            if not pmb.helpers.cli.confirm(args):
                continue
        break

    kernel = ask_for_device_kernel(args, device)
    return (device, device_exists, kernel)


def ask_for_additional_options(args, cfg):
    # Allow to skip additional options
    logging.info("Additional options:"
                 f" extra free space: {args.extra_space} MB,"
                 f" boot partition size: {args.boot_size} MB,"
                 f" parallel jobs: {args.jobs},"
                 f" ccache per arch: {args.ccache_size},"
                 f" sudo timer: {args.sudo_timer},"
                 f" mirror: {','.join(args.mirrors_postmarketos)}")

    if not pmb.helpers.cli.confirm(args, "Change them?",
                                   default=False):
        return

    # Extra space
    logging.info("Set extra free space to 0, unless you ran into a 'No space"
                 " left on device' error. In that case, the size of the"
                 " rootfs could not be calculated properly on your machine,"
                 " and we need to add extra free space to make the image big"
                 " enough to fit the rootfs (pmbootstrap#1904)."
                 " How much extra free space do you want to add to the image"
                 " (in MB)?")
    answer = pmb.helpers.cli.ask("Extra space size", None,
                                 args.extra_space, validation_regex="^[0-9]+$")
    cfg["pmbootstrap"]["extra_space"] = answer

    # Boot size
    logging.info("What should be the boot partition size (in MB)?")
    answer = pmb.helpers.cli.ask("Boot size", None, args.boot_size,
                                 validation_regex="^[1-9][0-9]*$")
    cfg["pmbootstrap"]["boot_size"] = answer

    # Parallel job count
    logging.info("How many jobs should run parallel on this machine, when"
                 " compiling?")
    answer = pmb.helpers.cli.ask("Jobs", None, args.jobs,
                                 validation_regex="^[1-9][0-9]*$")
    cfg["pmbootstrap"]["jobs"] = answer

    # Ccache size
    logging.info("We use ccache to speed up building the same code multiple"
                 " times. How much space should the ccache folder take up per"
                 " architecture? After init is through, you can check the"
                 " current usage with 'pmbootstrap stats'. Answer with 0 for"
                 " infinite.")
    regex = "0|[0-9]+(k|M|G|T|Ki|Mi|Gi|Ti)"
    answer = pmb.helpers.cli.ask("Ccache size", None, args.ccache_size,
                                 lowercase_answer=False,
                                 validation_regex=regex)
    cfg["pmbootstrap"]["ccache_size"] = answer

    # Sudo timer
    logging.info("pmbootstrap does everything in Alpine Linux chroots, so"
                 " your host system does not get modified. In order to"
                 " work with these chroots, pmbootstrap calls 'sudo'"
                 " internally. For long running operations, it is possible"
                 " that you'll have to authorize sudo more than once.")
    answer = pmb.helpers.cli.confirm(args, "Enable background timer to prevent"
                                     " repeated sudo authorization?",
                                     default=args.sudo_timer)
    cfg["pmbootstrap"]["sudo_timer"] = str(answer)

    # Mirrors
    # prompt for mirror change
    logging.info("Selected mirror:"
                 f" {','.join(args.mirrors_postmarketos)}")
    if pmb.helpers.cli.confirm(args, "Change mirror?", default=False):
        mirrors = ask_for_mirror(args)
        cfg["pmbootstrap"]["mirrors_postmarketos"] = ",".join(mirrors)


def ask_for_mirror(args):
    regex = "^[1-9][0-9]*$"  # single non-zero number only

    json_path = pmb.helpers.http.download(
        args, "https://postmarketos.org/mirrors.json", "pmos_mirrors",
        cache=False)
    with open(json_path, "rt") as handle:
        s = handle.read()

    logging.info("List of available mirrors:")
    mirrors = json.loads(s)
    keys = mirrors.keys()
    i = 1
    for key in keys:
        logging.info(f"[{i}]\t{key} ({mirrors[key]['location']})")
        i += 1

    urls = []
    for key in keys:
        # accept only http:// or https:// urls
        http_count = 0  # remember if we saw any http:// only URLs
        link_list = []
        for k in mirrors[key]["urls"]:
            if k.startswith("http"):
                link_list.append(k)
            if k.startswith("http://"):
                http_count += 1
        # remove all https urls if there is more that one URL and one of
        #     them was http://
        if http_count > 0 and len(link_list) > 1:
            link_list = [k for k in link_list if not k.startswith("https")]
        if len(link_list) > 0:
            urls.append(link_list[0])

    mirror_indexes = []
    for mirror in args.mirrors_postmarketos:
        for i in range(len(urls)):
            if urls[i] == mirror:
                mirror_indexes.append(str(i + 1))
                break

    mirrors_list = []
    # require one valid mirror index selected by user
    while len(mirrors_list) != 1:
        answer = pmb.helpers.cli.ask("Select a mirror", None,
                                     ",".join(mirror_indexes),
                                     validation_regex=regex)
        mirrors_list = []
        for i in answer.split(","):
            idx = int(i) - 1
            if 0 <= idx < len(urls):
                mirrors_list.append(urls[idx])
        if len(mirrors_list) != 1:
            logging.info("You must select one valid mirror!")

    return mirrors_list


def ask_for_hostname(args, device):
    while True:
        ret = pmb.helpers.cli.ask("Device hostname (short form, e.g. 'foo')",
                                  None, (args.hostname or device), True)
        if not pmb.helpers.other.validate_hostname(ret):
            continue
        # Don't store device name in user's config (gets replaced in install)
        if ret == device:
            return ""
        return ret


def ask_for_ssh_keys(args):
    if not len(glob.glob(os.path.expanduser("~/.ssh/id_*.pub"))):
        return False
    return pmb.helpers.cli.confirm(args,
                                   "Would you like to copy your SSH public"
                                   " keys to the device?",
                                   default=args.ssh_keys)


def ask_build_pkgs_on_install(args):
    logging.info("After pmaports are changed, the binary packages may be"
                 " outdated. If you want to install postmarketOS without"
                 " changes, reply 'n' for a faster installation.")
    return pmb.helpers.cli.confirm(args, "Build outdated packages during"
                                   " 'pmbootstrap install'?",
                                   default=args.build_pkgs_on_install)


def get_locales():
    ret = []
    list_path = f"{pmb.config.pmb_src}/pmb/data/locales"
    with open(list_path, "r") as handle:
        for line in handle:
            ret += [line.rstrip()]
    return ret


def ask_for_locale(args):
    locales = get_locales()
    logging.info("Choose your preferred locale, like e.g. en_US. Only UTF-8"
                 " is supported, it gets appended automatically. Use"
                 " tab-completion if needed.")

    while True:
        ret = pmb.helpers.cli.ask("Locale",
                                  choices=None,
                                  default=args.locale.replace(".UTF-8", ""),
                                  lowercase_answer=False,
                                  complete=locales)
        ret = ret.replace(".UTF-8", "")
        if ret not in locales:
            logging.info("WARNING: this locale is not in the list of known"
                         " valid locales.")
            if pmb.helpers.cli.ask() != "y":
                # Ask again
                continue

        return f"{ret}.UTF-8"


def frontend(args):
    require_programs()

    # Work folder (needs to be first, so we can create chroots early)
    cfg = pmb.config.load(args)
    work, work_exists = ask_for_work_path(args)
    cfg["pmbootstrap"]["work"] = work

    # Update args and save config (so chroots and 'pmbootstrap log' work)
    pmb.helpers.args.update_work(args, work)
    pmb.config.save(args, cfg)

    # Migrate work dir if necessary
    pmb.helpers.other.migrate_work_folder(args)

    # Clone pmaports
    pmb.config.pmaports.init(args)

    # Choose release channel, possibly switch pmaports branch
    channel = ask_for_channel(args)
    pmb.config.pmaports.switch_to_channel_branch(args, channel)
    cfg["pmbootstrap"]["is_default_channel"] = "False"

    # Copy the git hooks if master was checked out. (Don't symlink them and
    # only do it on master, so the git hooks don't change unexpectedly when
    # having a random branch checked out.)
    branch_current = pmb.helpers.git.rev_parse(args, args.aports,
                                               extra_args=["--abbrev-ref"])
    if branch_current == "master":
        logging.info("NOTE: pmaports is on master branch, copying git hooks.")
        pmb.config.pmaports.install_githooks(args)

    # Device
    device, device_exists, kernel = ask_for_device(args)
    cfg["pmbootstrap"]["device"] = device
    cfg["pmbootstrap"]["kernel"] = kernel

    info = pmb.parse.deviceinfo(args, device)
    apkbuild_path = pmb.helpers.devices.find_path(args, device, 'APKBUILD')
    if apkbuild_path:
        apkbuild = pmb.parse.apkbuild(apkbuild_path)
        ask_for_provider_select(args, apkbuild, cfg["providers"])

    # Device keymap
    if device_exists:
        cfg["pmbootstrap"]["keymap"] = ask_for_keymaps(args, info)

    cfg["pmbootstrap"]["user"] = ask_for_username(args)
    ask_for_provider_select_pkg(args, "postmarketos-base", cfg["providers"])
    ask_for_provider_select_pkg(args, "postmarketos-base-ui", cfg["providers"])

    # UI and various build options
    ui = ask_for_ui(args, info)
    cfg["pmbootstrap"]["ui"] = ui
    cfg["pmbootstrap"]["ui_extras"] = str(ask_for_ui_extras(args, ui))
    ask_for_provider_select_pkg(args, f"postmarketos-ui-{ui}",
                                cfg["providers"])
    ask_for_additional_options(args, cfg)

    # Extra packages to be installed to rootfs
    logging.info("Additional packages that will be installed to rootfs."
                 " Specify them in a comma separated list (e.g.: vim,file)"
                 " or \"none\"")
    extra = pmb.helpers.cli.ask("Extra packages", None,
                                args.extra_packages,
                                validation_regex=r"^([-.+\w]+)(,[-.+\w]+)*$")
    cfg["pmbootstrap"]["extra_packages"] = extra

    # Configure timezone info
    cfg["pmbootstrap"]["timezone"] = ask_for_timezone(args)

    # Locale
    cfg["pmbootstrap"]["locale"] = ask_for_locale(args)

    # Hostname
    cfg["pmbootstrap"]["hostname"] = ask_for_hostname(args, device)

    # SSH keys
    cfg["pmbootstrap"]["ssh_keys"] = str(ask_for_ssh_keys(args))

    # pmaports path (if users change it with: 'pmbootstrap --aports=... init')
    cfg["pmbootstrap"]["aports"] = args.aports

    # Build outdated packages in pmbootstrap install
    cfg["pmbootstrap"]["build_pkgs_on_install"] = str(
        ask_build_pkgs_on_install(args))

    # Save config
    pmb.config.save(args, cfg)

    # Zap existing chroots
    if (work_exists and device_exists and
            len(glob.glob(args.work + "/chroot_*")) and
            pmb.helpers.cli.confirm(
                args, "Zap existing chroots to apply configuration?",
                default=True)):
        setattr(args, "deviceinfo", info)

        # Do not zap any existing packages or cache_http directories
        pmb.chroot.zap(args, confirm=False)

    logging.info("WARNING: The chroots and git repositories in the work dir do"
                 " not get updated automatically.")
    logging.info("Run 'pmbootstrap status' once a day before working with"
                 " pmbootstrap to make sure that everything is up-to-date.")
    logging.info("DONE!")
