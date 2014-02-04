# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import dbus
import logging

from autotest_lib.client.bin import test
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros.cellular import mm1_constants
from autotest_lib.client.cros.cellular.pseudomodem import pm_constants
from autotest_lib.client.cros.cellular.pseudomodem import pseudomodem_context
from autotest_lib.client.cros.networking.chrome_testing \
        import chrome_networking_test_context as cntc
from autotest_lib.client.cros.networking.chrome_testing import test_utils

class network_ChromeCellularSmokeTest(test.test):
    """
    Tests that Chrome can bring the network to a connected state and effectively
    access the internet through the cellular network. The test repeats a
    connect/disconnect sequence several times and makes sure that Chrome can
    always connect to the network via chrome.networkingPrivate.

    """
    version = 1

    CONNECT_COUNT = 5

    def _setup_modem_proxy(self):
        self._bus = dbus.SystemBus()
        manager = self._bus.get_object(mm1_constants.I_MODEM_MANAGER,
                                       mm1_constants.MM1)
        imanager = dbus.Interface(manager, mm1_constants.I_OBJECT_MANAGER)
        devices = imanager.GetManagedObjects().keys()
        if len(devices) != 1:
            raise error.TestFail('Expected exactly one modem object, found: ' +
                                 len(devices))
        self._modem = self._bus.get_object(mm1_constants.I_MODEM_MANAGER,
                                           devices[0])


    def _get_modem_state(self):
        iprops = dbus.Interface(self._modem, mm1_constants.I_PROPERTIES)
        return iprops.Get(mm1_constants.I_MODEM,
                          mm1_constants.MM_MODEM_PROPERTY_NAME_STATE)


    def _get_cellular_network(self):
        networks = self._chrome_testing.find_cellular_networks()
        if len(networks) != 1:
            raise error.TestFail(
                    'Expected 1 cellular network, found ' + str(len(networks)))
        network = networks[0]
        test_utils.simple_network_sanity_check(
                network, pm_constants.DEFAULT_TEST_NETWORK_PREFIX,
                self._chrome_testing.CHROME_NETWORK_TYPE_CELLULAR)
        return network


    def _assert_modem_state(self, expected_state):
        modem_state = self._get_modem_state()
        if modem_state != expected_state:
            raise error.TestFail(
                    'Expected modem state to be "' +
                    mm1_constants.ModemStateToString(expected_state) +
                    '", found: ' +
                    mm1_constants.ModemStateToString(modem_state))


    def _ensure_network_status(self, network_id, status, timeout):
        test_utils.check_ui_property(
                self._chrome_testing, network_id, 'ConnectionState', status)


    def _disconnect_cellular_network(self):
        # Make sure that the network becomes disconnected.
        network_id = self._network['GUID']
        logging.info('Disconnecting from network: ' + network_id)
        call_status = self._chrome_testing.call_test_function(
                test_utils.LONG_TIMEOUT,
                'disconnectFromNetwork',
                '"' + network_id + '"')
        logging.info('Checking that the network is disconnected.')
        self._ensure_network_status(
                network_id, 'NotConnected', test_utils.LONG_TIMEOUT)
        logging.info('The network is disconnected. Checking that the modem is '
                     'in the REGISTERED state.')
        self._assert_modem_state(mm1_constants.MM_MODEM_STATE_REGISTERED)
        logging.info('Modem is disconnected. Disconnect was successful.')


    def _connect_cellular_network(self):
        # Make sure that the network becomes connected.
        network_id = self._network['GUID']
        logging.info('Connecting to network: ' + network_id)
        call_status = self._chrome_testing.call_test_function(
                test_utils.LONG_TIMEOUT,
                'connectToNetwork',
                '"' + network_id + '"')
        logging.info('Checking that the network is connected.')
        self._ensure_network_status(
                network_id, 'Connected', test_utils.LONG_TIMEOUT)
        logging.info('The network is connected. Checking that the modem is in '
                     'the CONNECTED state.')
        self._assert_modem_state(mm1_constants.MM_MODEM_STATE_CONNECTED)
        logging.info('Modem is connected. Connect was successful.')


    def _run_once_internal(self):
        # Set up a ModemManager proxy to use to verify the modem state.
        self._setup_modem_proxy()

        # Make sure that there is a single cellular network and it matches
        # the data from pseudomm.
        self._network = self._get_cellular_network()

        # Disconnect from the network before doing any operations.
        self._disconnect_cellular_network()

        logging.info('Starting connect/disconnect sequence.')
        for _ in xrange(self.CONNECT_COUNT):
            self._connect_cellular_network()
            self._disconnect_cellular_network()


    def run_once(self, family):
        with pseudomodem_context.PseudoModemManagerContext(
                True,
                {'family' : family}):
            with cntc.ChromeNetworkingTestContext() as testing_context:
                self._chrome_testing = testing_context
                self._run_once_internal()
