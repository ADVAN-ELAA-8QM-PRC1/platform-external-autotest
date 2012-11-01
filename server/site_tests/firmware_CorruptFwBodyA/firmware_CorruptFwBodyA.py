# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging

from autotest_lib.server.cros import vboot_constants as vboot
from autotest_lib.server.cros.faftsequence import FAFTSequence


class firmware_CorruptFwBodyA(FAFTSequence):
    """
    Servo based firmware body A corruption test.

    The expected behavior is different if the firmware preamble USE_RO_NORMAL
    flag is enabled. In the case USE_RO_NORMAL ON, the firmware corruption
    doesn't hurt the boot results since it boots the RO path directly and does
    not load and verify the RW firmware body. In the case USE_RO_NORMAL OFF,
    the RW firwmare A corruption will result booting the firmware B.
    """
    version = 1


    def setup(self, dev_mode=False):
        super(firmware_CorruptFwBodyA, self).setup()
        self.backup_firmware()
        self.setup_dev_mode(dev_mode)


    def cleanup(self):
        self.restore_firmware()
        super(firmware_CorruptFwBodyA, self).cleanup()


    def run_once(self, host=None):
        if (self.faft_client.get_firmware_flags('a') &
                vboot.PREAMBLE_USE_RO_NORMAL):
            # USE_RO_NORMAL flag is ON. Firmware body corruption doesn't
            # hurt the booting results.
            logging.info('The firmware USE_RO_NORMAL flag is enabled.')
            self.register_faft_sequence((
                {   # Step 1, corrupt firmware body A
                    'state_checker': (self.checkers.crossystem_checker, {
                        'mainfw_act': 'A',
                        'tried_fwb': '0',
                    }),
                    'userspace_action': (self.faft_client.corrupt_firmware_body,
                                         'a'),
                },
                {   # Step 2, still expected firmware A boot and restore
                    'state_checker': (self.checkers.crossystem_checker, {
                        'mainfw_act': 'A',
                        'tried_fwb': '0',
                    }),
                    'userspace_action': (self.faft_client.restore_firmware_body,
                                         'a'),
                },
            ))
        else:
            logging.info('The firmware USE_RO_NORMAL flag is disabled.')
            self.register_faft_sequence((
                {   # Step 1, corrupt firmware body A
                    'state_checker': (self.checkers.crossystem_checker, {
                        'mainfw_act': 'A',
                        'tried_fwb': '0',
                    }),
                    'userspace_action': (self.faft_client.corrupt_firmware_body,
                                         'a'),
                },
                {   # Step 2, expected firmware B boot and restore firmware A
                    'state_checker': (self.checkers.crossystem_checker, {
                        'mainfw_act': 'B',
                        'tried_fwb': '0',
                    }),
                    'userspace_action': (self.faft_client.restore_firmware_body,
                                         'a'),
                },
                {   # Step 3, expected firmware A boot, done
                    'state_checker': (self.checkers.crossystem_checker, {
                        'mainfw_act': 'A',
                        'tried_fwb': '0',
                    }),
                },
            ))
        self.run_faft_sequence()
