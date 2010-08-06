# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from autotest_lib.client.bin import site_backchannel, test, utils
from autotest_lib.client.common_lib import error

import logging, os, re, socket, string, sys, time, urllib2
import dbus, dbus.mainloop.glib, gobject

# Workaround so flimflam.py can remain part of flimflam scripts
import_path = os.environ.get('SYSROOT', '') + '/usr/lib/flimflam/test'
sys.path.append(import_path)
import flimflam, routing, mm


SERVER = 'testing-chargen.appspot.com'
BASE_URL = 'http://' + SERVER + '/'


class network_3GSmokeTest(test.test):
    version = 1

    def FindCellularService(self):
        """Find the first dbus cellular service object."""

        service = self.flim.FindElementByPropertySubstring('Service',
                                                           'Type',
                                                           'cellular')
        if not service:
            raise error.TestFail('Could not find cellular service.')
        return service

    def ConnectTo3GNetwork(self, config_timeout):
        """Attempts to connect to a 3G network using FlimFlam.

        Args:
        config_timeout:  Timeout (in seconds) before giving up on connect

        Raises:
        error.TestFail if connection fails
        """
        logging.info('ConnectTo3GNetwork')
        service = self.FindCellularService()

        success, status = self.flim.ConnectService(
            service=service,
            config_timeout=config_timeout)
        if not success:
            raise error.TestFail('Could not connect: %s.' % status)

    def FetchUrl(self, url_pattern=
                 BASE_URL + 'download?size=%d',
                 size=10,
                 label=None):
        """Fetch the URL, write a dictionary of performance data.

        Args:
          url_pattern:  URL to download with %d to be filled in with # of
              bytes to download.
          size:  Number of bytes to download.
          label:  Label to add to performance keyval keys.
        """

        if not label:
            raise error.TestError('FetchUrl: no label supplied.')

        url = url_pattern % size
        start_time = time.time()
        result = urllib2.urlopen(url)
        bytes_received = len(result.read())
        fetch_time = time.time() - start_time
        if not fetch_time:
            raise error.TestError('FetchUrl took 0 time.')

        if bytes_received != size:
            raise error.TestError('FetchUrl:  for %d bytes, got %d.' %
                                  (size, bytes_received))

        self.write_perf_keyval(
            {'seconds_%s_fetch_time' % label: fetch_time,
             'bytes_%s_bytes_received' % label: bytes_received,
             'bits_second_%s_speed' % label: 8 * bytes_received / fetch_time}
            )

    def DisconnectFrom3GNetwork(self, disconnect_timeout):
        """Attempts to disconnect to a 3G network using FlimFlam.

        Args:
          disconnect_timeout: Wait this long for disconnect to take
              effect.  Raise if we time out.
        """
        logging.info('DisconnectFrom3GNetwork')
        service = self.FindCellularService()

        success, status = self.flim.DisconnectService(
            service=service,
            wait_timeout=disconnect_timeout)
        if not success:
            raise error.TestFail('Could not disconnect: %s.' % status)

    def ResetAllModems(self):
        """Disable/Enable cycle all modems to ensure valid starting state."""
        manager = mm.ModemManager()
        for path in manager.manager.EnumerateDevices():
            modem = manager.Modem(path)
            modem.Enable(False)
            modem.Enable(True)

    def GetModemInfo(self):
        """Find all modems attached and return an dictionary of information.

        This returns a bunch of information for each modem attached to
        the system.  In practice collecting all this information
        sometimes fails if a modem is left in an odd state, so we
        collect as many things as we can to ensure that the modem is
        responding correctly.

        Returns: dictionary of information for each modem path.
        """
        results = {}
        manager = mm.ModemManager()

        for path in manager.manager.EnumerateDevices():
            modem = manager.Modem(path)
            props = manager.Properties(path)
            info = {}

            try:
                info = dict(info=modem.GetInfo())
                modem_type = props['Type']
                if modem_type == mm.ModemManager.CDMA_MODEM:
                    cdma_modem = manager.CdmaModem(path)

                    info['esn'] = cdma_modem.GetEsn()
                    info['rs'] = cdma_modem.GetRegistrationState()
                    info['ss'] = cdma_modem.GetServingSystem()
                    info['quality'] = cdma_modem.GetSignalQuality()

                elif modem_type == mm.ModemManager.GSM_MODEM:
                    gsm_card = manager.GsmCard(path)
                    info['imsi'] = gsm_card.GetImsi()

                    gsm_network = manager.GsmNetwork(path)
                    info['ri'] = gsm_network.GetRegistrationInfo()
                else:
                    print 'Unknown modem type %s' % modem_type
                    continue

            except dbus.exceptions.DBusException, e:
                logging.info('Info: %s.', info)
                logging.error('MODEM_DBUS_FAILURE: %s: %s.', path, e)
                continue

            results[path] = info
        return results

    def CheckInterfaceForDestination(self, host, service):
        """Checks that routes for hosts go through the device for service.

        The concern here is that our network setup may have gone wrong
        and our test connections may go over some other network than
        the one we're trying to test.  So we take all the IP addresses
        for the supplied host and make sure they go through the
        network device attached to the supplied Flimflam service.

        Args:
          host:  Destination host
          service: Flimflam service object that should be used for
            connections to host
        """
        # addrinfo records: (family, type, proto, canonname, (addr, port))
        server_addresses = [record[4][0] for
                            record in socket.getaddrinfo(SERVER, 80)]

        device = self.flim.GetObjectInterface('Device',
                                              service.GetProperties()['Device'])
        expected = device.GetProperties()['Interface']
        logging.info('Device for %s: %s', service.object_path, expected)

        routes = routing.NetworkRoutes()
        for address in server_addresses:
          interface = routes.getRouteFor(address).interface
          logging.info('interface for %s: %s', address, interface)
          if interface!= expected:
            raise error.TestFail('Target server %s uses interface %s'
                                 '(%s expected).' %
                                 (address, interface, expected))

    def run_once_internal(self, connect_count, sleep_kludge):
        bus_loop = dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus(mainloop=bus_loop)

        if not site_backchannel.setup():
            raise error.TestError('Could not setup Backchannel network.')

        # Get to a good starting state
        self.ResetAllModems()
        self.DisconnectFrom3GNetwork(disconnect_timeout=60)

        # Get information about all the modems
        modem_info = self.GetModemInfo()
        logging.info('Info: %s' % ', '.join(modem_info))

        for ii in xrange(connect_count):
            self.ConnectTo3GNetwork(config_timeout=120)
            self.CheckInterfaceForDestination(SERVER,
                                              self.FindCellularService())

            self.FetchUrl(label='3G', size=1<<16)
            self.DisconnectFrom3GNetwork(disconnect_timeout=60)

            # Verify that we can still get information for all the modems
            logging.info('Info: %s' % ', '.join(modem_info))
            if len(self.GetModemInfo()) != len(modem_info):
                raise error.TestFail('Test shutdown: '
                                     'failed to leave modem in working state.')

            if sleep_kludge:
              logging.info('Sleeping for %.1f seconds', sleep_kludge)
              time.sleep(sleep_kludge)

    def run_once(self, connect_count=30, sleep_kludge=5):
        self.flim = flimflam.FlimFlam()
        self.device_manager = flimflam.DeviceManager(self.flim)
        try:
            self.device_manager.ShutdownAllExcept('cellular')
            self.run_once_internal(connect_count, sleep_kludge)
        finally:
            self.device_manager.RestoreDevices()
