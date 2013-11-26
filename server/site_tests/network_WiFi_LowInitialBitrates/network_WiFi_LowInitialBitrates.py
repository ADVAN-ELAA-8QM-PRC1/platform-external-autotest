# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging

from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros.network import tcpdump_analyzer
from autotest_lib.client.common_lib.cros.network import xmlrpc_datatypes
from autotest_lib.server.cros.network import hostap_config
from autotest_lib.server.cros.network import wifi_cell_test_base


class network_WiFi_LowInitialBitrates(wifi_cell_test_base.WiFiCellTestBase):
    """Test that we can connect to router configured in various ways."""
    version = 1


    def check_bitrates_in_capture(self, pcap_result):
        """
        Check that bitrates look like we expect in a packet capture.

        The DUT should not send packets at high bitrates until after DHCP
        negotiation is complete.  If this is detected, fail the test.

        @param pcap_result: RemoteCaptureResult tuple.

        """
        logging.info('Analyzing packet capture...')
        dut_src_pcap_filter = ('ether src host %s' %
                               self.context.client.wifi_mac)
        # Get all the frames in chronological order.
        frames = tcpdump_analyzer.get_frames(
                pcap_result.pcap_path,
                remote_host=self.context.router.host,
                pcap_filter=dut_src_pcap_filter)
        # Get just the DHCP related packets.
        dhcp_frames = tcpdump_analyzer.get_frames(
                pcap_result.pcap_path,
                remote_host=self.context.router.host,
                pcap_filter='%s and port bootps' % dut_src_pcap_filter)
        if not dhcp_frames:
            raise error.TestFail('Packet capture did not contain a DHCP '
                                 'negotiation!')

        for frame in frames:
            if frame.time_delta_seconds > dhcp_frames[-1].time_delta_seconds:
                # We're past the last DHCP packet, so higher bitrates are
                # permissable and expected.
                break

            if frame.mcs_index is not None:
                if frame.mcs_index > 1:
                    # wpa_supplicant should ask that all but the 2 lowest rates
                    # be disabled.
                    raise error.TestFail('Found packet sent with MCS index %d '
                                         'during association process.' %
                                         frame.mcs_index)
            elif frame.bit_rate >= 12:
                raise error.TestFail('Found packet sent with bitrate %f '
                                     'during association process.' %
                                     frame.bit_rate)


    def run_once(self):
        """Asserts that WiFi bitrates remain low during the association process.

        Low bitrates mean that data transfer is slow, but reliable.  This is
        important since association usually includes some very time dependent
        configuration state machines and no user expectation of high bandwidth.

        """
        caps = [hostap_config.HostapConfig.N_CAPABILITY_GREENFIELD,
                hostap_config.HostapConfig.N_CAPABILITY_HT40]
        g_config = hostap_config.HostapConfig(
                channel=6,
                mode=hostap_config.HostapConfig.MODE_11G)
        n_config = hostap_config.HostapConfig(
                channel=44,
                mode=hostap_config.HostapConfig.MODE_11N_PURE,
                n_capabilities=caps)
        for ap_config in (g_config, n_config):
            self.context.configure(ap_config)
            self.context.router.start_capture(
                    ap_config.frequency,
                    ht_type=ap_config.ht_packet_capture_mode)
            assoc_params = xmlrpc_datatypes.AssociationParameters(
                    ssid=self.context.router.get_ssid())
            self.context.assert_connect_wifi(assoc_params)
            self.context.assert_ping_from_dut()
            results = self.context.router.stop_capture()
            if len(results) != 1:
                raise error.TestError('Expected to generate one packet '
                                      'capture but got %d captures instead.' %
                                      len(results))

            client_ip = self.context.client.wifi_ip
            self.check_bitrates_in_capture(results[0])
            self.context.client.shill.disconnect(assoc_params.ssid)
            self.context.router.deconfig()
