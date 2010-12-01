# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os

from autotest_lib.client.bin import boottool, site_logging, utils
from autotest_lib.client.bin.job import base_client_job
from autotest_lib.client.common_lib import error
from datetime import datetime

LAST_BOOT_TAG = object()

class site_job(base_client_job):
    def __init__(self, *args, **kwargs):
        base_client_job.__init__(self, *args, **kwargs)


    def run_test(self, url, *args, **dargs):
        log_pauser = site_logging.LogRotationPauser()
        try:
            log_pauser.begin()
            passed = base_client_job.run_test(self, url, *args, **dargs)
            if not passed:
                # Save the VM state immediately after the test failure.
                # This is a NOOP if the the test isn't running in a VM or
                # if the VM is not properly configured to save state.
                group, testname = self.pkgmgr.get_package_name(url, 'test')
                now = datetime.now().strftime('%I:%M:%S.%f')
                checkpoint_name = '%s-%s' % (testname, now)
                utils.save_vm_state(checkpoint_name)
        finally:
            log_pauser.end()


    def reboot(self, tag=LAST_BOOT_TAG):
        if tag == LAST_BOOT_TAG:
            tag = self.last_boot_tag
        else:
            self.last_boot_tag = tag

        self.reboot_setup()
        self.harness.run_reboot()

        # sync first, so that a sync during shutdown doesn't time out
        utils.system("sync; sync", ignore_status=True)

        utils.system("(sleep 5; reboot) </dev/null >/dev/null 2>&1 &")
        self.quit()


    def require_gcc(self):
        return False
