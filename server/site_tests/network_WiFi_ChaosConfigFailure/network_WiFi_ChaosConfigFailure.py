# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os

from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros.network import chaos_constants
from autotest_lib.server import test

class network_WiFi_ChaosConfigFailure(test.test):
    """ Test to grab debugging info about chaos configuration falures. """

    version = 1


    def _save_all_pages(self, ap):
        ap.establish_driver_connection()
        if not ap.driver_connection_established:
            logging.error('Unable to establish webdriver connection to '
                          'retrieve screenshots.')
            return
        for page in range(1, ap.get_number_of_pages() + 1):
            ap.navigate_to_page(page)
            ap.save_screenshot()


    def _write_screenshots(self, ap, filename):
        for (i, image) in enumerate(ap.get_all_screenshots()):
            path = os.path.join(self.outputdir,
                                str('%s_%d.png' % (filename, (i + 1))))
            with open(path, 'wb') as f:
                f.write(image.decode('base64'))


    def run_once(self, ap, error_string):
        """ Main entry function for autotest.

        There are three pieces of information we want to grab:
          1.) Screenshot at the point of failure
          2.) Screenshots of all pages
          3.) Stack trace of failure

        @param ap: an APConfigurator object
        @param error_string: String with the Configurator error description

        """

        if chaos_constants.AP_CONFIG_FAIL in error_string:
            self._write_screenshots(ap, 'config_failure')
            ap.clear_screenshot_list()
        self._save_all_pages(ap)
        self._write_screenshots(ap, 'final_configuration')
        ap.clear_screenshot_list()
        ap.reset_command_list()

        if chaos_constants.AP_CONFIG_FAIL in error_string:
            logging.error('Traceback:\n %s', ap.traceback)
            raise error.TestError('The AP was not configured correctly. Please '
                                  'see the ERROR log for more details.\n%s',
                                  ap.get_router_name())
        elif chaos_constants.AP_SECURITY_MISMATCH in error_string:
            raise error.TestError('The AP was not configured with correct '
                                  'security. Please check screenshots to '
                                  'debug.\n%s', ap.get_router_name())
        else:
            raise error.TestError('The SSID %s was not found in the scan. '
                                  'Check the screenshots to debug.\n%s',
                                  ap.ssid, ap.get_router_name())
