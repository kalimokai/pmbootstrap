# Copyright 2023 Lary Gibaud
# SPDX-License-Identifier: GPL-3.0-or-later
import re


def arm_big_little_first_group_ncpus():
    """
    Infer from /proc/cpuinfo on aarch64 if this is a big/little architecture
    (if there is different processor models) and the number of cores in the
    first model group.
    https://en.wikipedia.org/wiki/ARM_big.LITTLE

    :returns: the number of cores of the first model in the order given by
              linux or None if not big/little architecture
    """
    pattern = re.compile(r"^CPU part\s*: (\w+)$")
    counter = 0
    part = None

    with open('/proc/cpuinfo', 'r') as cpuinfo:
        for line in cpuinfo:
            match = pattern.match(line)
            if match:
                grp = match.group(1)
                if not part:
                    part = grp
                    counter += 1
                elif part == grp:
                    counter += 1
                else:
                    return counter
        return None
