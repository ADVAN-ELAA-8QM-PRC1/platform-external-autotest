# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import time

from autotest_lib.client.common_lib import error
from autotest_lib.server.cros import dark_resume_utils
from autotest_lib.server.cros.network import hostap_config
from autotest_lib.server.cros.network import wifi_cell_test_base
from autotest_lib.server.cros.network import wifi_client

_SHORT_DARK_RESUME_THRESHOLD = 3
_LONG_DARK_RESUME_THRESHOLD = 10
_SHORT_RECONNECT_WAIT_TIME_SECONDS = 5
_LONG_RECONNECT_WAIT_TIME_SECONDS = 35

class network_WiFi_WakeOnWiFiThrottling(wifi_cell_test_base.WiFiCellTestBase):
    """
    Test that the wake on WiFi throttling mechanism is triggered when the DUT
    wakes in dark resume too frequently.
    """

    version = 1

    def initialize(self, host):
        super(network_WiFi_WakeOnWiFiThrottling, self).initialize(host)
        """Set up for dark resume."""
        self._dr_utils = dark_resume_utils.DarkResumeUtils(host)


    def run_once(self):
        """Body of the test"""
        ap_ssid = self.configure_and_connect_to_ap(
                hostap_config.HostapConfig(channel=1))
        client = self.context.client
        client_mac = client.wifi_mac
        router = self.context.router

        if (client.is_wake_on_wifi_supported() is False):
            raise error.TestNAError('Wake on WiFi is not supported by this DUT')

        # Enable the wake on SSID feature in shill, and set the scan period.
        with client.wake_on_wifi_features(wifi_client.WAKE_ON_WIFI_SSID):
            logging.info('Set up WoWLAN')

            logging.info('Testing short dark resume threshold')
            with self._dr_utils.suspend():
                # Wait for suspend actions to finish.
                time.sleep(wifi_client.SUSPEND_WAIT_TIME_SECONDS)

                for iter_num in xrange(1, _SHORT_DARK_RESUME_THRESHOLD+1):
                    logging.info('Sending deauthentication message %d of %d' %
                            (iter_num, _SHORT_DARK_RESUME_THRESHOLD))
                    router.deauth_client(client_mac)

                    # Wait for the DUT to receive the disconnect, wake in
                    # dark resume, reconnect, then suspend again.
                    time.sleep(wifi_client.DISCONNECT_WAIT_TIME_SECONDS +
                               _SHORT_RECONNECT_WAIT_TIME_SECONDS)

            client.check_wake_on_wifi_throttled()

            prev_num_dark_resumes = self._dr_utils.count_dark_resumes()
            if prev_num_dark_resumes < _SHORT_DARK_RESUME_THRESHOLD:
                raise error.TestFail('Client did not enter the expected number '
                                     'of dark resumes (actual: %d, expected: %d'
                                     ')' % (num_dark_resumes,
                                            _SHORT_DARK_RESUME_THRESHOLD))

            # Since we wake from suspend and suspend again, the throttling
            # mechanism should be reset.
            logging.info('Testing long dark resume threshold')
            with self._dr_utils.suspend():
                # Wait for suspend actions to finish.
                time.sleep(wifi_client.SUSPEND_WAIT_TIME_SECONDS)

                for iter_num in xrange(1, _LONG_DARK_RESUME_THRESHOLD+1):
                    logging.info('Sending deauthentication message %d of %d' %
                            (iter_num, _LONG_DARK_RESUME_THRESHOLD))
                    router.deauth_client(client_mac)
                    # Wait for the DUT to receive the disconnect, wake in
                    # dark resume, reconnect, then suspend again. Wait longer
                    # than in the short threshold test above to avoid hitting
                    # the short dark resume threshold (i.e. 3 dark resumes in 1
                    # minute).
                    time.sleep(wifi_client.DISCONNECT_WAIT_TIME_SECONDS +
                               _LONG_RECONNECT_WAIT_TIME_SECONDS)

            client.check_wake_on_wifi_throttled()

            if (self._dr_utils.count_dark_resumes() -
                prev_num_dark_resumes) < _LONG_DARK_RESUME_THRESHOLD:
                raise error.TestFail('Client did not enter the expected number '
                                     'of dark resumes (actual: %d, expected: %d'
                                     ')' % (new_num_dark_resumes,
                                            _LONG_DARK_RESUME_THRESHOLD))


    def cleanup(self):
        self._dr_utils.teardown()
        # Make sure we clean up everything
        super(network_WiFi_WakeOnWiFiThrottling, self).cleanup()
