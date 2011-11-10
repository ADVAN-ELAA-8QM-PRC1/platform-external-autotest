# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import time

from autotest_lib.client.common_lib import error
from autotest_lib.server.cros.faftsequence import FAFTSequence


class firmware_CorruptKernelB(FAFTSequence):
    """
    Servo based kernel B corruption test.

    This test sets kernel B boot and then corrupts kernel B. The firmware
    verifies kernel B failed so falls back to kernel A boot. This test will
    fail if kernel verification mis-behaved.
    """
    version = 1


    def setup(self):
        super(firmware_CorruptKernelB, self).setup()
        self.setup_dev_mode(dev_mode=False)
        self.setup_kernel('a')


    def cleanup(self):
        self.ensure_kernel_boot('a')
        super(firmware_CorruptKernelB, self).cleanup()


    def run_once(self, host=None):
        self.register_faft_sequence((
            {   # Step 1, prioritize kernel B
                'state_checker': (self.root_part_checker, 'a'),
                'userspace_action': (self.reset_and_prioritize_kernel, 'b'),
            },
            {   # Step 2, expected kernel B boot and corrupt kernel B
                'state_checker': (self.root_part_checker, 'b'),
                'userspace_action': (self.faft_client.corrupt_kernel, 'b'),
            },
            {   # Step 3, expected kernel A boot and restore kernel B
                'state_checker': (self.root_part_checker, 'a'),
                'userspace_action': (self.faft_client.restore_kernel, 'b'),
            },
            {   # Step 4, expected kernel B boot and prioritize kerenl A
                'state_checker': (self.root_part_checker, 'b'),
                'userspace_action': (self.reset_and_prioritize_kernel, 'a'),
            },
            {   # Step 5, expected kernel A boot
                'state_checker': (self.root_part_checker, 'a'),
            },
        ))
        self.run_faft_sequence()
