#!/bin/sh
# Copyright 2019 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
#
# usage example:
# $ cd ~/code/linux
# $ source ~/code/pmbootstrap/helpers/envkernel.sh

check_kernel_folder() {
	[ -e "Kbuild" ] && return
	echo "ERROR: This folder is not a linux source tree: $PWD"
	return 1
}


clean_kernel_src_dir() {
	# Prevent Linux from appending Git version information to kernel version
	# This will cause kernels to be packaged incorrectly.
	touch .scmversion

	if [ -f ".config" ] || [ -d "include/config" ]; then
		echo "Source directory is not clean, running 'make mrproper'."

		tmp_dir=""
		if [ -d ".output" ]; then
			echo " * Preserving existing build output."
			tmp_dir=$(mktemp -d)
			sudo mv ".output" "$tmp_dir"
		fi;

		# backslash is prefixed to disable the alias
		# shellcheck disable=SC1001
		\make mrproper

		if [ -n "$tmp_dir" ]; then
			sudo mv "$tmp_dir/.output" ".output"
			sudo rmdir "$tmp_dir"
		fi;
	fi;
}


export_envkernel_sh() {
	# Get script location
	# See also: <https://stackoverflow.com/a/29835459>
	# shellcheck disable=SC3054
	if [ -n "${BASH_SOURCE[0]}" ]; then
		envkernel_sh="$(realpath "$BASH_SOURCE")"
	else
		envkernel_sh="$1"
	fi
	export envkernel_sh
}


export_pmbootstrap_dir() {
	if [ -n "$pmbootstrap_dir" ]; then
		return 0;
	fi

	# Get pmbootstrap dir based on this script's location, if it's
	# in a pmbootstrap source tree
	pmbootstrap_dir="$(realpath "$(dirname "${envkernel_sh}")/..")"
	if [ -e "$pmbootstrap_dir/pmbootstrap.py" ]; then
		export pmbootstrap_dir
	else
		unset pmbootstrap_dir
	fi
}


set_alias_pmbootstrap() {
	if [ -n "$pmbootstrap_dir" ] \
			&& [ -e "$pmbootstrap_dir/pmbootstrap.py" ]; then
		pmbootstrap="$pmbootstrap_dir"/pmbootstrap.py
		# shellcheck disable=SC2139
		alias pmbootstrap="\"$pmbootstrap\""
	elif [ -n "$(command -v pmbootstrap)" ]; then
		pmbootstrap="$(command -v pmbootstrap)"
	else
		echo "ERROR: pmbootstrap not found!"
		echo "If you're loading envkernel.sh from a pmbootstrap source tree,"
		echo "please check export_pmbootstrap_dir in envkernel.sh. Otherwise "
		echo "please make sure 'pmbootstrap' is on your PATH."
		return 1
	fi

	if [ -e "${XDG_CONFIG_HOME:-$HOME/.config}"/pmbootstrap.cfg ]; then
		"$pmbootstrap" work_migrate
	else
		echo "NOTE: First run of pmbootstrap, running 'pmbootstrap init'"
		"$pmbootstrap" init
	fi
}


export_chroot_device_deviceinfo() {
	chroot="$("$pmbootstrap" config work)/chroot_native"
	device="$("$pmbootstrap" config device)"
	deviceinfo="$(echo "$("$pmbootstrap" config aports)"/device/*/device-"$device"/deviceinfo)"
	export chroot device deviceinfo
}


check_device() {
	[ -e "$deviceinfo" ] && return
	echo "ERROR: Please select a valid device in 'pmbootstrap init'"
	return 1
}


initialize_chroot() {
	gcc_pkgname="gcc"
	if [ "$gcc6_arg" = "1" ]; then
		gcc_pkgname="gcc6"
	fi
	if [ "$gcc4_arg" = "1" ]; then
		gcc_pkgname="gcc4"
	fi

	# Kernel architecture
	# shellcheck disable=SC2154
	case "$deviceinfo_arch" in
		aarch64*) arch="arm64" ;;
		arm*) arch="arm" ;;
		x86_64) arch="x86_64" ;;
		x86) arch="x86" ;;
	esac

	# Check if it's a cross compile
	host_arch="$(uname -m)"
	need_cross_compiler=1
	# Match arm* architectures
	# shellcheck disable=SC3057
	arch_substr="${host_arch:0:3}"
	if [ "$arch" = "$host_arch" ] || \
		{ [ "$arch_substr" = "arm" ] && [ "$arch_substr" = "$arch" ]; } || \
		{ [ "$arch" = "arm64" ] && [ "$host_arch" = "aarch64" ]; } || \
		{ [ "$arch" = "x86" ] && [ "$host_arch" = "x86_64" ]; }; then
		need_cross_compiler=0
	fi

	# Don't initialize twice
	flag="$chroot/tmp/envkernel/${gcc_pkgname}_setup_done"
	[ -e "$flag" ] && return

	# Install needed packages
	echo "Initializing Alpine chroot (details: 'pmbootstrap log')"

	cross_binutils=""
	cross_gcc=""
	if [ "$need_cross_compiler" = 1 ]; then
		cross_binutils="binutils-$deviceinfo_arch"
		cross_gcc="$gcc_pkgname-$deviceinfo_arch"
	fi

	# FIXME: Ideally we would not "guess" the dependencies here.
	# It might be better to take a kernel package name as parameter
	#   (e.g. . envkernel.sh linux-postmarketos-mainline)
	# and install its build dependencies.

	# shellcheck disable=SC2086,SC2154
	"$pmbootstrap" -q chroot -- apk -q add \
		abuild \
		bash \
		bc \
		binutils \
		bison \
		$cross_binutils \
		$cross_gcc \
		diffutils \
		elfutils-dev \
		findutils \
		flex \
		g++ \
		"$gcc_pkgname" \
		gmp-dev \
		linux-headers \
		openssl-dev \
		make \
		mpc1-dev \
		mpfr-dev \
		musl-dev \
		ncurses-dev \
		perl \
		py3-dt-schema \
		sed \
		yamllint \
		yaml-dev \
		xz || return 1

	# Create /mnt/linux
	sudo mkdir -p "$chroot/mnt/linux"

	# Mark as initialized
	"$pmbootstrap" -q chroot -- su pmos -c \
		"mkdir /tmp/envkernel; touch /tmp/envkernel/$(basename "$flag")"
}


