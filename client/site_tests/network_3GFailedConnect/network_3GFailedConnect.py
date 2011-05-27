# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from autotest_lib.client.bin import test, utils
from autotest_lib.client.cros import backchannel
from autotest_lib.client.common_lib import error

import logging, time
import dbus, dbus.mainloop.glib, gobject

from autotest_lib.client.cros import flimflam_test_path
import flimflam, mm


class network_3GFailedConnect(test.test):
    version = 1

    def ConnectTo3GNetwork(self, config_timeout):
        """Attempts to connect to a 3G network using FlimFlam.

        Args:
        config_timeout:  Timeout (in seconds) before giving up on connect

        Raises:
        error.TestFail if connection fails
        """
        logging.info('ConnectTo3GNetwork')
        service = self.flim.FindCellularService()
        if not service:
          raise error.TestFail('No cellular service available')

        try:
          service.Connect()
        except Exception, e:
          print e

        state = self.flim.WaitForServiceState(
            service=service,
            expected_states=["ready", "portal", "online", "failure"],
            timeout=config_timeout)[0]

        if state != "failure":
            raise error.TestFail('Service state should be failure not %s' %
                                 state)

    def ResetAllModems(self):
        """Disable/Enable cycle all modems to ensure valid starting state."""

        service = self.flim.FindCellularService()
        if not service:
          raise error.TestFail('No cellular service available')

        print 'ResetAllModems: service %s' % service
        if service.GetProperties()['Favorite']:
            service.SetProperty('AutoConnect', False)
        for manager, path in mm.EnumerateDevices():
            modem = manager.Modem(path)
            modem.Enable(False)
            modem.Enable(True)

    def run_once_internal(self, connect_count):
        bus_loop = dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus(mainloop=bus_loop)

        # Get to a good starting state
        self.ResetAllModems()

        for ii in xrange(connect_count):
            self.ConnectTo3GNetwork(config_timeout=15)

    def run_once(self, connect_count=4):
        backchannel.setup()
        self.flim = flimflam.FlimFlam()
        self.device_manager = flimflam.DeviceManager(self.flim)
        try:
            self.device_manager.ShutdownAllExcept('cellular')
            self.run_once_internal(connect_count)
        finally:
            try:
                self.device_manager.RestoreDevices()
            finally:
                backchannel.teardown()
