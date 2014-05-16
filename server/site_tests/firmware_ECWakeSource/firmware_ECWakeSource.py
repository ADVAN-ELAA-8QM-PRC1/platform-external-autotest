# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
from threading import Timer
import time

from autotest_lib.client.common_lib import error
from autotest_lib.server.cros.faft.firmware_test import FirmwareTest


def delayed(seconds):
    def decorator(f):
        def wrapper(*args, **kargs):
            t = Timer(seconds, f, args, kargs)
            t.start()
        return wrapper
    return decorator


class firmware_ECWakeSource(FirmwareTest):
    """
    Servo based EC wake source test.
    """
    version = 1

    # Delay for waiting client to return before EC suspend
    EC_SUSPEND_DELAY = 5

    # Delay between EC suspend and wake
    WAKE_DELAY = 5

    # Delay between closing and opening lid
    LID_DELAY = 1

    # Delay for waiting client to shut down
    SHUTDOWN_DELAY = 10

    def initialize(self, host, cmdline_args):
        super(firmware_ECWakeSource, self).initialize(host, cmdline_args)
        # Only run in normal mode
        self.setup_dev_mode(False)

    @delayed(WAKE_DELAY)
    def wake_by_power_button(self):
        """Delay by WAKE_DELAY seconds and then wake DUT with power button."""
        self.servo.power_normal_press()

    @delayed(WAKE_DELAY)
    def wake_by_lid_switch(self):
        """Delay by WAKE_DELAY seconds and then wake DUT with lid switch."""
        self.servo.set('lid_open', 'no')
        time.sleep(self.LID_DELAY)
        self.servo.set('lid_open', 'yes')

    def suspend_as_reboot(self, wake_func):
        """
        Suspend DUT and also kill FAFT client so that this acts like a reboot.

        Args:
          wake_func: A function that is called to wake DUT. Note that this
            function must delay itself so that we don't wake DUT before
            suspend_as_reboot returns.
        """
        cmd = '(sleep %d; powerd_dbus_suspend) &' % self.EC_SUSPEND_DELAY
        self.faft_client.system.run_shell_command(cmd)
        self.faft_client.disconnect()
        time.sleep(self.EC_SUSPEND_DELAY)
        wake_func()

    def hibernate_and_wake_by_power_button(self):
        """Shutdown and hibernate EC. Then wake by power button."""
        self.faft_client.system.run_shell_command("shutdown -P now")
        time.sleep(self.SHUTDOWN_DELAY)
        self.ec.send_command("hibernate 1000")
        time.sleep(self.WAKE_DELAY)
        self.servo.power_short_press()

    def run_once(self):
        # TODO(victoryang): make this test run on both x86 and arm
        if not self.check_ec_capability(['x86', 'lid']):
            raise error.TestNAError("Nothing needs to be tested on this device")

        logging.info("Suspend and wake by power button.")
        self.do_reboot_action((self.suspend_as_reboot,
                               self.wake_by_power_button))
        self.wait_for_client()

        logging.info("Suspend and wake by lid switch.")
        self.do_reboot_action((self.suspend_as_reboot,
                               self.wake_by_lid_switch))
        self.wait_for_client()

        logging.info("EC hibernate and wake by power button.")
        self.do_reboot_action(self.hibernate_and_wake_by_power_button)
        self.wait_for_client()