mount_kernel_source() {
	if [ -e "$chroot/mnt/linux/Kbuild" ]; then
		sudo umount "$chroot/mnt/linux"
	fi
	sudo mount --bind "$PWD" "$chroot/mnt/linux"
}


create_output_folder() {
	[ -d "$chroot/mnt/linux/.output" ] && return
	mkdir -p ".output"
	"$pmbootstrap" -q chroot -- chown -R pmos:pmos "/mnt/linux/.output"
}


set_alias_make() {
	# Cross compiler prefix
	# shellcheck disable=SC1091
	prefix="$(CBUILD="$deviceinfo_arch" . "$chroot/usr/share/abuild/functions.sh";
		arch_to_hostspec "$deviceinfo_arch")"

	if [ "$gcc6_arg" = "1" ]; then
		cc="gcc6-${prefix}-gcc"
		hostcc="gcc6-gcc"
		cross_compiler="/usr/bin/gcc6-$prefix-"
	elif [ "$gcc4_arg" = "1" ]; then
		cc="gcc4-${prefix}-gcc"
		hostcc="gcc4-gcc"
		cross_compiler="/usr/bin/gcc4-$prefix-"
	else
		cc="${prefix}-gcc"
		hostcc="gcc"
		cross_compiler="/usr/bin/$prefix-"
	fi

	if [ "$arch" = "x86" ] && [ "$host_arch" = "x86_64" ]; then
		cc=$hostcc
	fi

	# Build make command
	cmd="echo '*** pmbootstrap envkernel.sh active for $PWD! ***';"
	cmd="$cmd pmbootstrap -q chroot --user --"
	cmd="$cmd CCACHE_DISABLE=1"
	cmd="$cmd ARCH=$arch"
	if [ "$need_cross_compiler" = 1 ]; then
		cmd="$cmd CROSS_COMPILE=$cross_compiler"
	fi
	cmd="$cmd make -C /mnt/linux O=/mnt/linux/.output"
	cmd="$cmd CC=$cc HOSTCC=$hostcc"

	# shellcheck disable=SC2139
	alias make="$cmd"
	unset cmd

	# Build run-script command
	cmd="_run_script() {"
	cmd="$cmd echo '*** pmbootstrap envkernel.sh active for $PWD! ***';"
	cmd="$cmd _script=\"\$1\";"
	cmd="$cmd shift;"
	cmd="$cmd if [ -e \"\$_script\" ]; then"
	cmd="$cmd 	echo \"Running \$_script in the chroot native /mnt/linux/\";"
	cmd="$cmd 	pmbootstrap -q chroot --user -- sh -c \"cd /mnt/linux;"
	cmd="$cmd 	srcdir=/mnt/linux builddir=/mnt/linux/.output tmpdir=/tmp/envkernel"
	cmd="$cmd 	./\"\$_script\" \\\"\\\$@\\\"\" \"sh\" \"\$@\";"
	cmd="$cmd else"
	cmd="$cmd 	echo \"ERROR: \$_script not found.\";"
	cmd="$cmd fi;"
	cmd="$cmd };"
	cmd="$cmd _run_script \"\$@\""
	# shellcheck disable=SC2139
	alias run-script="$cmd"
	unset cmd
}


set_alias_pmbroot_kernelroot() {
	if [ -n "$pmbootstrap_dir" ]; then
		# shellcheck disable=SC2139
		alias pmbroot="cd '$pmbootstrap_dir'"
	fi
	# shellcheck disable=SC2139
	alias kernelroot="cd '$PWD'"
}


cross_compiler_version() {
	if [ "$need_cross_compiler" = 1 ]; then
		"$pmbootstrap" chroot --user -- "${cross_compiler}gcc"  --version \
			2> /dev/null | grep "^.*gcc " | \
			awk -F'[()]' '{ print $1 "("$2")" }'
	else
		echo "none"
	fi
}


