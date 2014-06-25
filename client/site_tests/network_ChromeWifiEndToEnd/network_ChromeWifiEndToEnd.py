# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import time

from autotest_lib.client.bin import test
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros.networking.chrome_testing \
        import chrome_networking_test_context as cntc
from autotest_lib.client.cros.networking.chrome_testing import test_utils
from collections import namedtuple

NetworkInfo = namedtuple('NetworkInfo', 'name guid connectionState security')

class network_ChromeWifiEndToEnd(test.test):
    """
    Tests the following with chrome.networkingPrivate APIs:
        1. Tests that the configured wifi networks are seen by Chrome.
        2. Tests the transitioning between various available networks.
        3. Tests that the enabling and disabling WiFi works.

    """
    version = 1

    WIFI_NETWORK_DEVICE = 'WiFi'

    SHORT_TIMEOUT = 2


    def _get_wifi_networks(self):
        """Get list of available wifi networks.

        @raises error.TestFail if no wifi networks are found.
        @return List of dictionaries containing wifi network information.

        """
        wifi_networks = self._chrome_testing.find_wifi_networks()
        if not wifi_networks:
            raise error.TestFail('No wifi networks found.')

        return wifi_networks


    def _extract_wifi_network_info(self, networks_found):
        """Extract the needed information from the list of networks found
        via API.

        @param networks_found: Networks found via getVisibleNetworks api.
        @return Formated list of available wifi networks.

        """
        network_list = []

        for network in networks_found:
          network = NetworkInfo(name=network['Name'],
                                guid=network['GUID'],
                                connectionState=network['ConnectionState'],
                                security=network['WiFi']['Security'])
          network_list.append(network)

        return network_list


    def _wifi_network_comparison(
            self, configured_service_name_list, wifi_name_list):
        """Compare the known wifi SSID's against the SSID's returned via API.

        @param configured_service_name_list: Known SSID's that are configured
                by the network_WiFi_ChromeEndToEnd test.
        @param wifi_name_list: List of SSID's returned by the
                getVisibleNetworks API.
        @raises error.TestFail if network names do not match.

        """
        for name in configured_service_name_list:
            if name not in wifi_name_list:
                raise error.TestFail(
                    'Following network does not match: %s' % name)
        logging.info('Network names match!')


    def _enable_disable_network_check(
            self, original_enabled_networks, new_enabled_networks):
        """Tests enabling and disabling of WiFi.

        @param original_enabled_networks: List of network devices that were
                enabled when the test started.
        @param new_enabled_networks: List of network devices that are now
                now enabled.
        @raises error.TestFail if WiFi state is not toggled.

        """
        # Make sure we leave the WiFi network device in enabled state before
        # ending the test.
        self._enable_network_device(self.WIFI_NETWORK_DEVICE)

        if (self.WIFI_NETWORK_DEVICE in original_enabled_networks and
                self.WIFI_NETWORK_DEVICE in new_enabled_networks):
            raise error.TestFail('WiFi was not disabled.')
        if (self.WIFI_NETWORK_DEVICE not in original_enabled_networks and
                self.WIFI_NETWORK_DEVICE not in new_enabled_networks):
            raise error.TestFail('WiFi was not enabled.')
        logging.info('Enabling / Disabling WiFi works!')


    def _get_enabled_network_devices(self):
        """Get list of enabled network devices on the device.

        @return List of enabled network devices.

        """
        enabled_network_types = self._chrome_testing.call_test_function(
                test_utils.LONG_TIMEOUT,
                'getEnabledNetworkDevices')
        for key, value in enabled_network_types.items():
            if key == 'result':
                logging.info('Enabled Network Devices: %s', value)
                return value


    def _enable_network_device(self, network):
        """Enable given network device.

        @param network: string name of the network device to be enabled. Options
                include 'WiFi', 'Cellular' and 'Ethernet'.

        """
        logging.info('Enabling: %s', network)
        enable_network_result = self._chrome_testing.call_test_function_async(
                'enableNetworkDevice',
                '"' + network + '"')
        # Added delay to allow DUT enough time to fully transition into enabled
        # state before other actions are performed.
        time.sleep(self.SHORT_TIMEOUT)


    def _disable_network_device(self, network):
        """Disable given network device.

        @param network: string name of the network device to be disabled.
                Options include 'WiFi', 'Cellular' and 'Ethernet'.

        """
        # Do ChromeOS browser session teardown/setup before disabling the
        # network device because chrome.networkingPrivate.disableNetworkType API
        # fails to disable the network device on subsequent calls if we do not
        # teardown and setup the browser session.
        self._chrome_testing.teardown()
        self._chrome_testing.setup()

        logging.info('Disabling: %s', network)
        disable_network_result = self._chrome_testing.call_test_function_async(
                'disableNetworkDevice',
                '"' + network + '"')


    def _scan_for_networks(self):
        self._chrome_testing.call_test_function_async('requestNetworkScan')
        # Added delay to allow enough time for Chrome to scan and get all the
        # network ssids and make them available for the test to use.
        time.sleep(self.SHORT_TIMEOUT)


    def _find_and_transition_wifi_networks_in_range(self):
        """Verify all WiFi networks in range are displayed."""
        known_service_names_in_wifi_cell = [self.SSID_1, self.SSID_2]
        networks_found_via_api = self._get_wifi_networks()
        network_list = self._extract_wifi_network_info(networks_found_via_api)
        logging.info('Networks found via API: %s', networks_found_via_api)

        wifi_names_found_via_api = []
        known_wifi_network_details = []

        for network in network_list:
            if network.name in known_service_names_in_wifi_cell:
                known_wifi_network_details.append(network)
            wifi_names_found_via_api.append(network.name)

        if self.TEST in ('all', 'findVerifyWiFiNetworks'):
            self._wifi_network_comparison(
                    known_service_names_in_wifi_cell, wifi_names_found_via_api)
        if self.TEST in ('all', 'transitionWiFiNetworks'):
            self._transition_wifi_networks(known_wifi_network_details)


    def _enable_disable_wifi(self):
        """Verify that the test is able to enable and disable WiFi."""
        original_enabled_networks = self._get_enabled_network_devices()
        if self.WIFI_NETWORK_DEVICE in original_enabled_networks:
            self._disable_network_device(self.WIFI_NETWORK_DEVICE)
        else:
            self._enable_network_device(self.WIFI_NETWORK_DEVICE)
        new_enabled_networks = self._get_enabled_network_devices()
        self._enable_disable_network_check(
                original_enabled_networks, new_enabled_networks)


    def _transition_wifi_networks(self, known_wifi_networks):
        """Verify that the test is able to transition between the two known
        wifi networks.

        @param known_wifi_networks: List of known wifi networks.
        @raises error.TestFail if device is not able to transition to a
                known wifi network.

        """
        if not known_wifi_networks:
            raise error.TestFail('No pre-configured network available for '
                                 'connection/transition.')

        for network in known_wifi_networks:
            new_network_connect = self._chrome_testing.call_test_function(
                    test_utils.LONG_TIMEOUT,
                    'connectToNetwork',
                    '"' + network.guid +'"')
            if (new_network_connect['status'] ==
                    'chrome-test-call-status-failure'):
                raise error.TestFail(
                        'Could not connect to %s network. Error returned by '
                        'chrome.networkingPrivate.startConnect API: %s' %
                        (network.name, new_network_connect['error']))
            logging.info('Successfully transitioned to: %s', network.name)


    def run_once(self, ssid_1, ssid_2, test):
        """Run the test.

        @param ssid_1: SSID of the first AP.
        @param ssid_2: SSID of the second AP.
        @param test: Set by the server test control file depending on the test
                that is being run.

        """
        self.SSID_1 = ssid_1
        self.SSID_2 = ssid_2
        self.TEST = test

        with cntc.ChromeNetworkingTestContext() as testing_context:
            self._chrome_testing = testing_context
            enabled_networks_devices = self._get_enabled_network_devices()
            if self.WIFI_NETWORK_DEVICE not in enabled_networks_devices:
                self._enable_network_device(self.WIFI_NETWORK_DEVICE)
            self._scan_for_networks()

            if test == 'all':
                self._find_and_transition_wifi_networks_in_range()
                self._enable_disable_wifi()
            elif test in ('findVerifyWiFiNetworks', 'transitionWiFiNetworks'):
                self._find_and_transition_wifi_networks_in_range()
            elif test == 'enableDisableWiFi':
                self._enable_disable_wifi()
