# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import time

from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib import utils
from autotest_lib.client.common_lib.cros.network import iw_runner
from autotest_lib.client.common_lib.cros.network import ping_runner
from autotest_lib.client.common_lib.cros.network import xmlrpc_datatypes
from autotest_lib.server import hosts
from autotest_lib.server import site_linux_router
from autotest_lib.server import site_linux_server
from autotest_lib.server.cros import wifi_test_utils
from autotest_lib.server.cros.network import wifi_client


class WiFiTestContextManager(object):
    """A context manager for state used in WiFi autotests.

    Some of the building blocks we use in WiFi tests need to be cleaned up
    after use.  For instance, we start an XMLRPC server on the client
    which should be shut down so that the next test can start its instance.
    It is convenient to manage this setup and teardown through a context
    manager rather than building it into the test class logic.

    """
    CMDLINE_CLIENT_PACKET_CAPTURES = 'client_capture'
    CMDLINE_PACKET_CAPTURE_SNAPLEN = 'capture_snaplen'
    CMDLINE_ROUTER_ADDR = 'router_addr'
    CMDLINE_ROUTER_PACKET_CAPTURES = 'router_capture'
    CMDLINE_ROUTER_PORT = 'router_port'
    CONNECTED_STATES = 'ready', 'portal', 'online'


    @property
    def router_address(self):
        """@return string address of WiFi router host in test."""
        hostname = self.client.host.hostname
        if utils.host_is_in_lab_zone(hostname):
            # Lab naming convention in: go/chromeos-lab-hostname-convention
            return wifi_test_utils.get_router_addr_in_lab(hostname)

        elif self.CMDLINE_ROUTER_ADDR in self._cmdline_args:
            return self._cmdline_args[self.CMDLINE_ROUTER_ADDR]

        raise error.TestError('Test not running in lab zone and no '
                              'router address given')


    def __init__(self, test_name, host, cmdline_args, debug_dir):
        """Construct a WiFiTestContextManager.

        Optionally can pull addresses of the server address, router address,
        or router port from cmdline_args.

        @param test_name string descriptive name for this test.
        @param host host object representing the DUT.
        @param cmdline_args dict of key, value settings from command line.

        """
        super(WiFiTestContextManager, self).__init__()
        self._test_name = test_name
        self._cmdline_args = cmdline_args.copy()
        self._client_proxy = wifi_client.WiFiClient(host, debug_dir)
        self._router = None
        self._server = None
        self._enable_client_packet_captures = False
        self._enable_router_packet_captures = False
        self._packet_capture_snaplen = None


    def __enter__(self):
        self.setup()
        return self


    def __exit__(self, exc_type, exc_value, traceback):
        self.teardown()


    @property
    def client(self):
        """@return WiFiClient object abstracting the DUT."""
        return self._client_proxy


    @property
    def router(self):
        """@return router object (e.g. a LinuxCrosRouter)."""
        return self._router


    @property
    def server(self):
        """@return server object representing the server in the test."""
        return self._server


    def get_wifi_addr(self, ap_num=0):
        """Return an IPv4 address pingable by the client on the WiFi subnet.

        @param ap_num int number of AP.  Only used in stumpy cells.
        @return string IPv4 address.

        """
        if self.router.has_local_server():
            return self.router.local_server_address(ap_num)
        return self.server.wifi_ip


    def get_wifi_if(self, ap_num=0):
        """Returns the interface name for the IP address of self.get_wifi_addr.

        @param ap_num int number of AP.  Only used in stumpy cells.
        @return string interface name "e.g. wlan0".

        """
        if self.router.has_local_server():
            return self.router.local_servers[ap_num]['interface']

        return self.server.wifi_if


    def get_wifi_host(self):
        """@return host object representing a pingable machine."""
        if self.router.has_local_server():
            return self.router.host

        return self.server.host


    def configure(self, configuration_parameters, multi_interface=None,
                  is_ibss=None):
        """Configure a router with the given parameters.

        Configures an AP according to the specified parameters and
        enables whatever packet captures are appropriate.  Will deconfigure
        existing APs unless |multi_interface| is specified.

        @param configuration_parameters HostapConfig object.
        @param multi_interface True iff having multiple configured interfaces
                is expected for this configure call.
        @param is_ibss True iff this is an IBSS endpoint.

        """
        configuration_parameters.security_config.install_router_credentials(
                self.router.host)
        if is_ibss:
            if multi_interface:
                raise error.TestFail('IBSS mode does not support multiple '
                                     'interfaces.')

            self.router.ibss_configure(configuration_parameters)
        else:
            self.router.hostap_configure(configuration_parameters,
                                         multi_interface=multi_interface)
        if self._enable_client_packet_captures:
            self.client.start_capture(configuration_parameters.frequency,
                                      snaplen=self._packet_capture_snaplen)
        if self._enable_router_packet_captures:
            self.router.start_capture(
                    configuration_parameters.frequency,
                    ht_type=configuration_parameters.ht_packet_capture_mode,
                    snaplen=self._packet_capture_snaplen)


    def setup(self):
        """Construct the state used in a WiFi test."""
        # Build up our router we're going to use in the test.  This involves
        # figuring out what kind of test setup we're using.
        router_port = int(self._cmdline_args.get(self.CMDLINE_ROUTER_PORT, 22))
        logging.info('Connecting to router at %s:%d',
                     self.router_address, router_port)
        ping_helper = ping_runner.PingRunner()
        ping_config = ping_runner.PingConfig(self.router_address, count=3,
                                             interval=0.5, ignore_result=True,
                                             ignore_status=True)
        ping_result = ping_helper.ping(ping_config).loss
        if ping_result is None or ping_result:
            raise error.TestFail('Router at %s is not pingable!' %
                                 self.router_address)

        self._router = site_linux_router.LinuxRouter(
                hosts.SSHHost(self.router_address, port=router_port),
                self._test_name)
        # The '_server' is a machine which hosts network services, such as
        # OpenVPN or StrongSwan.  Note that we make a separate SSHHost instance
        # here because both the server and the router expect to close() their
        # host, and only one close() is permitted.
        self._server = site_linux_server.LinuxServer(
                hosts.SSHHost(self.router_address, port=router_port), {})
        # Set up a clean context to conduct WiFi tests in.
        self.client.shill.init_test_network_state()
        if self.CMDLINE_CLIENT_PACKET_CAPTURES in self._cmdline_args:
            self._enable_client_packet_captures = True
        if self.CMDLINE_ROUTER_PACKET_CAPTURES in self._cmdline_args:
            self._enable_router_packet_captures = True
        if self.CMDLINE_PACKET_CAPTURE_SNAPLEN in self._cmdline_args:
            self._packet_capture_snaplen = int(
                    self._cmdline_args[self.CMDLINE_PACKET_CAPTURE_SNAPLEN])
        for system in (self.client, self.server, self.router):
            system.sync_host_times()


    def teardown(self):
        """Teardown the state used in a WiFi test."""
        logging.debug('Tearing down the test context.')
        for system in [self.client, self._router, self._server]:
            if system is not None:
                system.close()


    def assert_connect_wifi(self, wifi_params):
        """Connect to a WiFi network and check for success.

        Connect a DUT to a WiFi network and check that we connect successfully.

        @param wifi_params AssociationParameters describing network to connect.

        """
        logging.info('Connecting to %s.', wifi_params.ssid)
        assoc_result = xmlrpc_datatypes.deserialize(
                self.client.shill.connect_wifi(wifi_params))
        logging.info('Finished connection attempt to %s with times: '
                     'discovery=%.2f, association=%.2f, configuration=%.2f.',
                     wifi_params.ssid,
                     assoc_result.discovery_time,
                     assoc_result.association_time,
                     assoc_result.configuration_time)

        if assoc_result.success and wifi_params.expect_failure:
            raise error.TestFail(
                    'Expected connect to fail, but it was successful.')

        if not assoc_result.success and not wifi_params.expect_failure:
            raise error.TestFail('Expected connect to succeed, but it failed '
                                 'with reason: %s.' %
                                 assoc_result.failure_reason)

        if wifi_params.expect_failure:
            logging.info('Unable to connect to %s (as intended).',
                         wifi_params.ssid)
            return

        logging.info('Connected successfully to %s.', wifi_params.ssid)


    def assert_ping_from_dut(self, ping_config=None, ap_num=None):
        """Ping a host on the WiFi network from the DUT.

        Ping a host reachable on the WiFi network from the DUT, and
        check that the ping is successful.  The host we ping depends
        on the test setup, sometimes that host may be the server and
        sometimes it will be the router itself.  Ping-ability may be
        used to confirm that a WiFi network is operating correctly.

        @param ping_config optional PingConfig object to override defaults.
        @param ap_num int which AP to ping if more than one is configured.

        """
        if ap_num is None:
            ap_num = 0
        if ping_config is None:
            ping_ip = self.get_wifi_addr(ap_num=ap_num)
            ping_config = ping_runner.PingConfig(ping_ip)
        self.client.ping(ping_config)


    def assert_ping_from_server(self, ping_config=None):
        """Ping the DUT across the WiFi network from the server.

        Check that the ping is mostly successful and fail the test if it
        is not.

        @param ping_config optional PingConfig object to override defaults.

        """
        logging.info('Pinging from server.')
        if ping_config is None:
            ping_ip = self.client.wifi_ip
            ping_config = ping_runner.PingConfig(ping_ip)
        self.server.ping(ping_config)


    def wait_for_connection(self, ssid, freq=None, ap_num=None,
                            timeout_seconds=30):
        """Verifies a connection to network ssid on frequency freq.

        @param ssid string ssid of the network to check.
        @param freq int frequency of network to check.
        @param ap_num int AP to which to connect
        @param timeout_seconds int number of seconds to wait for
                connection on the given frequency.

        """
        POLLING_INTERVAL_SECONDS = 1.0
        start_time = time.time()
        duration = lambda: time.time() - start_time
        success = False
        while duration() < timeout_seconds:
            success, state, _ = self.client.wait_for_service_states(
                    ssid, self.CONNECTED_STATES, timeout_seconds - duration())
            if not success:
                time.sleep(POLLING_INTERVAL_SECONDS)
                continue

            if freq:
                actual_freq = self.client.get_iw_link_value(
                        iw_runner.IW_LINK_KEY_FREQUENCY)
                if str(freq) != actual_freq:
                    time.sleep(POLLING_INTERVAL_SECONDS)
                    continue

            self.assert_ping_from_dut(ap_num=ap_num)
            return

        freq_error_str = (' on frequency %d Mhz' % freq) if freq else ''
        raise error.TestFail(
                'Failed to connect to "%s"%s in %f seconds (state=%s)' %
                (ssid, freq_error_str, duration(), state))
