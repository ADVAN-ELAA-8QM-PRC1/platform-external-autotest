# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from autotest_lib.client.bin import test, utils
from autotest_lib.client.common_lib import error

import logging, re, socket, string, time, urllib2
import dbus, dbus.mainloop.glib, gobject

from autotest_lib.client.cros import flimflam_test_path
import flimflam, mm

class network_3GStressEnable(test.test):
    version = 1

    okerrors = [
        'org.chromium.flimflam.Error.InProgress'
    ]

    def SetPowered(self, state):
        try:
            self.device.SetProperty('Powered', dbus.Boolean(state))
        except dbus.exceptions.DBusException, err:
            if err._dbus_error_name in network_3GStressEnable.okerrors:
                return
            else:
                raise error.TestFail(err)

    def test(self, settle):
        self.SetPowered(1)
        time.sleep(settle)
        self.SetPowered(0)
        time.sleep(settle)

    def FindDevice(self, names):
        for name in names:
            self.device = self.flim.FindElementByNameSubstring('Device',
                                                               name)
            if self.device:
                return True
            self.device = self.flim.FindElementByPropertySubstring('Device',
                                                              'Interface',
                                                               name)
            if self.device:
                return True
        return False

    def run_once(self, names=['usb', 'wwan'], cycles=3, min=15, max=25):
        self.flim = flimflam.FlimFlam(dbus.SystemBus())
        if not self.FindDevice(names):
            raise error.TestFail('No device found.')
        service = self.flim.FindElementByNameSubstring('Service', 'cellular')
        if service:
            # If cellular's already up, take it down to start.
            try:
                service.SetProperty('AutoConnect', False)
            except dbus.exceptions.DBusException, err:
                # If the device has never connected to the cellular service
                # before, flimflam will raise InvalidService when attempting
                # to change the AutoConnect property.
                if err._dbus_error_name != 'org.chromium.flimflam.'\
                                             'Error.InvalidService':
                    raise err
            self.SetPowered(0)
        for t in xrange(max, min, -1):
            for n in xrange(cycles):
                # deciseconds are an awesome unit.
                print 'Cycle %d: %f seconds delay.' % (n, t / 10.0)
                self.test(t / 10.0)
        print 'Done.'
