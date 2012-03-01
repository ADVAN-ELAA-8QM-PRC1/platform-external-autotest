# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging, time

from autotest_lib.client.bin import test
from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros import backchannel
from autotest_lib.client.cros.cellular import cell_tools
from autotest_lib.client.cros import network

from autotest_lib.client.cros import flimflam_test_path
import flimflam

class network_Portal(test.test):
    version = 1

    def GetConnectedService(self, service_name):
        service = self.flim.FindElementByNameSubstring('Service',
                                                       service_name)
        if service:
            properties = service.GetProperties(utf8_strings=True)
            state = properties['State']

            if state in ('online', 'portal', 'ready'):
                self.service = service
                return True

        return False

    def TestConnect(self, service_name, expected_state, timeout_seconds=30):
        """Connect to a service and verifies the portal state

        Args:
          service_name: substring to match against services
          expected_state: expected state of service after connecting

        Returns:
          True if the service is in the expected state
          False otherwise

        Raises:
          error.TestFail on non-recoverable failure
        """
        logging.info('TestConnect(%s, %s)' % (service_name, expected_state))

        self.service.Disconnect()
        state = self.flim.WaitForServiceState(
            service=self.service,
            expected_states=['idle', 'failure'],
            timeout=5)[0]

        self.service.Connect()
        state = self.flim.WaitForServiceState(
            service=self.service,
            expected_states=['portal', 'online', 'failure'],
            timeout=timeout_seconds)[0]

        if state != expected_state:
            logging.error('Service state should be %s but is %s' %
                          (expected_state, state))
            return False

        return True


    def run_once(self, force_failure, test_iterations=10, service_name='wifi'):
        """Run a test of the portal code.

        Args:
          force_failure: keyed values for different flavors of tests
              'portal' - blackhole the hosts used for http ensure that
                         the connection manager detects a portal.
              'dns'    - blackhole the DNS servers and ensure that
                         the connection manager detects a portal.
               False   - Do not force any failes and ensure that the
                         connection manager detects the service is online.
              'partial-dns'
                       - blackhole the first DNS server and ensure that the
                         connection manager detects the service is online.
        """
        errors = 0
        if force_failure == 'portal':
            # depends on getting a consistent IP address from DNS
            # depends on portal detection using www.google.com or
            # clients3.google.com
            hosts = [('clients3.google.com', 'OUTPUT'),
                     ('www.google.com', 'OUTPUT')]
            expected_state = 'portal'
        else:
            hosts = []
            expected_state = 'online'

        with backchannel.Backchannel():
            # Immediately after the backchannel is setup there may be no
            # services.  Try for up to 20 seconds to find one.
            # Getting to the ready state on an encrypted network can
            # be slow.
            self.flim = flimflam.FlimFlam()
            utils.poll_for_condition(
                lambda: self.GetConnectedService(service_name),
                error.TestFail(
                    'No service named "%s" available' % service_name),
                timeout=20)

            nameservers = []
            if force_failure == 'dns':
                nameservers = network.NameServersForService(self.flim,
                                                            self.service)
                expected_state = 'portal'
            elif force_failure == 'partial-dns':
                nameservers = network.NameServersForService(self.flim,
                                                            self.service)
                nameservers = nameservers[0:1]

            hosts += [(host, 'INPUT') for host in nameservers]

            with cell_tools.BlackholeContext(hosts):
                for _ in range(test_iterations):
                    if not self.TestConnect(service_name, expected_state):
                        errors += 1

                if errors:
                    raise error.TestFail('%d failures to enter state %s ' % (
                        errors, expected_state))

            #
            # Test the portal retry timer which should transition the
            # service to online (at most) 1 minute after the portal
            # restriction is removed.
            #
            if expected_state == 'portal':
                with cell_tools.BlackholeContext(hosts):
                    if not self.TestConnect(service_name, 'portal'):
                        raise error.TestFail('Failed to enter state portal')

                state = self.flim.WaitForServiceState(
                    service=self.service,
                    expected_states=['online'],
                    timeout=60)[0]

                if state != 'online':
                    raise error.TestFail('Failed to enter state online')
