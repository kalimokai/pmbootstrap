#!/bin/sh -e
# Description: run pmbootstrap python testsuite
# Options: native slow
# https://postmarketos.org/pmb-ci

if [ "$(id -u)" = 0 ]; then
	set -x
	apk -q add \
		git \
		openssl \
		py3-pytest \
		py3-pytest-cov \
		sudo
	exec su "${TESTUSER:-build}" -c "sh -e $0"
fi

# Require pytest to be installed on the host system
if [ -z "$(command -v pytest)" ]; then
	echo "ERROR: pytest command not found, make sure it is in your PATH."
	exit 1
fi

# Use pytest-cov if it is installed to display code coverage
cov_arg=""
if python -c "import pytest_cov" >/dev/null 2>&1; then
	cov_arg="--cov=pmb"
fi

echo "Initializing pmbootstrap..."
if ! yes '' | ./pmbootstrap.py \
		--details-to-stdout \
		init \
		>/tmp/pmb_init 2>&1; then
	cat /tmp/pmb_init
	exit 1
fi

# Make sure that the work folder format is up to date, and that there are no
# mounts from aborted test cases (#1595)
./pmbootstrap.py work_migrate
./pmbootstrap.py -q shutdown

# Make sure we have a valid device (#1128)
device="$(./pmbootstrap.py config device)"
pmaports="$(./pmbootstrap.py config aports)"
deviceinfo="$(ls -1 "$pmaports"/device/*/device-"$device"/deviceinfo)"
if ! [ -e "$deviceinfo" ]; then
	echo "ERROR: Could not find deviceinfo file for selected device:" \
		"$device"
	echo "Expected path: $deviceinfo"
	echo "Maybe you have switched to a branch where your device does not"
	echo "exist? Use 'pmbootstrap config device qemu-amd64' to switch to"
	echo "a valid device."
	exit 1
fi

# Make sure pmaports is clean, some of the tests will fail otherwise
if [ -n "$(git -C "$pmaports" status --porcelain)" ]; then
	echo "ERROR: pmaports dir is not clean"
	exit 1
fi

echo "Running pytest..."
echo "NOTE: use 'pmbootstrap log' to see the detailed log if running locally."
pytest \
	--color=yes \
	-vv \
	-x \
	$cov_arg \
	test \
		-m "not skip_ci" \
		"$@"
