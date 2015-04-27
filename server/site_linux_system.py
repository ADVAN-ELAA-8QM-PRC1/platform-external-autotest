# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime
import collections
import logging
import os
import time

from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros import path_utils
from autotest_lib.client.common_lib.cros import virtual_ethernet_pair
from autotest_lib.client.common_lib.cros.network import iw_runner
from autotest_lib.client.common_lib.cros.network import ping_runner
from autotest_lib.server.cros.network import packet_capturer

NetDev = collections.namedtuple('NetDev',
                                ['inherited', 'phy', 'if_name', 'if_type'])

class LinuxSystem(object):
    """Superclass for test machines running Linux.

    Provides a common point for routines that use the cfg80211 userspace tools
    to manipulate the wireless stack, regardless of the role they play.
    Currently the commands shared are the init, which queries for wireless
    devices, along with start_capture and stop_capture.  More commands may
    migrate from site_linux_router as appropriate to share.

    """

    CAPABILITY_5GHZ = '5ghz'
    CAPABILITY_MULTI_AP = 'multi_ap'
    CAPABILITY_MULTI_AP_SAME_BAND = 'multi_ap_same_band'
    CAPABILITY_IBSS = 'ibss_supported'
    CAPABILITY_SEND_MANAGEMENT_FRAME = 'send_management_frame'
    CAPABILITY_TDLS = 'tdls'
    CAPABILITY_VHT = 'vht'
    BRIDGE_INTERFACE_NAME = 'br0'


    @property
    def capabilities(self):
        """@return iterable object of AP capabilities for this system."""
        if self._capabilities is None:
            self._capabilities = self.get_capabilities()
            logging.info('%s system capabilities: %r',
                         self.role, self._capabilities)
        return self._capabilities


    @property
    def board(self):
        """@return string self reported board of this device."""
        if self._board is None:
            # Remove 'board:' prefix.
            self._board = self.host.get_board().split(':')[1]
        return self._board


    def __init__(self, host, role, inherit_interfaces=False):
        # Command locations.
        cmd_iw = path_utils.must_be_installed('/usr/sbin/iw', host=host)
        self.cmd_ip = path_utils.must_be_installed('/usr/sbin/ip', host=host)
        self.cmd_readlink = '%s -l' % path_utils.must_be_installed(
                '/bin/ls', host=host)

        self.host = host
        self.role = role

        self._packet_capturer = packet_capturer.get_packet_capturer(
                self.host, host_description=role, cmd_ip=self.cmd_ip,
                cmd_iw=cmd_iw, ignore_failures=True)
        self.iw_runner = iw_runner.IwRunner(remote_host=host, command_iw=cmd_iw)

        self._phy_list = None
        self.phys_for_frequency, self.phy_bus_type = self._get_phy_info()
        self._interfaces = []
        for interface in self.iw_runner.list_interfaces():
            if inherit_interfaces:
                self._interfaces.append(NetDev(inherited=True,
                                               if_name=interface.if_name,
                                               if_type=interface.if_type,
                                               phy=interface.phy))
            else:
                self.iw_runner.remove_interface(interface.if_name)

        self._wlanifs_in_use = []
        self._capture_interface = None
        self._board = None
        # Some uses of LinuxSystem don't use the interface allocation facility.
        # Don't force us to remove all the existing interfaces if this facility
        # is not desired.
        self._wlanifs_initialized = False
        self._capabilities = None
        self._ping_runner = ping_runner.PingRunner(host=self.host)
        self._bridge_interface = None
        self._virtual_ethernet_pair = None


    @property
    def phy_list(self):
        """@return iterable object of PHY descriptions for this system."""
        if self._phy_list is None:
            self._phy_list = self.iw_runner.list_phys()
        return self._phy_list


    def _get_phy_info(self):
        """Get information about WiFi devices.

        Parse the output of 'iw list' and some of sysfs and return:

        A dict |phys_for_frequency| which maps from each frequency to a
        list of phys that support that channel.

        A dict |phy_bus_type| which maps from each phy to the bus type for
        each phy.

        @return phys_for_frequency, phy_bus_type tuple as described.

        """
        phys_for_frequency = {}
        phy_caps = {}
        phy_list = []
        for phy in self.phy_list:
            phy_list.append(phy.name)
            for band in phy.bands:
                for mhz in band.frequencies:
                    if mhz not in phys_for_frequency:
                        phys_for_frequency[mhz] = [phy.name]
                    else:
                        phys_for_frequency[mhz].append(phy.name)

        phy_bus_type = {}
        for phy in phy_list:
            phybus = 'unknown'
            command = '%s /sys/class/ieee80211/%s' % (self.cmd_readlink, phy)
            devpath = self.host.run(command).stdout
            if '/usb' in devpath:
                phybus = 'usb'
            elif '/mmc' in devpath:
                phybus = 'sdio'
            elif '/pci' in devpath:
                phybus = 'pci'
            phy_bus_type[phy] = phybus
        logging.debug('Got phys for frequency: %r', phys_for_frequency)
        return phys_for_frequency, phy_bus_type


    def _create_bridge_interface(self):
        """Create a bridge interface."""
        self.host.run('%s link add name %s type bridge' %
                      (self.cmd_ip, self.BRIDGE_INTERFACE_NAME))
        self.host.run('%s link set dev %s up' %
                      (self.cmd_ip, self.BRIDGE_INTERFACE_NAME))
        self._bridge_interface = self.BRIDGE_INTERFACE_NAME


    def _create_virtual_ethernet_pair(self):
        """Create a virtual ethernet pair."""
        self._virtual_ethernet_pair = virtual_ethernet_pair.VirtualEthernetPair(
                interface_ip=None, peer_interface_ip=None, host=self.host)
        self._virtual_ethernet_pair.setup()


    def remove_interface(self, interface):
        """Remove an interface from a WiFi device.

        @param interface string interface to remove (e.g. wlan0).

        """
        self.release_interface(interface)
        self.host.run('%s link set %s down' % (self.cmd_ip, interface))
        self.iw_runner.remove_interface(interface)
        for net_dev in self._interfaces:
            if net_dev.if_name == interface:
                self._interfaces.remove(net_dev)
                break


    def close(self):
        """Close global resources held by this system."""
        logging.debug('Cleaning up host object for %s', self.role)
        self._packet_capturer.close()
        # Release and remove any interfaces that we create.
        for net_dev in self._wlanifs_in_use:
            self.release_interface(net_dev.if_name)
        for net_dev in self._interfaces:
            if net_dev.inherited:
                continue
            self.remove_interface(net_dev.if_name)
        if self._bridge_interface is not None:
            self.remove_bridge_interface()
        if self._virtual_ethernet_pair is not None:
            self.remove_ethernet_pair_interface()
        self.host.close()
        self.host = None


    def get_capabilities(self):
        caps = set()
        phymap = self.phys_for_frequency
        if [freq for freq in phymap.iterkeys() if freq > 5000]:
            # The frequencies are expressed in megaherz
            caps.add(self.CAPABILITY_5GHZ)
        if [freq for freq in phymap.iterkeys() if len(phymap[freq]) > 1]:
            caps.add(self.CAPABILITY_MULTI_AP_SAME_BAND)
            caps.add(self.CAPABILITY_MULTI_AP)
        elif len(self.phy_bus_type) > 1:
            caps.add(self.CAPABILITY_MULTI_AP)
        for phy in self.phy_list:
            if 'tdls_mgmt' in phy.commands or 'tdls_oper' in phy.commands:
                caps.add(self.CAPABILITY_TDLS)
            if phy.support_vht:
                caps.add(self.CAPABILITY_VHT)
        return caps


    def start_capture(self, frequency,
                      ht_type=None, snaplen=None, filename=None):
        """Start a packet capture.

        @param frequency int frequency of channel to capture on.
        @param ht_type string one of (None, 'HT20', 'HT40+', 'HT40-').
        @param snaplen int number of bytes to retain per capture frame.
        @param filename string filename to write capture to.

        """
        if self._packet_capturer.capture_running:
            self.stop_capture()
        self._capture_interface = self.get_wlanif(frequency, 'monitor')
        full_interface = [net_dev for net_dev in self._interfaces
                          if net_dev.if_name == self._capture_interface][0]
        # If this is the only interface on this phy, we ought to configure
        # the phy with a channel and ht_type.  Otherwise, inherit the settings
        # of the phy as they stand.
        if len([net_dev for net_dev in self._interfaces
                if net_dev.phy == full_interface.phy]) == 1:
            self._packet_capturer.configure_raw_monitor(
                    self._capture_interface, frequency, ht_type=ht_type)
        else:
            self.host.run('%s link set %s up' %
                          (self.cmd_ip, self._capture_interface))

        # Start the capture.
        if filename:
            remote_path = os.path.join('/tmp', os.path.basename(filename))
        else:
            remote_path = None
        self._packet_capturer.start_capture(
            self._capture_interface, './debug/', snaplen=snaplen,
            remote_file=remote_path)


    def stop_capture(self, save_dir=None, save_filename=None):
        """Stop a packet capture.

        @param save_dir string path to directory to save pcap files in.
        @param save_filename string basename of file to save pcap in locally.

        """
        if not self._packet_capturer.capture_running:
            return
        results = self._packet_capturer.stop_capture(
                local_save_dir=save_dir, local_pcap_filename=save_filename)
        self.release_interface(self._capture_interface)
        self._capture_interface = None
        return results


    def sync_host_times(self):
        """Set time on our DUT to match local time."""
        epoch_seconds = time.time()
        busybox_format = '%Y%m%d%H%M.%S'
        busybox_date = datetime.datetime.utcnow().strftime(busybox_format)
        self.host.run('date -u --set=@%s 2>/dev/null || date -u %s' %
                      (epoch_seconds, busybox_date))


    def _get_phy_for_frequency(self, frequency, phytype):
        """Get a phy appropriate for a frequency and phytype.

        Return the most appropriate phy interface for operating on the
        frequency |frequency| in the role indicated by |phytype|.  Prefer idle
        phys to busy phys if any exist.  Secondarily, show affinity for phys
        that use the bus type associated with this phy type.

        @param frequency int WiFi frequency of phy.
        @param phytype string key of phytype registered at construction time.
        @return string name of phy to use.

        """
        phys = self.phys_for_frequency[frequency]

        busy_phys = set(net_dev.phy for net_dev in self._wlanifs_in_use)
        idle_phys = [phy for phy in phys if phy not in busy_phys]
        phys = idle_phys or phys

        preferred_bus = {'monitor': 'usb', 'managed': 'pci'}.get(phytype)
        preferred_phys = [phy for phy in phys
                          if self.phy_bus_type[phy] == preferred_bus]
        phys = preferred_phys or phys

        return phys[0]


    def get_wlanif(self, frequency, phytype, same_phy_as=None):
        """Get a WiFi device that supports the given frequency and type.

        @param frequency int WiFi frequency to support.
        @param phytype string type of phy (e.g. 'monitor').
        @param same_phy_as string create the interface on the same phy as this.
        @return string WiFi device.

        """
        if same_phy_as:
            for net_dev in self._interfaces:
                if net_dev.if_name == same_phy_as:
                    phy = net_dev.phy
                    break
            else:
                raise error.TestFail('Unable to find phy for interface %s' %
                                     same_phy_as)
        elif frequency in self.phys_for_frequency:
            phy = self._get_phy_for_frequency(frequency, phytype)
        else:
            raise error.TestFail('Unable to find phy for frequency %d' %
                                 frequency)

        # If we have a suitable unused interface sitting around on this
        # phy, reuse it.
        for net_dev in set(self._interfaces) - set(self._wlanifs_in_use):
            if net_dev.phy == phy and net_dev.if_type == phytype:
                self._wlanifs_in_use.append(net_dev)
                return net_dev.if_name

        # Because we can reuse interfaces, we have to iteratively find a good
        # interface name.
        name_exists = lambda name: bool([net_dev
                                         for net_dev in self._interfaces
                                         if net_dev.if_name == name])
        if_name = lambda index: '%s%d' % (phytype, index)
        if_index = len(self._interfaces)
        while name_exists(if_name(if_index)):
            if_index += 1
        net_dev = NetDev(phy=phy, if_name=if_name(if_index), if_type=phytype,
                         inherited=False)
        self._interfaces.append(net_dev)
        self._wlanifs_in_use.append(net_dev)
        self.iw_runner.add_interface(phy, net_dev.if_name, phytype)
        return net_dev.if_name


    def release_interface(self, wlanif):
        """Release a device allocated throuhg get_wlanif().

        @param wlanif string name of device to release.

        """
        for net_dev in self._wlanifs_in_use:
            if net_dev.if_name == wlanif:
                 self._wlanifs_in_use.remove(net_dev)


    def get_bridge_interface(self):
        """Return the bridge interface, create one if it is not created yet.

        @return string name of bridge interface.
        """
        if self._bridge_interface is None:
            self._create_bridge_interface()
        return self._bridge_interface


    def remove_bridge_interface(self):
        """Remove the bridge interface that's been created."""
        if self._bridge_interface is not None:
            self.host.run('%s link delete %s type bridge' %
                          (self.cmd_ip, self._bridge_interface))
        self._bridge_interface = None


    def add_interface_to_bridge(self, interface):
        """Add an interface to the bridge interface.

        This will create the bridge interface if it is not created yet.

        @param interface string name of the interface to add to the bridge.
        """
        if self._bridge_interface is None:
            self._create_bridge_interface()
        self.host.run('%s link set dev %s master %s' %
                      (self.cmd_ip, interface, self._bridge_interface))


    def get_virtual_ethernet_master_interface(self):
        """Return the master interface of the virtual ethernet pair.

        @return string name of the master interface of the virtual ethernet
                pair.
        """
        if self._virtual_ethernet_pair is None:
            self._create_virtual_ethernet_pair()
        return self._virtual_ethernet_pair.interface_name


    def get_virtual_ethernet_peer_interface(self):
        """Return the peer interface of the virtual ethernet pair.

        @return string name of the peer interface of the virtual ethernet pair.
        """
        if self._virtual_ethernet_pair is None:
            self._create_virtual_ethernet_pair()
        return self._virtual_ethernet_pair.peer_interface_name


    def remove_ethernet_pair_interface(self):
        """Remove the virtual ethernet pair that's been created."""
        if self._virtual_ethernet_pair is not None:
            self._virtual_ethernet_pair.teardown()
        self._virtual_ethernet_pair = None


    def require_capabilities(self, requirements, fatal_failure=False):
        """Require capabilities of this LinuxSystem.

        Check that capabilities in |requirements| exist on this system.
        Raise and exception to skip but not fail the test if said
        capabilities are not found.  Pass |fatal_failure| to cause this
        error to become a test failure.

        @param requirements list of CAPABILITY_* defined above.
        @param fatal_failure bool True iff failures should be fatal.

        """
        to_be_raised = error.TestNAError
        if fatal_failure:
            to_be_raised = error.TestFail
        missing = [cap for cap in requirements if not cap in self.capabilities]
        if missing:
            raise to_be_raised('AP on %s is missing required capabilites: %r' %
                               (self.role, missing))


    def set_antenna_bitmap(self, tx_bitmap, rx_bitmap):
        """Setup antenna bitmaps for all the phys.

        @param tx_bitmap int bitmap of allowed antennas to use for TX
        @param rx_bitmap int bitmap of allowed antennas to use for RX

        """
        for phy in self.phy_list:
            if not phy.supports_setting_antenna_mask:
                continue
            self.iw_runner.set_antenna_bitmap(phy.name, tx_bitmap, rx_bitmap)


    def set_default_antenna_bitmap(self):
        """Setup default antenna bitmaps for all the phys."""
        for phy in self.phy_list:
            if not phy.supports_setting_antenna_mask:
                continue
            self.iw_runner.set_antenna_bitmap(phy.name, phy.avail_tx_antennas,
                                              phy.avail_rx_antennas)


    def ping(self, ping_config):
        """Ping an IP from this system.

        @param ping_config PingConfig object describing the ping command to run.
        @return a PingResult object.

        """
        logging.info('Pinging from the %s.', self.role)
        return self._ping_runner.ping(ping_config)
