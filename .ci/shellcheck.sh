#!/bin/sh -e
# Description: lint all shell scripts
# https://postmarketos.org/pmb-ci

if [ "$(id -u)" = 0 ]; then
	set -x
	apk -q add shellcheck
	exec su "${TESTUSER:-build}" -c "sh -e $0"
fi

find . -name '*.sh' |
while read -r file; do
	echo "shellcheck: $file"
	shellcheck "$file"
done
