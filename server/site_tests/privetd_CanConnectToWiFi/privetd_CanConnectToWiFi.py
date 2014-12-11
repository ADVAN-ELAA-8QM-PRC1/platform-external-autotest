# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import time

from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros.network import xmlrpc_security_types
from autotest_lib.client.common_lib.cros.tendo import privetd_helper
from autotest_lib.server.cros.network import hostap_config
from autotest_lib.server.cros.network import wifi_cell_test_base


class privetd_CanConnectToWiFi(wifi_cell_test_base.WiFiCellTestBase):
    """Tests that privetd can take WiFi credentials and give them to shill."""
    version = 1

    CONNECT_TIMEOUT_SECONDS = 45
    PASSPHRASE = 'chromeos'

    def run_once(self):
        """This test asserts that privetd can cause us to connect to an AP.

        1) Set up an AP.
        2) Restart privetd to disable cryptographic security around pairing.
        3) Provide WiFi credentials for the AP set up in 1).
        4) Assert that we connect
        5) Check that privetd reports the last configuration attempt successful.

        """
        wpa_config = xmlrpc_security_types.WPAConfig(
                psk=self.PASSPHRASE,
                wpa_mode=xmlrpc_security_types.WPAConfig.MODE_PURE_WPA,
                wpa_ciphers=[xmlrpc_security_types.WPAConfig.CIPHER_TKIP])
        router_conf = hostap_config.HostapConfig(
                channel=1,
                mode=hostap_config.HostapConfig.MODE_11G,
                security_config=wpa_config)
        self.context.configure(router_conf)
        ssid = self.context.router.get_ssid()
        helper = privetd_helper.PrivetdHelper(host=self.context.client.host)
        helper.restart_privetd(log_verbosity=3, enable_ping=True,
                               disable_security=True)
        helper.ping_server(use_https=False)
        helper.ping_server(use_https=True)
        auth_token = helper.privet_auth()
        ssid = self.context.router.get_ssid()
        data = helper.setup_add_wifi_credentials(ssid, self.PASSPHRASE)
        helper.setup_start(data, auth_token)
        logging.info('Waiting for privetd to report connect successful.')
        start_time = time.time()
        while time.time() - start_time < self.CONNECT_TIMEOUT_SECONDS:
            if helper.wifi_setup_was_successful(ssid, auth_token):
                break
            time.sleep(0.5)
        else:
            raise error.TestFail('Timed out waiting for privetd to report '
                                 'connect success.')
        self.context.assert_ping_from_dut()
        # TODO(wiley) Check privetd's understanding of whether or not the setup
        #             was successful.
        self.context.client.shill.disconnect(self.context.router.get_ssid())


    def cleanup(self):
        helper = privetd_helper.PrivetdHelper(host=self.context.client.host)
        helper.restart_privetd()
        super(privetd_CanConnectToWiFi, self).cleanup()

