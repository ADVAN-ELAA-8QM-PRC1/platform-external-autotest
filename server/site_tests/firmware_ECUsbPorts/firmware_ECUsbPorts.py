# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging

from autotest_lib.client.common_lib import error
from autotest_lib.server.cros.faftsequence import FAFTSequence


class firmware_ECUsbPorts(FAFTSequence):
    """
    Servo based EC USB port control test.
    """
    version = 1


    # Delay for remote shell command call to return
    RPC_DELAY = 1

    # Delay between turning off and on USB ports
    REBOOT_DELAY = 6

    # Timeout range for waiting system to shutdown
    SHUTDOWN_TIMEOUT = 10


    def fake_reboot_by_usb_mode_change(self):
        """
        Turn off USB ports and also kill FAFT client so that this acts like a
        reboot. If USB ports cannot be turned off or on, reboot step would
        fail.
        """
        for_all_ports_cmd = ('id=0; while ectool usbchargemode "$id" %d;' +
                             'do id=$((id+1)); sleep 0.5; done')
        ports_off_cmd = for_all_ports_cmd % 0
        ports_on_cmd = for_all_ports_cmd % 3
        cmd = ("(sleep %d; %s; sleep %d; %s)&" %
                (self.RPC_DELAY, ports_off_cmd, self.REBOOT_DELAY, ports_on_cmd))
        self.faft_client.run_shell_command(cmd)
        self.kill_remote()


    def get_port_count(self):
        """
        Get the number of USB ports by checking the number of GPIO named
        USB*_ENABLE.
        """
        cnt = 0
        limit = 10
        while limit > 0:
            try:
                gpio_name = "USB%d_ENABLE" % (cnt + 1)
                self.send_uart_command_get_output(
                        "gpioget %s" % gpio_name,
                        "[01].\s*%s" % gpio_name,
                        timeout=1)
                cnt = cnt + 1
                limit = limit - 1
            except error.TestFail:
                logging.info("Found %d USB ports" % cnt)
                return cnt

        # Limit reached. Probably something went wrong.
        raise error.TestFail("Unexpected error while trying to determine " +
                             "number of USB ports")


    def wait_port_disabled(self, port_count, timeout):
        """
        Wait for all USB ports to be disabled.

        Args:
          port_count: Number of USB ports.
          timeout: Timeout range.
        """
        logging.info('Waiting for %d USB ports to be disabled.' % port_count)
        while timeout > 0:
            try:
                timeout = timeout - 1
                for idx in xrange(1, port_count+1):
                    gpio_name = "USB%d_ENABLE" % idx
                    self.send_uart_command_get_output(
                            "gpioget %s" % gpio_name,
                            "0.\s*%s" % gpio_name,
                            timeout=1)
                return True
            except error.TestFail:
                # USB ports not disabled. Retry.
                pass
        return False


    def check_power_off_mode(self):
        """Shutdown the system and check USB ports are disabled."""
        self._failed = False
        port_cnt = self.get_port_count()
        self.faft_client.run_shell_command("shutdown -P now")
        if not self.wait_port_disabled(port_cnt, self.SHUTDOWN_TIMEOUT):
            logging.info("Fails to wait for USB port disabled")
            self._failed = True
        self.servo.power_short_press()


    def check_failure(self):
        return not self._failed


    def run_once(self, host=None):
        if not self.check_ec_capability(['usb']):
            return
        self.register_faft_sequence((
            {   # Step 1, turn off all USB ports and then turn them on again
                'reboot_action': self.fake_reboot_by_usb_mode_change,
            },
            {   # Step 2, check USB ports are disabled when powered off
                'reboot_action': self.check_power_off_mode,
            },
            {   # Step 3, check if failure occurred
                'state_checker': self.check_failure,
            }
        ))
        self.run_faft_sequence()
