# Copyright 2023 Oliver Smith
# SPDX-License-Identifier: GPL-3.0-or-later
import pmb_test  # noqa
import pmb.helpers.mount


def test_umount_all_list(tmpdir):
    # Write fake mounts file
    fake_mounts = str(tmpdir + "/mounts")
    with open(fake_mounts, "w") as handle:
        handle.write("source /test/var/cache\n")
        handle.write("source /test/home/pmos/packages\n")
        handle.write("source /test\n")
        handle.write("source /test/proc\n")
        handle.write("source /test/dev/loop0p2\\040(deleted)\n")

    ret = pmb.helpers.mount.umount_all_list("/no/match", fake_mounts)
    assert ret == []

    ret = pmb.helpers.mount.umount_all_list("/test/var/cache", fake_mounts)
    assert ret == ["/test/var/cache"]

    ret = pmb.helpers.mount.umount_all_list("/test", fake_mounts)
    assert ret == ["/test/var/cache", "/test/proc", "/test/home/pmos/packages",
                   "/test/dev/loop0p2", "/test"]
