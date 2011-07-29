# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import dbus
import logging
from random import randint
import time
import utils

from autotest_lib.client.bin import test
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros import rtc, sys_power

# Special import to define the location of the flimflam library.
from autotest_lib.client.cros import flimflam_test_path
import flimflam


class network_3GSuspendResume(test.test):
    version = 1

    okerrors = [
        # Setting of device power can sometimes result with InProgress error
        # if it is in the process of already doing so.
        'org.chromium.flimflam.Error.InProgress',
    ]

    scenarios = {
        'all': [
            'scenario_suspend_3g_enabled',
            'scenario_suspend_3g_disabled',
            'scenario_suspend_3g_disabled_twice',
            # TODO(jglasgow): enable when it stops making test abort
            # 'scenario_autoconnect',
        ],
        'stress': [
            'scenario_suspend_3g_random',
        ],
    }

    modem_status_outputs = [
        'org.chromium.ModemManager',
        'meid',
        'Manufacturer',
        'MasterDevice'
    ]

    # This function returns True when cellular service is available.  Otherwise,
    # if the timeout period has been hit, it returns false.
    def cellular_service_available(self, timeout=60):
        service = self.flim.FindCellularService(timeout)
        if service:
            logging.info('Cellular service is available.')
            return service
        logging.info('Cellular service is not available.')
        return None

    def connect_service(self, service):
        flim = flimflam.FlimFlam(dbus.SystemBus())
        (success, reason) = flim.ConnectService(service)
        if success:
            return True
        return False

    def get_powered(self, device):
        properties = device.GetProperties(utf8_strings=True)
        logging.debug(properties)
        logging.info('Power state of cellular device is %s.',
                     ['off', 'on'][properties['Powered']])
        return properties['Powered']

    def set_powered(self, device, state):
        try:
            device.SetProperty('Powered', dbus.Boolean(state))
        except dbus.exceptions.DBusException, e:
            if e._dbus_error_name not in network_3GSuspendResume.okerrors:
                raise e
        # Sometimes if we disable the modem then immediately enable the modem
        # we hit a condition where the modem seems to ignore the enable command
        # and keep the modem disabled.  This is to prevent that from happening.
        time.sleep(4)
        return self.get_powered(device) == state

    def suspend_resume(self, duration=10):
        alarm_time = rtc.get_seconds() + duration
        logging.info('Suspending machine for: %d.\n' % duration)
        rtc.set_wake_alarm(alarm_time)
        sys_power.request_suspend()
        # it is expected that the following sleep starts before the
        # suspend, because the request_suspend interface is NOT
        # synchronous.  This means the sleep should wake immediately
        # after resume.
        time.sleep(duration)
        logging.info('Machine resumed')

        # Race condition hack alert: Before we added this sleep, this
        # test was very sensitive to the relative timing of the test
        # and modem resumption.  There is a window where flimflam has
        # not yet learned that the old modem has gone away (it doesn't
        # find this out until seconds after we resume) and the test is
        # running.  If the test finds and attempts to use the old
        # modem, those operations will fail.  There's no good
        # hardware-independent way to see the modem go away and come
        # back, so instead we sleep
        time.sleep(4)

    # __get_cellular_device is a hack wrapper around the FindCellularDevice
    # that verifies that GetProperties can be called before proceeding.
    # There appears to be an issue after suspend/resume where GetProperties
    # returns with UnknownMethod called until some time later.
    def __get_cellular_device(self, timeout=30):
        start_time = time.time()
        device = self.flim.FindCellularDevice(timeout)

        properties = None
        timeout = start_time + timeout
        while properties is None and time.time() < timeout:
            try:
                properties = device.GetProperties(utf8_strings=True)
            except:
                properties = None

            time.sleep(1)
        if not device:
            raise error.TestError('Cellular device not found.')
        return device

    # The suspend_3g_enabled test suspends, then resumes the machine while
    # 3g is enabled.
    def scenario_suspend_3g_enabled(self):
        device = self.__get_cellular_device()
        self.set_powered(device, 1)
        if not self.cellular_service_available():
            raise error.TestError('Unable to find cellular service.')
        self.suspend_resume(20)

    # The suspend_3g_disabled test suspends, then resumes the machine while
    # 3g is disabled.
    def scenario_suspend_3g_disabled(self):
        device = self.__get_cellular_device()
        self.set_powered(device, 0)
        self.suspend_resume(20)

        # This verifies that the device is in the same state before and after
        # the device is suspended/resumed.
        device = self.__get_cellular_device()
        if self.get_powered(device) != 0:
            raise error.TestError('Device is not in same state it was prior'
                                  'to Suspend/Resume.')

        # Turn on the device to make sure we can bring it back up.
        self.set_powered(device, 1)

    # The suspend_3g_disabled_twice subroutine is here because
    # of bug 9405.  The test will suspend/resume the device twice
    # while 3g is disabled.  We will then verify that 3g can be enabled
    # thereafter.
    def scenario_suspend_3g_disabled_twice(self):
        device = self.__get_cellular_device()
        self.set_powered(device, 0)

        for _ in [0, 1]:
            self.suspend_resume(20)

            # This verifies that the device is in the same state before
            # and after the device is suspended/resumed.
            device = self.__get_cellular_device()
            if self.get_powered(device) != 0:
                raise error.TestError('Device is not in same state it was prior'
                                      'to Suspend/Resume.')

        # Turn on the device to make sure we can bring it back up.
        self.set_powered(device, 1)

    # This test randomly enables or disables the modem.  This
    # is mainly used for stress tests as it does not check the power state of
    # the modem before and after suspend/resume.
    def scenario_suspend_3g_random(self):
        device = self.__get_cellular_device()
        self.set_powered(device, randint(0,1))
        self.suspend_resume(randint(20, 40))
        device = self.__get_cellular_device()
        self.set_powered(device, 1)

    # This verifies that autoconnect works.
    def scenario_autoconnect(self):
        device = self.__get_cellular_device()
        self.set_powered(device, 1)
        service = self.flim.FindCellularService(30)
        if not service:
            raise error.TestError('Unable to find cellular service')

        props = service.GetProperties(utf8_strings=True)
        if props['AutoConnect']:
            expected_states = ['ready', 'online', 'portal']
        else:
            expected_states = ['idle']

        for _ in xrange(5):
            self.suspend_resume(10)

            # wait for the device to come back
            device = self.__get_cellular_device()

            # verify the service state is correct
            service = self.flim.FindCellularService(30)
            if not service:
                raise error.TestFail('Cannot find cellular service')

            state, _ = self.flim.WaitForServiceState(service,
                                                     expected_states, 30)
            if not state in expected_states:
                raise error.TestFail('Cellular state %s not in %s as expected'
                                     % (state, ', '.join(expected_states)))

    # Returns 1 if modem_status returned output within duration.
    # otherwise, returns 0
    def get_modem_status(self, duration=60):
        time_end = time.time() + duration
        timeout = 30
        while time.time() < time_end:
            status = utils.system_output('modem status', timeout=timeout)
            if reduce(lambda x, y: x & (y in status),
                      network_3GSuspendResume.modem_status_outputs,
                      True):
                break
        else:
            return 0
        return 1

    # This is the wrapper around the running of each scenario with
    # initialization steps and final checks.
    def run_scenario(self, function_name):
        device = self.__get_cellular_device()

        # Initialize all tests with the power off.
        self.set_powered(device, 0)

        function = getattr(self, function_name)
        logging.info('Running %s' % function_name)
        function()

        # By the end of each test, the cellular device should be up.
        # Here we verify that the power state of the device is up, and
        # that the cellular service can be found.
        device = self.__get_cellular_device()

        if not self.get_powered(device) == 1:
            raise error.TestFail('Failed to execute %s.  Modem '
                             'is not powered on after test.'% function_name)

        logging.info('Scenario complete: %s.' % function_name)

        if not self.get_modem_status():
            raise error.TestFail('Failed to get modem_status after %s.'
                              % function_name)
        service = self.cellular_service_available()
        if not service:
            raise error.TestFail('Could not find cellular service at the end '
                                 'of test %s.' % function_name)
        # if not self.connect_service(service):
        #     raise error.TestFail('Cellular service was not connectable at '
        #                          'the end of %s' % function_name)

    def run_once(self, scenario_group='all', autoconnect=False):
        # Replace the test type with the list of tests
        if scenario_group not in network_3GSuspendResume.scenarios.keys():
            scenario_group = 'all'
        logging.info('Running scenario group: %s' % scenario_group)
        scenarios = network_3GSuspendResume.scenarios[scenario_group]

        self.flim = flimflam.FlimFlam(dbus.SystemBus())
        device = self.__get_cellular_device()
        if not device:
            raise error.TestFail('Cannot find cellular device.')
        self.set_powered(device, 1)

        service = self.flim.FindCellularService(30)
        if not service:
            raise error.TestFail('Cannot find cellular service.')

        service.SetProperty('AutoConnect', dbus.Boolean(autoconnect))

        logging.info('Running scenarios with autoconnect %s.' % autoconnect)
        for t in scenarios:
            self.run_scenario(t)
