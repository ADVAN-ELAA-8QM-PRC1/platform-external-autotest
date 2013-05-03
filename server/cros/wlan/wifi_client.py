# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import re
import signal

from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros.network import interface
from autotest_lib.client.cros import constants
from autotest_lib.server import autotest
from autotest_lib.server.cros import remote_command
from autotest_lib.server.cros import wifi_test_utils
from autotest_lib.server.cros.wlan import packet_capturer


class WiFiClient(object):
    """WiFiClient is a thin layer of logic over a remote DUT in wifitests."""

    IW_LINK_KEY_BEACON_INTERVAL = 'beacon int'
    IW_LITNK_KEY_DTIM_PERIOD = 'dtim period'
    IW_LINK_KEY_FREQUENCY = 'freq'

    DEFAULT_PING_COUNT = 10
    COMMAND_PING = 'ping'


    @property
    def host(self):
        """@return host object representing the remote DUT."""
        return self._host


    @property
    def shill(self):
        """@return shill RPCProxy object."""
        return self._shill_proxy


    @property
    def client(self):
        """Deprecated accessor for the client host.

        The term client is used very loosely in old autotests and this
        accessor should not be used in new code.  Use host() instead.

        @return host object representing a remote DUT.

        """
        return self._host


    @property
    def command_ifconfig(self):
        """@return string path to ifconfig command."""
        return self._command_ifconfig


    @property
    def command_ip(self):
        """@return string path to ip command."""
        return self._command_ip


    @property
    def command_iperf(self):
        """@return string path to iperf command."""
        return self._command_iperf


    @property
    def command_iptables(self):
        """@return string path to iptables command."""
        return self._command_iptables


    @property
    def command_iw(self):
        """@return string path to iw command."""
        return self._command_iw


    @property
    def command_netdump(self):
        """@return string path to netdump command."""
        return self._command_netdump


    @property
    def command_netperf(self):
        """@return string path to netperf command."""
        return self._command_netperf


    @property
    def command_netserv(self):
        """@return string path to netserv command."""
        return self._command_netserv


    @property
    def command_ping6(self):
        """@return string path to ping6 command."""
        return self._command_ping6


    @property
    def command_wpa_cli(self):
        """@return string path to wpa_cli command."""
        return self._command_wpa_cli


    @property
    def wifi_if(self):
        """@return string wifi device on machine (e.g. mlan0)."""
        return self._wifi_if


    @property
    def wifi_mac(self):
        """@return string MAC address of self.wifi_if."""
        return self._interface.mac_address


    @property
    def wifi_ip(self):
        """@return string IPv4 address of self.wifi_if."""
        return self._interface.ipv4_address


    def __init__(self, client_host, result_dir):
        """
        Construct a WiFiClient.

        @param client_host host object representing a remote host.
        @param result_dir string directory to store test logs/packet caps.

        """
        super(WiFiClient, self).__init__()
        self._ping_thread = None
        self._host = client_host
        self._ping_stats = {}
        # Make sure the client library is on the device so that the proxy code
        # is there when we try to call it.
        client_at = autotest.Autotest(self.host)
        client_at.install()
        # Start up the XMLRPC proxy on the client
        self._shill_proxy = self.host.xmlrpc_connect(
                constants.SHILL_XMLRPC_SERVER_COMMAND,
                constants.SHILL_XMLRPC_SERVER_PORT,
                constants.SHILL_XMLRPC_SERVER_CLEANUP_PATTERN,
                constants.SHILL_XMLRPC_SERVER_READY_METHOD)
        # Look up or hardcode command paths.
        self._command_ifconfig = 'ifconfig'
        self._command_ip = wifi_test_utils.must_be_installed(
                self.host, '/usr/local/sbin/ip')
        self._command_iperf = wifi_test_utils.must_be_installed(
                self.host, '/usr/local/bin/iperf')
        self._command_iptables = '/sbin/iptables'
        self._command_iw = 'iw'
        self._command_netdump = 'tcpdump'
        self._command_netperf = wifi_test_utils.must_be_installed(
                self.host, '/usr/local/bin/netperf')
        self._command_netserv = wifi_test_utils.must_be_installed(
                self.host, '/usr/local/sbin/netserver')
        self._command_ping6 = 'ping6'
        self._command_wpa_cli = 'wpa_cli'
        # Look up the WiFi device (and its MAC) on the client.
        devs = wifi_test_utils.get_wlan_devs(self.host, self.command_iw)
        if not devs:
            raise error.TestFail('No wlan devices found on %s.' %
                                 self.host.hostname)

        if len(devs) > 1:
            logging.warning('Warning, found multiple WiFi devices on %s: %r',
                            self.host.hostname, devs)
        self._wifi_if = devs[0]
        self._interface = interface.Interface(self._wifi_if, host=self.host)
        # Used for packet captures.
        self._packet_capturer = packet_capturer.PacketCapturer(
                self.host, host_description='client',
                cmd_ifconfig=self.command_ifconfig, cmd_ip=self.command_ip,
                cmd_iw=self.command_iw, cmd_netdump=self.command_netdump)
        self._result_dir = result_dir

        self._firewall_rules = []


    def close(self):
        """Tear down state associated with the client."""
        if self._ping_thread is not None:
            self.ping_bg_stop()
        self.stop_capture()
        # This kills the RPC server.
        self._host.close()


    def ping(self, ping_ip, ping_args, save_stats=None, count=None):
        """Ping an address from the client and return the command output.

        @param ping_ip string IPv4 address for the client to ping.
        @param ping_args dict of parameters understood by
                wifi_test_utils.ping_args().
        @param save_stats string Key to save statistics of this ping
                run under for later similarity assertion.
        @param count int number of times to ping the address.
        @return string raw output of the ping command

        """
        if not count:
            count = self.DEFAULT_PING_COUNT
        # Timeout is 3s / ping packet.
        timeout = 3 * count
        ping_args = ping_args.copy()
        ping_args['count'] = count
        result = self.host.run(
                '%s %s %s' % (self.COMMAND_PING,
                              wifi_test_utils.ping_args(ping_args),
                              ping_ip),
                timeout=timeout)
        if save_stats:
            stats = wifi_test_utils.parse_ping_output(ping_output)
            self._ping_stats[save_stats] = stats
        return result.stdout


    def ping_bg(self, ping_ip, ping_args):
        """Ping an address from the client in the background.

        Only one instance of a background ping is supported at a time.

        @param ping_ip string IPv4 address for the client to ping.
        @param ping_args dict of parameters understood by
                wifi_test_utils.ping_args().

        """
        if self._ping_thread is not None:
            raise error.TestFail('Tried to start a background ping without '
                                 'stopping an earlier ping.')
        cmd = '%s %s %s' % (self.COMMAND_PING,
                            wifi_test_utils.ping_args(ping_args),
                            ping_ip)
        self._ping_thread = remote_command.Command(
                self.host, cmd, pkill_argument=self.COMMAND_PING)


    def ping_bg_stop(self, save_stats=None):
        """Stop pinging an address from the client in the background.

        Clean up state from a previous call to ping_bg.  If requested,
        statistics from the background ping run may be saved.

        @param save_stats string Key to save ping statistics under for
                later comparison, or None if no statistics should be
                saved.

        """
        if self._ping_thread is None:
            logging.info('Tried to stop a bg ping, but none was started')
            return
        # Sending SIGINT gives us stats at the end, how nice.
        self._ping_thread.join(signal.SIGINT)
        if save_stats:
            stats = wifi_test_utils.parse_ping_output(
                    self._ping_thread.result.stdout)
            self._ping_stats[save_stats] = stats
        self._ping_thread = None


    def assert_ping_similarity(self, key1, key2):
        """Assert that two specified sets of ping results are 'similar'.

        @param key1 string key given previously as a value for save_stats.
        @param key2 string key given previously as a value for save_stats.

        """
        stats0 = self._ping_stats[key1]
        stats1 = self._ping_stats[key2]
        if 'dev' not in stats0 or 'dev' not in stats1:
            raise error.TestFail('Missing standard dev from ping stats')
        if 'min' not in stats0 or 'min' not in stats1:
            raise error.TestFail('Missing max rtt from ping stats')
        if 'avg' not in stats0 or 'avg' not in stats1:
            raise error.TestFail('Missing avg rtt from ping stats')
        if 'max' not in stats0 or 'max' not in stats1:
            raise error.TestFail('Missing max rtt from ping stats')
        try:
            avg0 = float(stats0['avg'])
            max0 = float(stats0['max'])
            avg1 = float(stats1['avg'])
            max1 = float(stats1['max'])
        except ValueError:
            raise error.TestFail('Failed to parse ping statistics from avg/max '
                                 'pairs: %s/%s %s/%s',
                                 stats0['avg'], stats0['max'],
                                 stats1['avg'], stats1['max'])
        # This check is meant to assert that ping latency remains 'similar'
        # during WiFi background scans.  APs typically send beacons every 100ms,
        # (the period is configurable) so bgscan algorithms like to sit in a
        # channel for 100ms to see if they can catch a beacon.
        #
        # Assert that the maximum latency is under 200 ms + whatever the
        # average was for the other sample.  This allows us to go off chanel,
        # but forces us to serve some real traffic when we go back on.
        # We'll do this check symmetrically because we don't actually know
        # which is the control distribution and which is the potentially dirty
        # distribution.
        if max0 > 200 + avg1 or max1 > 200 + avg0:
            for name, stats in zip([key1, key2], [stats0, stats1]):
                logging.error('Ping %s min/avg/max/dev = %s/%s/%s/%s',
                              name,
                              stats['min'],
                              stats['avg'],
                              stats['max'],
                              stats['dev'])
            raise error.TestFail('Significant difference in rtt due to bgscan')


    def firewall_open(self, proto, src):
        """Opens up firewall to run iperf/netperf tests.

        By default, we have a firewall rule for NFQUEUE (see crbug.com/220736).
        In order to run iperf test, we need to add a new firewall rule BEFORE
        this NFQUEUE rule in the INPUT chain.

        @param proto a string, test traffic protocol, e.g. udp, tcp.
        @param src a string, subnet/mask.

        @return a string firewall rule added.

        """
        rule = 'INPUT -s %s/32 -p %s -m %s -j ACCEPT' % (src, proto, proto)
        self.host.run('%s -I %s' % (self._command_iptables, rule))
        self._firewall_rules.append(rule)
        return rule


    def _firewall_close(self, rule):
        """Removes firewall rule.

        @param rule a string, firewall rule to remove.

        """
        if rule in self._firewall_rules:
            self.host.run('%s -D %s' % (self._command_iptables, rule))
            self._firewall_rules.remove(rule)


    def firewall_cleanup(self):
        """Cleans up firewall rules."""
        for rule in self._firewall_rules:
            self._firewall_close(rule)


    def start_capture(self):
        """Start a packet capture.

        Attempt to start a host based OTA capture.  If the driver stack does
        not support creating monitor interfaces, fall back to managed interface
        packet capture.  Only one ongoing packet capture is supported at a time.

        """
        self.stop_capture()
        devname = self._packet_capturer.create_managed_monitor(self.wifi_if)
        if devname is None:
            logging.warning('Failure creating monitor interface; doing '
                            'managed packet capture instead.')
            devname = self.wifi_if
        self._packet_capturer.start_capture(devname, self._result_dir)


    def stop_capture(self):
        """Stop a packet capture and copy over the results."""
        self._packet_capturer.stop()
        self._packet_capturer.destroy_netdump_devices()


    def check_iw_link_value(self, iw_link_key, desired_value):
        """Assert that the current wireless link property is |desired_value|.

        @param iw_link_key string one of IW_LINK_KEY_* defined above.
        @param desired_value string desired value of iw link property.

        """
        result = self.host.run('%s dev %s link' % (self.command_iw,
                                                   self.wifi_if))
        find_re = re.compile('\s*%s:\s*(.*\S)\s*$' % iw_link_key)
        find_results = filter(bool, map(find_re.match,
                                        result.stdout.splitlines()))
        if not find_results:
            raise error.TestFail('Could not find iw link property %s.' %
                                 key)

        actual_value = find_results[0].group(1)
        desired_value = str(desired_value)
        if actual_value != str(desired_value):
            raise error.TestFail('Wanted iw link property %s value %s, but '
                                 'got %s instead.' % (iw_link_key,
                                                      desired_value,
                                                      actual_value))

        logging.info('Found iw link key %s with value %s.',
                     iw_link_key, actual_value)


    def powersave_switch(self, turn_on):
        """Toggle powersave mode for the DUT.

        @param turn_on bool True iff powersave mode should be turned on.

        """
        mode = 'off'
        if turn_on:
            mode = 'on'
        self.host.run('iw dev %s set power_save %s' % (self.wifi_if, mode))
