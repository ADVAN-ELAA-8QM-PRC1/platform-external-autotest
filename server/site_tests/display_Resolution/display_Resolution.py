# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This is a server side resolution display test using the Chameleon board."""

import logging
import os
import time

from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros.chameleon import chameleon_port_finder
from autotest_lib.client.cros.chameleon import chameleon_screen_test
from autotest_lib.client.cros.chameleon import edid
from autotest_lib.server import test
from autotest_lib.server.cros.multimedia import remote_facade_factory


class display_Resolution(test.test):
    """Server side external display test.

    This test talks to a Chameleon board and a DUT to set up, run, and verify
    external display function of the DUT.
    """
    version = 1
    RESOLUTION_TEST_LIST = [
            # Mix DP and HDMI together to test the converter cases.
            ('DP', 1280, 800),
            ('DP', 1440, 900),
            ('DP', 1600, 900),
            ('DP', 1680, 1050),
            ('DP', 1920, 1080),
            ('HDMI', 1280, 720),
            ('HDMI', 1920, 1080),
    ]

    def run_once(self, host, test_mirrored=False, test_suspend_resume=False,
                 test_reboot=False):
        factory = remote_facade_factory.RemoteFacadeFactory(host)
        display_facade = factory.create_display_facade()
        chameleon_board = host.chameleon

        chameleon_board.reset()
        finder = chameleon_port_finder.ChameleonVideoInputFinder(
                chameleon_board, display_facade)

        errors = []
        for chameleon_port in finder.iterate_all_ports():
            screen_test = chameleon_screen_test.ChameleonScreenTest(
                    chameleon_port, display_facade, self.outputdir)

            for interface, width, height in self.RESOLUTION_TEST_LIST:
                test_resolution = (width, height)
                test_name = "%s_%dx%d" % ((interface,) + test_resolution)

                if not edid.is_edid_supported(host, interface, width, height):
                    logging.info('skip unsupported EDID: %s', test_name)
                    continue

                if test_reboot:
                    logging.info('Reboot...')
                    boot_id = host.get_boot_id()
                    host.reboot(wait=False)
                    host.test_wait_for_shutdown()

                path = os.path.join(self.bindir, 'test_data', 'edids',
                                    test_name)
                logging.info('Use EDID: %s', test_name)
                with chameleon_port.use_edid_file(path):
                    utils.wait_for_value_changed(
                            display_facade.get_external_connector_name,
                            old_value=False)

                    if test_reboot:
                        host.test_wait_for_boot(boot_id)

                    logging.info('Set mirrored: %s', test_mirrored)
                    display_facade.set_mirrored(test_mirrored)
                    if test_suspend_resume:
                        if test_mirrored:
                            # magic sleep to wake up nyan_big in mirrored mode
                            # TODO: find root cause
                            time.sleep(6)
                        logging.info('Going to suspend...')
                        display_facade.suspend_resume()
                        logging.info('Resumed back')

                    screen_test.test_screen_with_image(
                            test_resolution, test_mirrored, errors)

        if errors:
            raise error.TestFail('; '.join(set(errors)))
