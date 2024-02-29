#!/usr/bin/env fish
# Copyright 2019 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later

for arg in $argv
	if not string match -q -- "--gcc6" $arg;
		and not string match -q -- "--gcc4" $arg
		echo "usage: source envkernel.fish"
		echo "optional arguments:"
		echo "    --gcc4        Use GCC4 cross compiler"
		echo "    --gcc6        Use GCC6 cross compiler"
		echo "    --help        Show this help message"
		exit 1
	end
end

# Fish compatibility code from envkernel.sh
set envkernel_fish (status filename)
set script_dir (dirname "$envkernel_fish")
sh "$script_dir/envkernel.sh" $argv --fish 1>| read -z fishcode
set pmbootstrap_dir (realpath "$script_dir/..")
if not test -e "$pmbootstrap_dir/pmbootstrap.py"
	set -e pmbootstrap_dir
end

# Verbose output (enable with: 'set ENVKERNEL_FISH_VERBOSE 1')
if [ "$ENVKERNEL_FISH_VERBOSE" = "1" ]
	echo "(eval code start)"
	printf "$fishcode"
	echo "(eval code end)"
end

# Execute generated code
echo -e "$fishcode" | source -

# Set prompt
if test -z "$ENVKERNEL_DISABLE_PROMPT"
    functions -c fish_prompt _old_fish_prompt

    function fish_prompt
        set -l old_status $status
        printf "[envkernel] "
        echo "exit $old_status" | .
        _old_fish_prompt
    end
end

# Deactivate
function deactivate
	if functions -q _old_fish_prompt
		functions -e fish_prompt
		functions -c _old_fish_prompt fish_prompt
		functions -e _old_fish_prompt
	end
	functions -e make kernelroot pmbootstrap pmbroot
	functions -e deactivate reactivate
	set -e envkernel_fish script_dir pmbootstrap_dir
end

# Reactivate
alias reactivate "deactivate; pushd '$PWD'; . '$envkernel_fish'; popd"
