#! /bin/sh -e
if [ -e "pmbootstrap.py" ]; then
	PMB_PATH=$(pwd)
	# shellcheck disable=SC2139
	alias pmbroot="cd \"$PMB_PATH\""
	# shellcheck disable=SC2139
	alias pmbootstrap="$PMB_PATH/pmbootstrap.py"
else
	echo "ERROR: Please source this from the pmbootstrap folder."
	return 1
fi
