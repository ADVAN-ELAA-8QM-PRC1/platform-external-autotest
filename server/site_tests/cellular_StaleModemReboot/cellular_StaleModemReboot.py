# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import time

from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error
from autotest_lib.server import test

_MODEM_WAIT_DELAY = 120

NO_MODEM_STATE_AVAILABLE = 'FAILED TO GET MODEM STATE'

# TODO(harpreet / benchan): Modify the modem script to report modem health.
# crbug.com/352351
MM_MODEM_STATE_FAILED = '-1'
MM_MODEM_STATE_UNKNOWN = '0'
MM_MODEM_STATE_INITIALIZING = '1'
MM_MODEM_STATE_LOCKED = '2'
MM_MODEM_STATE_DISABLED = '3'
MM_MODEM_STATE_DISABLING = '4'
MM_MODEM_STATE_ENABLING = '5'
MM_MODEM_STATE_ENABLED = '6'
MM_MODEM_STATE_SEARCHING = '7'
MM_MODEM_STATE_REGISTERED = '8'
MM_MODEM_STATE_DISCONNECTING = '9'
MM_MODEM_STATE_CONNECTING = '10'
MM_MODEM_STATE_CONNECTED = '11'

GOBI_MODEM_STATE_UNKNOWN = '0'
GOBI_MODEM_STATE_DISABLING = '20'
GOBI_MODEM_STATE_ENABLING = '30'
GOBI_MODEM_STATE_ENABLED = '40'
GOBI_MODEM_STATE_SEARCHING = '50'
GOBI_MODEM_STATE_REGISTERED = '60'
GOBI_MODEM_STATE_DISCONNECTING = '70'
GOBI_MODEM_STATE_CONNECTING = '80'
GOBI_MODEM_STATE_CONNECTED = '90'

GOBI_MODEM_STATES = [
    GOBI_MODEM_STATE_DISABLING,
    GOBI_MODEM_STATE_ENABLING,
    GOBI_MODEM_STATE_ENABLED,
    GOBI_MODEM_STATE_SEARCHING,
    GOBI_MODEM_STATE_REGISTERED,
    GOBI_MODEM_STATE_DISCONNECTING,
    GOBI_MODEM_STATE_CONNECTING,
    GOBI_MODEM_STATE_CONNECTED
]

ENABLED_MODEM_STATES = [
    MM_MODEM_STATE_ENABLED,
    GOBI_MODEM_STATE_ENABLED
]

WAIT_DELAY_MODEM_STATES = [
    MM_MODEM_STATE_INITIALIZING,
    MM_MODEM_STATE_ENABLING,
    MM_MODEM_STATE_ENABLED,
    MM_MODEM_STATE_SEARCHING,
    MM_MODEM_STATE_CONNECTING,
    GOBI_MODEM_STATE_ENABLING,
    GOBI_MODEM_STATE_ENABLED,
    GOBI_MODEM_STATE_SEARCHING,
    GOBI_MODEM_STATE_CONNECTING
]

STABLE_MODEM_STATES = [
    MM_MODEM_STATE_DISABLED,
    MM_MODEM_STATE_REGISTERED,
    MM_MODEM_STATE_CONNECTED,
    GOBI_MODEM_STATE_REGISTERED,
    GOBI_MODEM_STATE_CONNECTED
]

