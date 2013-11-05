# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging, time, traceback
from autotest_lib.client.common_lib import error
from autotest_lib.server import autotest
from autotest_lib.server import hosts
from autotest_lib.server import utils, test

class hardware_StorageStress(test.test):
    """
    Integrity stress test for storage device
    """
    version = 1

    # Define default value for the test case
    _TEST_GAP = 60 # 1 min
    _TEST_DURATION = 12 * 60 * 60 # 12 hours
    _FIO_REQUIREMENT_FILE = '8k_async_randwrite'
    _FIO_WRITE_FLAGS = []
    _FIO_VERIFY_FLAGS = ['--verifyonly']

    def run_once(self, client_ip, gap=_TEST_GAP, duration=_TEST_DURATION,
                 power_command='reboot', test_command='integrity'):
        """
        Run the Storage stress test
        Use hardwareStorageFio to run some test_command repeatedly for a long
        time. Between each iteration of test command, run power command such as
        reboot or suspend.

        @param client_ip:     string of client's ip address (required)
        @param gap:           gap between each test (second) default = 1 min
        @param duration:      duration to run test (second) default = 12 hours
        @param power_command: command to do between each test Command
                              possible command: reboot / suspend / nothing
        @param test_command:  FIO command to run
                              - integrity:  Check data integrity
        """

        # init test
        if not client_ip:
            error.TestError("Must provide client's IP address to test")

        self._client = hosts.create_host(client_ip)
        self._client_at = autotest.Autotest(self._client)
        self._results = {}

        start_time = time.time()

        # parse power command
        if power_command == 'nothing':
            power_func = self._do_nothing
        elif power_command == 'reboot':
            power_func = self._do_reboot
        elif power_command == 'suspend':
            power_func = self._do_suspend
        else:
            raise error.TestFail(
                'Test failed with error: Invalid power command')

        # parse test command
        if test_command == 'integrity':
            setup_func = self._write_data
            loop_func = self._verify_data
        else:
            raise error.TestFail('Test failed with error: Invalid test command')

        setup_func()

        # init statistic variable
        min_time_per_loop = self._TEST_DURATION
        max_time_per_loop = 0
        all_loop_time = 0
        avr_time_per_loop = 0
        self._loop_count = 0

        while time.time() - start_time < duration:
            # sleep
            time.sleep(gap)

            self._loop_count += 1

            # do power command & verify data & calculate time
            loop_start_time = time.time()
            power_func()
            loop_func()
            loop_time = time.time() - loop_start_time

            # update statistic
            all_loop_time += loop_time
            min_time_per_loop = min(loop_time, min_time_per_loop)
            max_time_per_loop = max(loop_time, max_time_per_loop)

        if self._loop_count > 0:
            avr_time_per_loop = all_loop_time / self._loop_count

        logging.info(str('check data count: %d' % self._loop_count))

        # report result
        self.write_perf_keyval({'loop_count':self._loop_count})
        self.write_perf_keyval({'min_time_per_loop':min_time_per_loop})
        self.write_perf_keyval({'max_time_per_loop':max_time_per_loop})
        self.write_perf_keyval({'avr_time_per_loop':avr_time_per_loop})

    def _do_nothing(self):
        pass

    def _do_reboot(self):
        """
        Reboot host machine
        """
        logging.info('Server: reboot client')
        try:
            self._client.reboot()
        except error.AutoservRebootError as e:
            raise error.TestFail('%s.\nTest failed with error %s' % (
                    traceback.format_exc(), str(e)))

    def _do_suspend(self):
        """
        Suspend host machine
        """
        logging.info('Server: suspend client')
        self._client_at.run_test('power_Resume')
        passed = self._check_result()
        if not passed:
            raise error.TestFail('Test failed with error: Suspend Error')


    def _check_result(self):
        """
        Check result of the client test.
        Auto test will store results in the file named status.
        We check that the second to last line in that file begin with 'END GOOD'

        @ return True if last test passed, False otherwise.
        """
        # Is there any better way to do this?
        status = utils.system_output('tail -2 status | head -1').strip()
        logging.info(status)
        return status[:8] == 'END GOOD'


    def _write_data(self):
        """
        Write test data to host using hardware_StorageFio
        """
        logging.info('_write_data')
        self._client_at.run_test('hardware_StorageFio', wait=0,
                                 requirements=[(self._FIO_REQUIREMENT_FILE,
                                                self._FIO_WRITE_FLAGS)])
        passed = self._check_result()
        if not passed:
            raise error.TestFail('Test failed with error: Data Write Error')

    def _verify_data(self):
        """
        Vertify test data using hardware_StorageFio
        """
        logging.info(str('_verify_data #%d' % self._loop_count))
        self._client_at.run_test('hardware_StorageFio', wait=0,
                                 requirements=[(self._FIO_REQUIREMENT_FILE,
                                                self._FIO_VERIFY_FLAGS)])
        passed = self._check_result()
        if not passed:
            raise error.TestFail('Test failed with error: Data Verify #%d Error'
                % self._loop_count)
