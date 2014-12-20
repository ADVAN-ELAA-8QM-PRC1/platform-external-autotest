# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from autotest_lib.client.common_lib.cros.network import xmlrpc_datatypes
from autotest_lib.server.cros.network import apmanager_service_provider
from autotest_lib.server.cros.network import wifi_cell_test_base


class apmanager_SimpleConnect(wifi_cell_test_base.WiFiCellTestBase):
    """Test that the DUT can connect to an AP created by apmanager."""
    version = 1


    XMLRPC_BRINGUP_TIMEOUT_SECONDS = 60


    def run_once(self):
        """Sets up a router, connects to it, pings it."""
        ssid = self.context.router.build_unique_ssid()
        with apmanager_service_provider.ApmanagerServiceProvider(
                self.context.router, ssid):
            assoc_params = xmlrpc_datatypes.AssociationParameters()
            assoc_params.ssid = ssid
            self.context.assert_connect_wifi(assoc_params)
            self.context.assert_ping_from_server()
        # AP is terminated, wait for client to become disconnected.
        success, state, elapsed_seconds = \
                self.context.client.wait_for_service_states(
                        ssid, ( 'idle', ), 30)
        if not success:
            raise error.TestFail('Failed to disconnect from %s after AP was '
                                 'terminated for %f seconds (state=%s)' %
                                 (ssid, elapsed_seconds, state))