class cellular_StaleModemReboot(test.test):
    """
    Uses servo to cold reboot the device if modem is not available or is not in
    testable state.

    The test attempts to get modem status by running the 'modem status' command
    on the DUT. If it is unsuccessful in getting the modem status or the modem
    is in a bad state, it will try to reboot the DUT.

    """

    version = 1

    def _modem_state_to_string(self, state):
        if not state:
            return NO_MODEM_STATE_AVAILABLE

        if state in GOBI_MODEM_STATES:
            """
            Fix the index for MODEM_STATE_STRINGS
            """
            state = ''.join(('1', state[:-1]))

        state = int(state)

        MODEM_STATE_STRINGS = [
            'FAILED',
            'UNKNOWN',
            'INITIALIZING',
            'LOCKED',
            'DISABLED',
            'DISABLING',
            'ENABLING',
            'ENABLED',
            'SEARCHING',
            'REGISTERED',
            'DISCONNECTING',
            'CONNECTING',
            'CONNECTED',
            'DISABLING',
            'ENABLING',
            'ENABLED',
            'SEARCHING',
            'REGISTERED',
            'DISCONNECTING',
            'CONNECTING',
            'CONNECTED'
        ]
        return MODEM_STATE_STRINGS[state + 1]


    def _format_modem_status(self, modem_status):
        """
        Formats the modem status data and inserts it into a dictionary.

        @param modem_status: Command line output of 'modem status'.
        @return modem status dictionary

        """

        modem_state = ''
        modem_status_dict = {}

        if not modem_status:
            return None

        lines = modem_status.splitlines()

        for item in lines:
            columns = item.split(':')
            columns = [x.strip() for x in columns]
            if len(columns) > 1:
                modem_status_dict[columns[0]] = columns[1]
            else:
                modem_status_dict[columns[0]] = ''

        return modem_status_dict


    def _get_modem_status(self):
        try:
            modem_status = self._client.run('modem status').stdout.strip()
            modem_status_dict = self._format_modem_status(modem_status)
            return modem_status_dict
        except error.AutoservRunError as e:
            logging.debug("AutoservRunError is: %s", e)
            return None


    def _get_modem_state(self):
        modem_status_dict = self._get_modem_status()

        if not modem_status_dict:
            return None

        return modem_status_dict.get('State')


    def _cold_reset_dut(self, boot_id):
        # TODO(dshi): power_off() / power_on() may not work on all devices at
        # this time but the fix is on the way. crbug.com/352404
        self._servo.get_power_state_controller().power_off()
        self._servo.get_power_state_controller().power_on()
        time.sleep(self._servo.BOOT_DELAY)
        self._client.wait_for_restart(old_boot_id=boot_id)
        self._wait_for_stable_modem_state()


    def _wait_for_stable_modem_state(self):
        """
        Wait for a maximum of _MODEM_WAIT_DELAY seconds for the modem to get
        into stable state. Also, because we do not want the test to terminate
        in case there is an exception, we are catching and logging the exception
        so the test can continue with rebooting the device again as needed.

        """

        try:
            utils.poll_for_condition(
                  lambda: self._get_modem_state() in STABLE_MODEM_STATES,
                  exception=utils.TimeoutError('Modem not in stable state '
                                               'after %s seconds.' %
                                               _MODEM_WAIT_DELAY),
                  timeout=_MODEM_WAIT_DELAY,
                  sleep_interval=5)
        except utils.TimeoutError as e:
            logging.debug("Stable modem state TimeoutError is: %s", e)


    def run_once(self, host, tries=2, expect_auto_registration=True):
        """
        Runs the test.

        @param host: A host object representing the DUT.
        @param tries: Maximum number of times test will try to reboot the DUT.
                Default number of tries is 2, which is set in the control file.
        @param expect_auto_registration: To be used with an exceptional modem
                that does not auto-register by passing False from modem specific
                control file.
        @raise error.TestFail if modem cannot be brought to a testable stated.

        """

        self._client = host
        self._servo = host.servo

        if not self._servo:
            logging.info('Host %s does not have a servo.', host.hostname)
            return

        if not expect_auto_registration:
            STABLE_MODEM_STATES.extend(ENABLED_MODEM_STATES)
            WAIT_DELAY_MODEM_STATES.remove(MM_MODEM_STATE_ENABLED)
            WAIT_DELAY_MODEM_STATES.remove(GOBI_MODEM_STATE_ENABLED)

        original_modem_state = self._get_modem_state()

        logging.info('Modem state before reboot on host %s: %s',
                     host.hostname,
                     self._modem_state_to_string(original_modem_state))

        boot_id = self._client.get_boot_id()
        self._cold_reset_dut(boot_id)
        new_modem_state = self._get_modem_state()

        num_tries = 0

        while True:
            if new_modem_state in STABLE_MODEM_STATES:
                logging.info('Modem is in testable state: '
                             '%s', self._modem_state_to_string(new_modem_state))
                break
            if new_modem_state == MM_MODEM_STATE_LOCKED:
                raise error.TestFail('Modem in locked state.')
            if num_tries == tries:
                logging.info('Modem still in bad state after %s reboot tries '
                             'on host %s. Modem state: %s ',
                             tries+1, host.hostname,
                             self._modem_state_to_string(new_modem_state))
                raise error.TestFail('Modem is not in testable state')
            num_tries += 1
            self._cold_reset_dut(boot_id)
            new_modem_state = self._get_modem_state()
