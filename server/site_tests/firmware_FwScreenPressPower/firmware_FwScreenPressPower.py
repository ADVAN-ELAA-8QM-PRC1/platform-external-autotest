# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import time

from autotest_lib.server.cros.faftsequence import FAFTSequence


class firmware_FwScreenPressPower(FAFTSequence):
    """
    Servo based power button triggered shutdown test during firmware screens.

    This test requires a USB disk plugged-in, which contains a Chrome OS test
    image (built by "build_image --test"). On runtime, this test triggers
    firmware screens (developer, remove, insert, yuck, and to_norm screens),
    and then presses the power button in order to power the machine down.
    """
    version = 1


    def wait_second_screen_and_press_power(self):
        """Wait and trigger a second screen and press power button."""
        self.wait_fw_screen_and_trigger_recovery()
        self.wait_longer_fw_screen_and_press_power()


    def wait_yuck_screen_and_press_power(self):
        """Insert corrupted USB for yuck screen and press power button."""
        # This USB stick will be removed in cleanup phase.
        self.servo.set('usb_mux_sel1', 'dut_sees_usbkey')
        time.sleep(self.delay.load_usb)
        self.wait_longer_fw_screen_and_press_power()


    def setup(self):
        super(firmware_FwScreenPressPower, self).setup()
        self.assert_test_image_in_usb_disk()
        self.setup_dev_mode(dev_mode=True)
        self.servo.set('usb_mux_sel1', 'servo_sees_usbkey')
        usb_dev = self.servo.probe_host_usb_dev()
        # Corrupt the kernel of USB stick. It is needed for triggering a
        # yuck screen later.
        self.corrupt_usb_kernel(usb_dev)


    def cleanup(self):
        self.servo.set('usb_mux_sel1', 'servo_sees_usbkey')
        usb_dev = self.servo.probe_host_usb_dev()
        # Restore the kernel of USB stick which is corrupted on setup phase.
        self.restore_usb_kernel(usb_dev)
        super(firmware_FwScreenPressPower, self).cleanup()



    def run_once(self):
        self.register_faft_sequence((
            {   # Step 1, expected dev mode and reboot.
                # When the next DEVELOPER SCREEN shown, press power button
                # to make DUT shutdown.
                'state_checker': (self.checkers.crossystem_checker, {
                    'devsw_boot': '1',
                    'mainfw_type': 'developer',
                }),
                'firmware_action': (self.run_shutdown_process,
                                    (self.wait_fw_screen_and_press_power,
                                     None,
                                     self.wait_fw_screen_and_ctrl_d)),
            },
            {   # Step 2, reboot. When the developer screen shown, press
                # enter key to trigger either TO_NORM screen (new) or
                # RECOVERY INSERT screen (old). Then press power button to
                # make DUT shutdown.
                'state_checker': (self.checkers.crossystem_checker, {
                    'devsw_boot': '1',
                    'mainfw_type': 'developer',
                }),
                'firmware_action': (self.run_shutdown_process,
                                    (self.wait_second_screen_and_press_power,
                                     None,
                                     self.wait_fw_screen_and_ctrl_d)),
            },
            {   # Step 3, request recovery boot. When the RECOVERY INSERT
                # screen shows, press power button to make DUT shutdown.
                'state_checker': (self.checkers.crossystem_checker, {
                    'devsw_boot': '1',
                    'mainfw_type': 'developer',
                }),
                'userspace_action': self.faft_client.request_recovery_boot,
                'firmware_action': (self.run_shutdown_process,
                                    (self.wait_longer_fw_screen_and_press_power,
                                     None,
                                     self.wait_fw_screen_and_ctrl_d)),
            },
            {   # Step 4, request recovery boot again. When the recovery
                # insert screen shows, insert a corrupted USB and trigger
                # a YUCK SCREEN. Then press power button to make DUT shutdown.
                'state_checker': (self.checkers.crossystem_checker, {
                    'devsw_boot': '1',
                    'mainfw_type': 'developer',
                }),
                'userspace_action': self.faft_client.request_recovery_boot,
                'firmware_action': (self.run_shutdown_process,
                                    (self.wait_yuck_screen_and_press_power,
                                     None,
                                     self.wait_fw_screen_and_ctrl_d)),
            },
            {   # Step 5, switch back to normal mode.
                'state_checker': (self.checkers.crossystem_checker, {
                    'devsw_boot': '1',
                    'mainfw_type': 'developer',
                }),
                'userspace_action': self.enable_normal_mode_and_reboot,
                'reboot_action': None,
            },
            {   # Step 6, expected normal mode and request recovery boot.
                # Because an USB stick is inserted, a RECOVERY REMOVE screen
                # shows. Press power button to make DUT shutdown.
                'state_checker': (self.checkers.crossystem_checker, {
                    'devsw_boot': '0',
                    'mainfw_type': 'normal',
                }),
                'userspace_action': self.faft_client.request_recovery_boot,
                'firmware_action': (self.run_shutdown_process,
                                    (self.wait_longer_fw_screen_and_press_power,
                                     None,
                                     None)),
            },
            {   # Step 7, done.
                'state_checker': (self.checkers.crossystem_checker, {
                    'devsw_boot': '0',
                    'mainfw_type': 'normal',
                }),
            },
        ))
        self.run_faft_sequence()
