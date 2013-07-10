# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from autotest_lib.client.common_lib.cros.network import xmlrpc_datatypes
from autotest_lib.server import site_linux_system
from autotest_lib.server.cros.wlan import hostap_config
from autotest_lib.server.cros.network import wifi_cell_test_base


class network_WiFi_IBSS(wifi_cell_test_base.WiFiCellTestBase):
    """Test that we can connect to an IBSS (Adhoc) endpoint."""
    version = 1


    def run_once(self):
        """Body of the test."""
        self.context.router.require_capabilities(
                [site_linux_system.LinuxSystem.CAPABILITY_IBSS])
        self.context.router.create_wifi_device(device_type='ibss')
        configuration = hostap_config.HostapConfig(
                frequency=2412, mode=hostap_config.HostapConfig.MODE_11B)
        self.context.configure(configuration, is_ibss=True)
        assoc_params = xmlrpc_datatypes.AssociationParameters()
        assoc_params.ssid = self.context.router.get_ssid()
        assoc_params.station_type = \
                xmlrpc_datatypes.AssociationParameters.STATION_TYPE_IBSS
        self.context.assert_connect_wifi(assoc_params)
        self.context.assert_ping_from_dut()
        self.context.client.shill.disconnect(assoc_params.ssid)
        self.context.router.deconfig()
