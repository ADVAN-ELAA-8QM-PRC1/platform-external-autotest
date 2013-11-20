# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging

from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros.network import ping_runner
from autotest_lib.client.common_lib.cros.network import tcpdump_analyzer
from autotest_lib.client.common_lib.cros.network import xmlrpc_datatypes
from autotest_lib.server import site_linux_system
from autotest_lib.server.cros.network import hostap_config
from autotest_lib.server.cros.network import wifi_cell_test_base


class network_WiFi_TDLSPing(wifi_cell_test_base.WiFiCellTestBase):
    """Tests that the DUT can establish a TDLS link to a connected peer.

    This test associates the DUT with an AP, then attaches a peer
    client to the same AP.  After enabling a TDLS link from the DUT
    to the attached peer, we should see in the over-the-air packets
    that a ping between these devices does not use the AP as a relay
    any more.

    """

    version = 1

    def ping_and_check_for_tdls(self, frequency, expected):
        """
        Use an over-the-air packet capture to check whether we see
        ICMP packets from the DUT that indicate it is using a TDLS
        link to transmit its requests.  Raise an exception if this
        was not what was |expected|.

        @param frequency: int frequency on which to perform the packet capture.
        @param expected: bool set to true if we expect the sender to use TDLS.

        """
        self.context.router.start_capture(frequency)

        # Since we don't wait for the TDLS link to come up, it's possible
        # that we'll have some fairly drastic packet loss as the link is
        # being established.  We don't care about that in this test, except
        # that we should see at least a few packets by the end of the ping
        # we can use to test for TDLS.  Therefore we ignore the statistical
        # result of the ping.
        ping_config = ping_runner.PingConfig(
                self.context.router.local_peer_ip_address(0),
                ignore_result=True)
        self.context.assert_ping_from_dut(ping_config=ping_config)

        results = self.context.router.stop_capture()
        if len(results) != 1:
            raise error.TestError('Expected to generate one packet '
                                  'capture but got %d captures instead.' %
                                  len(results))
        pcap_result = results[0]

        logging.info('Analyzing packet capture...')

        # Filter for packets from the DUT.
        client_mac_filter = 'ether src host %s' % self.context.client.wifi_mac

        # In this test we only care that the outgoing ICMP requests are
        # sent over IBSS, so we filter for ICMP echo requests explicitly.
        icmp_filter = 'icmp[icmptype] = icmp-echo'

        # This filter requires a little explaining.  The "link[1]" identifier
        # tells tcpdump to provide the second byte of the link header, which
        # in the case of a received 802.11 frame is the second byte of the
        # frame control field.  This field contains the "tods" and "fromds"
        # bits in bit 0 and 1 respsectively.  These bits have the following
        # interpretation:
        #
        #   ToDS  FromDS
        #     0     0      Ad-Hoc (IBSS)
        #     0     1      Traffic from client to the AP
        #     1     0      Traffic from AP to the client
        #     1     1      4-address mode for wireless distribution system
        #
        # TDLS co-opts the ToDS=0, FromDS=0 (IBSS) mode when transferring
        # data directly between peers.  Therefore, to detect TDLS, we mask
        # the ToDS and FromDS bits out of the second byte of the frame control
        # and compare it with 0.
        tdls_filter = 'link[1] & 0x3 == 0'

        dut_icmp_pcap_filter = ' and '.join(
                [client_mac_filter, icmp_filter, tdls_filter])
        frames = tcpdump_analyzer.get_frames(
                pcap_result.pcap_path,
                remote_host=self.context.router.host,
                pcap_filter=dut_icmp_pcap_filter)
        if expected and not frames:
            raise error.TestFail('Packet capture did not contain a IBSS '
                                 'frames from the DUT!')
        elif not expected and frames:
            raise error.TestFail('Packet capture contain a IBSS frames '
                                 'from the DUT, but we did not expect them!')


    def run_once(self):
        """Test body."""
        client_caps = self.context.client.capabilities
        if site_linux_system.LinuxSystem.CAPABILITY_TDLS not in client_caps:
            raise error.TestNAError('DUT is incapable of TDLS')

        # Configure the AP.
        frequency = 2412
        self.context.configure(hostap_config.HostapConfig(frequency=frequency))
        router_ssid = self.context.router.get_ssid()

        # Connect the DUT to the AP.
        self.context.assert_connect_wifi(
                xmlrpc_datatypes.AssociationParameters(ssid=router_ssid))

        # Connect a client instance to the AP so the DUT has a peer to which
        # it can send TDLS traffic.
        self.context.router.add_connected_peer()

        # Manually add an ARP entry for the peer device in the DUT.
        # Because the AP is the same machine as the peer, it will
        # reply to ARP requests for the peer with the AP MAC address,
        # which is not what we want the DUT to use.
        peer_ip = self.context.router.local_peer_ip_address(0)
        peer_mac = self.context.router.local_peer_mac_address()
        self.context.client.add_arp_entry(peer_ip, peer_mac)

        # Ping from DUT to the associated peer without TDLS.
        self.ping_and_check_for_tdls(frequency, expected=False)

        # Ping from DUT to the associated peer with TDLS.
        self.context.client.establish_tdls_link(peer_mac)
        self.ping_and_check_for_tdls(frequency, expected=True)

        # Ensure that the DUT reports the TDLS link as being active.
        link_state = self.context.client.query_tdls_link(peer_mac)
        if (link_state != 'Connected'):
            raise error.TestError(
                    'DUT does not report TDLS link is active: %r' % link_state)
