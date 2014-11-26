# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This is a display hot-plug and reboot test using the Chameleon board."""

import logging

from autotest_lib.server.cros.chameleon import chameleon_test


class display_HotPlugAtBoot(chameleon_test.ChameleonTest):
    """Display hot-plug and reboot test.

    This test talks to a Chameleon board and a DUT to set up, run, and verify
    DUT behavior response to different configuration of hot-plug during boot.
    """
    version = 1
    PLUG_CONFIGS = [
        # (plugged_before_boot, plugged_after_boot)
        (False, True),
        (True, True),
        (True, False),
    ]


    def run_once(self, host, test_mirrored=False):
        logging.info('See the display on Chameleon: port %d (%s)',
                     self.chameleon_port.get_connector_id(),
                     self.chameleon_port.get_connector_type())

        self.set_mirrored(test_mirrored)

        # Keep the original connector name, for later comparison.
        expected_connector = self.display_facade.get_external_connector_name()
        resolution = self.display_facade.get_external_resolution()
        logging.info('See the display on DUT: %s (%dx%d)', expected_connector,
                     *resolution)

        errors = []
        for plugged_before_boot, plugged_after_boot in self.PLUG_CONFIGS:
            logging.info('TESTING THE CASE: %s > reboot > %s',
                         'plug' if plugged_before_boot else 'unplug',
                         'plug' if plugged_after_boot else 'unplug')
            boot_id = host.get_boot_id()
            self.chameleon_port.set_plug(plugged_before_boot)

            # Don't wait DUT up. Do plug/unplug while booting.
            self.reboot(wait=False)

            host.test_wait_for_shutdown()
            self.chameleon_port.set_plug(plugged_after_boot)
            host.test_wait_for_boot(boot_id)

            self.display_facade.connect()
            self.check_external_display_connector(
                    expected_connector if plugged_after_boot else False)

            if plugged_after_boot:
                if test_mirrored and not self.is_mirrored_enabled():
                    error_message = 'Error: not rebooted to mirrored mode'
                    errors.append(error_message)
                    logging.error(error_message)
                    self.set_mirrored(True)
                else:
                    self.screen_test.test_screen_with_image(
                            resolution, test_mirrored, errors)

        self.raise_on_errors(errors)
