#!/bin/sh -e
# Description: lint all python scripts
# https://postmarketos.org/pmb-ci

if [ "$(id -u)" = 0 ]; then
	set -x
	apk -q add ruff
	exec su "${TESTUSER:-build}" -c "sh -e $0"
fi

set -x

# __init__.py with additional ignore:
# F401: imported, but not used
# shellcheck disable=SC2046
ruff --ignore "F401" $(find . -not -path '*/venv/*' -name '__init__.py')

# Check all other files
ruff  --exclude=__init__.py .
