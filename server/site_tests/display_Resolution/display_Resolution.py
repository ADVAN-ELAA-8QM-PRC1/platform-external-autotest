# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This is a server side resolution display test using the Chameleon board."""

import logging
import os
import time

from autotest_lib.client.common_lib import error
from autotest_lib.server.cros.chameleon import chameleon_test


class display_Resolution(chameleon_test.ChameleonTest):
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
    # Allow a range of pixel value difference.
    PIXEL_DIFF_VALUE_MARGIN = 5
    # A range of pixel number which a cursor covers. We accept this number
    # of pixels not matched in the case of a cursor showed.
    CURSOR_PIXEL_NUMBER = 100
    # Time to wait the calibration image stable, like waiting the info
    # window "DisplayTestExtension triggered full screen" disappeared.
    CALIBRATION_IMAGE_SETUP_TIME = 10


    def initialize(self, host):
        self._test_data_dir = os.path.join(
                self.bindir, 'display_Resolution_test_data')
        super(display_Resolution, self).initialize(host, self._test_data_dir)


    def run_once(self, host, test_mirrored=False, test_suspend_resume=False):
        errors = []
        for tag, width, height in self.RESOLUTION_TEST_LIST:
            self.set_up_chameleon((tag, width, height))
            try:
                logging.info('Reconnect output...')
                self.display_client.reconnect_output_and_wait()
                logging.info('Set mirrored: %s', test_mirrored)
                self.display_client.set_mirrored(test_mirrored)

                if test_suspend_resume:
                    logging.info('Suspend and resume')
                    self.display_client.suspend_resume()
                    if host.wait_up(timeout=20):
                        logging.info('DUT is up')
                    else:
                        raise error.TestError('DUT is not up after resume')

                logging.info('Waiting the calibration image stable.')
                self.display_client.load_calibration_image((width, height))
                self.display_client.move_cursor_to_bottom_right()
                time.sleep(self.CALIBRATION_IMAGE_SETUP_TIME)

                error_message = self.check_screen_with_chameleon(
                        '%s-%dx%d' % (tag, width, height),
                        self.PIXEL_DIFF_VALUE_MARGIN,
                        self.CURSOR_PIXEL_NUMBER if test_mirrored else 0)
                if error_message:
                    errors.append(error_message)

            finally:
                self.display_client.close_tab()
                self.chameleon.reset()

        if errors:
            raise error.TestFail('; '.join(errors))


    def set_up_chameleon(self, resolution):
        """Loads the EDID of the given resolution onto Chameleon.

        @param resolution: A tuple (tag, width, height) representing the
                resolution to test.
        """
        logging.info('Setting up %r on port %d (%s)...',
                     resolution,
                     self.chameleon_port.get_connector_id(),
                     self.chameleon_port.get_connector_type())
        edid_filename = os.path.join(
                self._test_data_dir, 'edids', '%s_%dx%d' % resolution)
        if not os.path.exists(edid_filename):
            raise ValueError('EDID file %r does not exist' % edid_filename)

        logging.info('Apply edid: %s', edid_filename)
        self.chameleon_port.apply_edid(open(edid_filename).read())
