# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re
from threading import Timer

from autotest_lib.client.common_lib import error
from autotest_lib.server.cros.faftsequence import FAFTSequence

class firmware_ECPowerButton(FAFTSequence):
    """
    Servo based EC power button test.
    """
    version = 1


    # Delay between shutdown and wake by power button
    LONG_WAKE_DELAY = 13
    SHORT_WAKE_DELAY = 7

    # Short duration of holding down power button to power on
    POWER_BUTTON_SHORT_POWER_ON_DURATION = 0.05

    # Long duration of holding down power button to power on
    POWER_BUTTON_LONG_POWER_ON_DURATION = 1

    # Duration of holding down power button to shut down with powerd
    POWER_BUTTON_POWERD_DURATION = 6

    # Duration of holding down power button to shut down without powerd
    POWER_BUTTON_NO_POWERD_DURATION = 10


    def setup(self):
        super(firmware_ECPowerButton, self).setup()
        # Only run in normal mode
        self.setup_dev_mode(False)


    def kill_powerd(self):
        """Stop powerd on client."""
        self.faft_client.run_shell_command("stop powerd")


    def debounce_power_button(self):
        """Check if power button debouncing works.

        Press power button for a very short period and checks for power
        button keycode.
        """
        # Delay 3 seconds to allow "showkey" to start on client machine.
        # Press power button for only 10ms. Should be debounced.
        Timer(3, self.servo.power_key, [0.001]).start()
        lines = self.faft_client.run_shell_command_get_output("showkey")
        for line in lines:
            if re.search("keycode 116", line) is not None:
                return False
        return True


    def shutdown_and_wake(self,
                          shutdown_powerkey_duration,
                          wake_delay,
                          wake_powerkey_duration):
        """
        Shutdown the system by power button, delay, and then power on
        by power button again.
        """
        self.servo.power_key(shutdown_powerkey_duration)
        Timer(wake_delay, self.servo.power_key, [wake_powerkey_duration]).start()



    def run_once(self, host=None):
        if not self.check_ec_capability():
            return
        self.register_faft_sequence((
            {   # Step 1, Shutdown when powerd is still running and wake from S5
                #         with short power button press.
                'state_checker': self.debounce_power_button,
                'reboot_action': (self.shutdown_and_wake,
                                  (self.POWER_BUTTON_POWERD_DURATION,
                                   self.SHORT_WAKE_DELAY,
                                   self.POWER_BUTTON_SHORT_POWER_ON_DURATION)),
            },
            {   # Step 2, Shutdown when powerd is stopped and wake from G3
                #         with short power button press.
                'userspace_action': self.kill_powerd,
                'reboot_action': (self.shutdown_and_wake,
                                  (self.POWER_BUTTON_NO_POWERD_DURATION,
                                   self.LONG_WAKE_DELAY,
                                   self.POWER_BUTTON_SHORT_POWER_ON_DURATION)),
            },
            {   # Step 3, Shutdown when powerd is still running and wake from G3
                #         with long power button press.
                'reboot_action': (self.shutdown_and_wake,
                                  (self.POWER_BUTTON_POWERD_DURATION,
                                   self.LONG_WAKE_DELAY,
                                   self.POWER_BUTTON_LONG_POWER_ON_DURATION)),
            },
            {   # Step 4, Shutdown when powerd is stopped and wake from S5
                #         with long power button press.
                'userspace_action': self.kill_powerd,
                'reboot_action': (self.shutdown_and_wake,
                                  (self.POWER_BUTTON_NO_POWERD_DURATION,
                                   self.SHORT_WAKE_DELAY,
                                   self.POWER_BUTTON_LONG_POWER_ON_DURATION)),
            },
            {   # Step 5, dummy step to ensure reboot in step 4
            }
        ))
        self.run_faft_sequence()
