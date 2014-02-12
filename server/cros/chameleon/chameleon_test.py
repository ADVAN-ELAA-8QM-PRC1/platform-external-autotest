# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import operator
import os

from autotest_lib.client.common_lib import error
from autotest_lib.server import test
from autotest_lib.server.cros.chameleon import display_client


class ChameleonTest(test.test):
    """This is the base class of Chameleon tests.

    This base class initializes Chameleon board and its related services,
    like connecting Chameleond and DisplayClient. Also kills the connections
    on cleanup.
    """

    def initialize(self, host, test_data_dir=None):
        """Initializes.

        @param host: The Host object of DUT.
        @param test_data_dir: Path to the test data directory. A HTTP daemon
                serves this directory as its root. If None, the HTTP daemon
                doesn't run.
        """
        self.display_client = display_client.DisplayClient(host)
        self.display_client.initialize(test_data_dir)
        self.chameleon = host.chameleon
        self.chameleon_port = self._get_connected_port()
        if self.chameleon_port is None:
            raise error.TestError('DUT and Chameleon board not connected')


    def cleanup(self):
        """Cleans up."""
        if self.display_client:
            self.display_client.cleanup()


    def _get_connected_port(self):
        """Gets the first connected output port between Chameleon and DUT.

        @return: A ChameleonPort object.
        """
        # TODO(waihong): Support multiple connectors.
        for chameleon_port in self.chameleon.get_all_ports():
            # Plug to ensure the connector is plugged.
            chameleon_port.plug()
            connector_type = chameleon_port.get_connector_type()
            output = self.display_client.get_connector_name()

            # TODO(waihong): Make sure eDP work in this way.
            if output and output.startswith(connector_type):
                return chameleon_port
        return None


    def check_screen_with_chameleon(self,
            tag, pixel_diff_value_margin=0, total_wrong_pixels_margin=0):
        """Checks the DUT external screen with Chameleon.

        1. Capture the whole screen from the display buffer of Chameleon.
        2. Capture the framebuffer on DUT.
        3. Verify that the captured screen match the content of DUT framebuffer.

        @param tag: A string of tag for the prefix of output filenames.
        @param pixel_diff_value_margin: The margin for comparing a pixel. Only
                if a pixel difference exceeds this margin, will treat as a wrong
                pixel.
        @param total_wrong_pixels_margin: The margin for the number of wrong
                pixels. If the total number of wrong pixels exceeds this margin,
                the check fails.

        @return: None if the check passes; otherwise, a string of error message.
        """
        logging.info('Checking screen with Chameleon (tag: %s)...', tag)
        chameleon_path = os.path.join(self.outputdir, '%s-chameleon.bgra' % tag)
        dut_path = os.path.join(self.outputdir, '%s-dut.bgra' % tag)

        logging.info('Capturing framebuffer on Chameleon.')
        chameleon_pixels = self.chameleon_port.capture_screen(chameleon_path)
        chameleon_pixels_len = len(chameleon_pixels)

        logging.info('Capturing framebuffer on DUT.')
        dut_pixels = self.display_client.capture_external_screen(dut_path)
        dut_pixels_len = len(dut_pixels)

        if chameleon_pixels_len != dut_pixels_len:
            message = ('Result of %s: lengths of pixels not match: %d != %d' %
                    (tag, chameleon_pixels_len, dut_pixels_len))
            logging.error(message)
            return message

        logging.info('Comparing the pixels...')
        total_wrong_pixels = 0
        # The dut_pixels array are formatted in BGRA.
        for i in xrange(0, len(dut_pixels), 4):
            # Skip the fourth byte, i.e. the alpha value.
            chameleon_pixel = tuple(ord(p) for p in chameleon_pixels[i:i+3])
            dut_pixel = tuple(ord(p) for p in dut_pixels[i:i+3])
            # Compute the maximal difference for a pixel.
            diff_value = max(map(abs, map(
                    operator.sub, chameleon_pixel, dut_pixel)))
            if (diff_value > pixel_diff_value_margin):
                if total_wrong_pixels == 0:
                    first_pixel_message = ('offset %d, %r != %r' %
                            (i, chameleon_pixel, dut_pixel))
                total_wrong_pixels += 1

        if total_wrong_pixels > 0:
            message = ('Result of %s: total %d wrong pixels, e.g. %s' %
                       (tag, total_wrong_pixels, first_pixel_message))
            if total_wrong_pixels > total_wrong_pixels_margin:
                logging.error(message)
                return message
            else:
                message += (', within the acceptable range %d' %
                            total_wrong_pixels_margin)
                logging.warn(message)
        else:
            logging.info('Result of %s: all pixels match', tag)
            for file_path in (chameleon_path, dut_path):
                os.remove(file_path)
        return None
