#!/bin/sh -e
# Description: verify that we don't use too new python features
# https://postmarketos.org/pmb-ci

if [ "$(id -u)" = 0 ]; then
	set -x
	apk -q add vermin
	exec su "${TESTUSER:-build}" -c "sh -e $0"
fi

# shellcheck disable=SC2046
vermin \
	-t=3.7- \
	--backport argparse \
	--backport configparser \
	--backport enum \
	--backport typing \
	--lint \
	--no-parse-comments \
	--eval-annotations \
	$(find . -name '*.py' \
		-a -not -path "./.venv/*" \
		-a -not -path "./venv/*")

echo "vermin check passed"
