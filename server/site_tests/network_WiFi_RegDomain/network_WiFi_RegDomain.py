# Copyright (c) 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
import subprocess
import tempfile

from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros.network import iw_runner
from autotest_lib.client.common_lib.cros.network import xmlrpc_datatypes
from autotest_lib.server import test
from autotest_lib.server.cros.network import hostap_config
from autotest_lib.server.cros.network import wifi_test_context_manager


class network_WiFi_RegDomain(test.test):
    """Verifies that a DUT connects, or fails to connect, on particular
    channels, in particular regions, per expectations."""
    version = 1


    DEBUG_DIR = 'debug'
    MISSING_SSID = "MissingSsid"
    # TODO(quiche): Shrink or remove the repeat count, once we've
    # figured out why tcpdump sometimes misses data. crbug.com/477536
    PASSIVE_SCAN_REPEAT_COUNT = 30
    REBOOT_TIMEOUT_SECS = 60
    # TODO(quiche): Migrate to the shiny new pyshark code from rpius.
    TSHARK_COMMAND = 'tshark'
    TSHARK_DISABLE_NAME_RESOLUTION = '-n'
    TSHARK_READ_FILE = '-r'
    TSHARK_SRC_FILTER = 'wlan.sa == %s'
    VPD_CACHE_FILE = \
        '/mnt/stateful_partition/unencrypted/cache/vpd/full-v2.txt'
    VPD_CLEAN_COMMAND ='dump_vpd_log --clean'


    @staticmethod
    def assert_equal(description, actual, expected):
        """Verifies that |actual| equals |expected|.

        @param description A string describing the data being checked.
        @param actual The actual value encountered by the test.
        @param expected The value we expected to encounter.
        @raise error.TestFail If actual != expected.

        """
        if actual != expected:
            raise error.TestFail(
                'Expected %s |%s|, but got |%s|.' %
                (description, expected, actual))


    @staticmethod
    def phy_list_to_channel_expectations(phy_list):
        """Maps phy information to expected scanning/connection behavior.

        Converts phy information from iw_runner.IwRunner.list_phys()
        into a map from channel numbers to expected connection
        behavior. This mapping is useful for comparison with the
        expectations programmed into the control file.

        @param phy_list The return value of iw_runner.IwRunner.list_phys()
        @return A dict from channel numbers to expected behaviors.

        """
        channel_to_expectation = {}
        for phy in phy_list:
            for band in phy.bands:
                for frequency, flags in band.frequency_flags.iteritems():
                    channel = (
                        hostap_config.HostapConfig.get_channel_for_frequency(
                            frequency))
                    # While we don't expect a channel to have both
                    # CHAN_FLAG_DISABLED, and (CHAN_FLAG_PASSIVE_SCAN
                    # or CHAN_FLAG_NO_IR), we still test the most
                    # restrictive flag first.
                    if iw_runner.CHAN_FLAG_DISABLED in flags:
                        channel_to_expectation[channel] = 'no-connect'
                    elif (iw_runner.CHAN_FLAG_PASSIVE_SCAN in flags or
                        iw_runner.CHAN_FLAG_NO_IR in flags):
                        channel_to_expectation[channel] = 'passive-scan'
                    else:
                        channel_to_expectation[channel] = 'connect'
        return channel_to_expectation


    @classmethod
    def assert_dut_has_expected_phy_config(
            cls, dut_host, expected_channel_configs):
        """Verifies that phys on the DUT place the expected restrictions on
        channels.

        Compares the restrictions reported by the running system to the
        restrictions in |expected_channel_configs|. Fails the test if
        the restrictions do not match.

        Note that this method deliberately ignores channels that are
        reported by the running system, but not mentioned in
        |expected_channel_configs|. This allows us to program the
        control file with "spot checks", rather than an exhaustive
        list of channels.

        @param dut_host The host object for the DUT.
        @param expected_channel_configs A channel_infos list.
        @raise error.TestFail If actual restrictions do not match expectations.

        """
        actual_channel_expectations = cls.phy_list_to_channel_expectations(
            iw_runner.IwRunner(dut_host).list_phys())
        for expected_config in expected_channel_configs:
            cls.assert_equal(
                'phy config for channel %d' % expected_config['chnum'],
                actual_channel_expectations[expected_config['chnum']],
                expected_config['expect'])


    @classmethod
    def assert_scanning_is_passive(cls, client, router, scan_freq):
        """Initiates single-channel scans, and verifies no probes are sent.

        @param client The WiFiClient object for the DUT.
        @param router The LinuxCrosRouter object for the router.
        @param scan_freq The frequency (in MHz) on which to scan.
        """
        try:
            client.claim_wifi_if()  # Stop shill/supplicant scans.
            router.start_capture(
                scan_freq, filename='%d_scan.pcap' % scan_freq)
            for i in range(0, cls.PASSIVE_SCAN_REPEAT_COUNT):
                # We pass in an SSID here, to check that even hidden
                # SSIDs do not cause probe requests to be sent.
                client.scan(
                    [scan_freq], [cls.MISSING_SSID], require_match=False)
            pcap_src = router.stop_capture()[0].pcap_path
            pcap_dest = os.path.join(cls.DEBUG_DIR, os.path.basename(pcap_src))
            router.host.get_file(pcap_src, pcap_dest)
            dut_frames = subprocess.check_output(
                [cls.TSHARK_COMMAND,
                 cls.TSHARK_DISABLE_NAME_RESOLUTION,
                 cls.TSHARK_READ_FILE, pcap_dest,
                 cls.TSHARK_SRC_FILTER % client.wifi_mac])
            if len(dut_frames):
                raise error.TestFail('Saw unexpected frames from DUT.')
        finally:
            client.release_wifi_if()
            router.stop_capture()


    @classmethod
    def assert_scanning_fails(cls, client, scan_freq):
        """Initiates a single-channel scan, and verifies that it fails.

        @param client The WiFiClient object for the DUT.
        @param scan_freq The frequency (in MHz) on which to scan.
        """
        client.claim_wifi_if()  # Stop shill/supplicant scans.
        try:
            # We use IwRunner directly here, because WiFiClient.scan()
            # wants a scan to succeed, while we want the scan to fail.
            if iw_runner.IwRunner(client.host).timed_scan(
                client.wifi_if, [scan_freq], [cls.MISSING_SSID]):
                # We should have got None, to represent failure.
                raise error.TestFail(
                    'Scan succeeded (and was expected to fail).')
        finally:
            client.release_wifi_if()


    def fake_up_region(self, region):
        """Modifies VPD cache to force a particular region, and reboots system
        into to faked state.

        @param region: The region we want to force the host into.

        """
        self.host.run(self.VPD_CLEAN_COMMAND)
        temp_vpd = tempfile.NamedTemporaryFile()
        temp_vpd.write('"region"="%s"' % region)
        temp_vpd.flush()
        self.host.send_file(temp_vpd.name, self.VPD_CACHE_FILE)
        self.host.reboot(timeout=self.REBOOT_TIMEOUT_SECS, wait=True)


    def warmup(self, host, raw_cmdline_args, additional_params):
        """Stashes away parameters for use by run_once().

        @param host Host object representing the client DUT.
        @param raw_cmdline_args Raw input from autotest.
        @param additional_params One item from CONFIGS in control file.

        """
        self.host = host
        self.cmdline_args = utils.args_to_dict(raw_cmdline_args)
        self.channel_infos = additional_params['channel_infos']
        self.expected_country_code = additional_params['country_code']
        self.region_name = additional_params['region_name']


    def test_channel(self, wifi_context, channel_config):
        """Verifies that a DUT does/does not connect on a particular channel,
        per expectation.

        @param wifi_context: A WiFiTestContextManager.
        @param channel_config: A dict with 'chnum' and 'expect' keys.

        """
        router_freq = hostap_config.HostapConfig.get_frequency_for_channel(
            channel_config['chnum'])
        router_ssid = None

        # Test scanning behavior, as appropriate. To ensure that,
        # e.g., AP beacons don't affect the DUT's behavior, this is
        # done with no AP running.
        if channel_config['expect'] == 'passive-scan':
            self.assert_scanning_is_passive(
                wifi_context.client, wifi_context.router, router_freq)
        elif channel_config['expect'] == 'no-connect':
            self.assert_scanning_fails(wifi_context.client, router_freq)

        try:
            # Now, start the AP and test whether or not connection succeeds.
            wifi_context.router.start_capture(
                router_freq, filename='%d_connect.pcap' % router_freq)
            wifi_context.router.hostap_configure(
                hostap_config.HostapConfig(
                    frequency=router_freq,
                    mode=hostap_config.HostapConfig.MODE_11N_MIXED))
            router_ssid = wifi_context.router.get_ssid()
            client_conf = xmlrpc_datatypes.AssociationParameters(
                ssid = router_ssid,
                expect_failure = channel_config['expect'] not in (
                    'connect', 'passive-scan'))
            wifi_context.assert_connect_wifi(client_conf)
        finally:
            if router_ssid:
                wifi_context.client.shill.delete_entries_for_ssid(router_ssid)
            wifi_context.router.stop_capture()


    def run_once(self):
        """Configures a DUT to behave as if it was manufactured for a
        particular region. Then verifies that the DUT connects, or
        fails to connect, per expectations.

        """
        num_failures = 0
        try:
            self.fake_up_region(self.region_name)
            self.assert_equal(
              'country code',
              iw_runner.IwRunner(self.host).get_regulatory_domain(),
              self.expected_country_code)
            self.assert_dut_has_expected_phy_config(
                self.host, self.channel_infos)
            wifi_context = wifi_test_context_manager.WiFiTestContextManager(
                self.__class__.__name__,
                self.host,
                self.cmdline_args,
                self.debugdir)
            with wifi_context:
                wifi_context.router.host.reboot(
                    timeout=self.REBOOT_TIMEOUT_SECS, wait=True)
                for channel_config in self.channel_infos:
                    try:
                        self.test_channel(wifi_context, channel_config)
                    except error.TestFail as e:
                        # Log the error, but keep going. This way, we
                        # get a full report of channels where behavior
                        # differs from expectations.
                        logging.error('Verification failed for |%s|: %s',
                                      self.region_name, channel_config)
                        logging.error(e)
                        num_failures += 1
        finally:
            if num_failures:
                raise error.TestFail(
                    'Verification failed for %d channel configs (see below)' %
                    num_failures)
            self.host.run(self.VPD_CLEAN_COMMAND)
            self.host.reboot(timeout=self.REBOOT_TIMEOUT_SECS, wait=True)