update_prompt() {
	if [ -n "$ZSH_VERSION" ]; then
		# assume Zsh
		export _OLD_PROMPT="$PROMPT"
		export PROMPT="[envkernel] $PROMPT"
	elif [ -n "$BASH_VERSION" ]; then
		export _OLD_PS1="$PS1"
		export PS1="[envkernel] $PS1"
	fi
}


set_deactivate() {
	cmd="_deactivate() {"
	cmd="$cmd unset POSTMARKETOS_ENVKERNEL_ENABLED;"
	if [ -n "$pmbootstrap_dir" ]; then
		cmd="$cmd unalias pmbootstrap pmbroot;"
	fi
	cmd="$cmd unalias make kernelroot run-script;"
	cmd="$cmd unalias deactivate reactivate;"
	cmd="$cmd unset pmbootstrap pmbootstrap_dir;"
	cmd="$cmd if [ -n \"\$_OLD_PS1\" ]; then"
	cmd="$cmd   export PS1=\"\$_OLD_PS1\";"
	cmd="$cmd   unset _OLD_PS1;"
	cmd="$cmd elif [ -n \"\$_OLD_PROMPT\" ]; then"
	cmd="$cmd   export PROMPT=\"\$_OLD_PROMPT\";"
	cmd="$cmd   unset _OLD_PROMPT;"
	cmd="$cmd fi"
	cmd="$cmd };"
	cmd="$cmd _deactivate \"\$@\""
	# shellcheck disable=SC2139
	alias deactivate="$cmd"
	unset cmd
}

set_reactivate() {
	# shellcheck disable=SC2139
	alias reactivate="deactivate; pushd '$PWD'; . '$envkernel_sh'; popd"
}

check_and_deactivate() {
	if [ "$POSTMARKETOS_ENVKERNEL_ENABLED" = 1 ]; then
		# we already are running in envkernel
		deactivate
	fi
}


print_usage() {
	# shellcheck disable=SC3054
	if [ -n "${BASH_SOURCE[0]}" ]; then
		echo "usage: source $(basename "$(realpath "$BASH_SOURCE")")"
	fi
	echo "optional arguments:"
	echo "    --fish        Print fish alias syntax (internally used)"
	echo "    --gcc6        Use GCC6 cross compiler"
	echo "    --gcc4        Use GCC4 cross compiler"
	echo "    --help        Show this help message"
}


parse_args() {
	unset fish_arg
	unset gcc6_arg
	unset gcc4_arg

	while [ "${1:-}" != "" ]; do
		case $1 in
		--fish)
			fish_arg="$1"
			shift
			;;
		--gcc6)
			gcc6_arg=1
			shift
			;;
		--gcc4)
			gcc4_arg=1
			shift
			;;
		--help)
			shift
			return 0
			;;
		*)
			echo "Invalid argument: $1"
			shift
			return 0
			;;
		esac
	done

	return 1
}


main() {
	# Stop executing once a function fails
	# shellcheck disable=SC1090
	if check_and_deactivate \
		&& check_kernel_folder \
		&& clean_kernel_src_dir \
		&& export_envkernel_sh "$1" \
		&& export_pmbootstrap_dir \
		&& set_alias_pmbootstrap \
		&& export_chroot_device_deviceinfo \
		&& check_device \
		&& . "$deviceinfo" \
		&& initialize_chroot \
		&& mount_kernel_source \
		&& create_output_folder \
		&& set_alias_make \
		&& set_alias_pmbroot_kernelroot \
		&& update_prompt \
		&& set_deactivate \
		&& set_reactivate; then

		POSTMARKETOS_ENVKERNEL_ENABLED=1

		# Success
		echo "pmbootstrap envkernel.sh activated successfully."
		echo " * kernel source:  $PWD"
		echo " * output folder:  $PWD/.output"
		echo " * architecture:   $arch ($device is $deviceinfo_arch)"
		echo " * cross compile:  $(cross_compiler_version)"
		if [ -n "$pmbootstrap_dir" ]; then
			echo " * aliases: make, kernelroot, pmbootstrap, pmbroot," \
				"run-script (see 'type make' etc.)"
		else
			echo " * aliases: make, kernelroot, run-script"\
				"(see 'type make' etc.)"
		fi
		echo " * run 'deactivate' to revert all env changes"
	else
		# Failure
		echo "See also: <https://postmarketos.org/troubleshooting>"
		return 1
	fi
}


# Print fish alias syntax (when called from envkernel.fish)
fish_compat() {
	[ "$1" = "--fish" ] || return 0
	for name in make kernelroot pmbootstrap pmbroot; do
		alias "$name" >/dev/null 2>&1 && echo "alias $(alias "$name" | sed 's/=/ /')"
	done
}

if parse_args "$@"; then
	print_usage "$0"
	return 1
fi

# Run main() with all output redirected to stderr
# Afterwards print fish compatible syntax to stdout
main "$0" >&2 && fish_compat "$fish_arg"
