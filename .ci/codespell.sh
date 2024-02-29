#!/bin/sh -ex
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright 2023 Oliver Smith
# Description: find typos
# https://postmarketos.org/pmb-ci

if [ "$(id -u)" = 0 ]; then
	set -x
	apk -q add \
		py3-codespell
	exec su "${TESTUSER:-build}" -c "sh -e $0"
fi

set -x

# -L: words to ignore
codespell \
	-L crate \
	-L hda \
	.
