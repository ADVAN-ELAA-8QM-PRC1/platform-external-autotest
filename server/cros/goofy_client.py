# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
import httplib
import logging
import os
import re
import socket
import time

import common

from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros import retry
from autotest_lib.server import utils


GOOFY_JSONRPC_SERVER_PORT = 0x0FAC
GOOFY_RUNNING = 'RUNNING'


class GoofyProxyException(Exception):
    """Exception raised when a goofy rpc fails."""
    pass


class GoofyProxy(object):
    """Client capable of making rpc calls to goofy.

    Methods of this class that can cause goofy to change state
    usually need a retry decorator. Methods that have a retry decorator
    need to be 'pure', i.e return the same results when called multiple
    times with the same argument.

    There are 2 known exceptions this class can deal with, a socket.error
    which happens when we try to execute an rpc when the DUT is, say, suspended
    and a BadStatusLine, which we get when we try to execute an rpc while the
    DUT is going through a factory_restart. Ideally we would like to handle
    socket timeouts different from BadStatusLines as we can get connection
    errors even when a device reboots and BadStatusLines ususally only when
    factory restarts. crbug.com/281714.
    """

    # This timeout was arbitrarily chosen as many tests in the factory test
    # suite run for days. Ideally we would like to split this into at least 2
    # timeouts, one which we use for rpcs that run while no other test is,
    # running and is smaller than the second that is designed for use with rpcs
    # that might execute simultaneously with a test. The latter needs a longer
    # timeout since tests could suspend,resume for a long time, and a call like
    # GetGoofyStatus should be tolerant to these suspend/resumes. In designing
    # the base timeout one needs to allocate time to component methods of this
    # class (such as _set_test_list) as a multiple of the number of rpcs it
    # executes.
    BASE_RPC_TIMEOUT = 1440
    POLLING_INTERVAL = 5
    FACTORY_BUG_RE = r'.*(/tmp/factory_bug.*tar.bz2).*'
    UNTAR_COMMAND = 'tar jxf %s -C %s'


    def __init__(self, host):
        """
        @param host: The host object representing the DUT running goofy.
        """
        self._host = host
        self._client = host.jsonrpc_connect(GOOFY_JSONRPC_SERVER_PORT)


    @retry.retry((httplib.BadStatusLine, socket.error),
                 timeout_min=BASE_RPC_TIMEOUT)
    def _get_goofy_status(self):
        """Return status of goofy, ignoring socket timeouts and http exceptions.
        """
        status = self._client.GetGoofyStatus().get('status')
        return status


    def _wait_for_goofy(self, timeout_min=BASE_RPC_TIMEOUT*2):
        """Wait till goofy is running or a timeout occurs.

        @param timeout_min: Minutes to wait before timing this call out.
        """
        current_time = time.time()
        timeout_secs = timeout_min * 60
        logging.info('Waiting on goofy')
        while self._get_goofy_status() != GOOFY_RUNNING:
            if time.time() - current_time > timeout_secs:
                break
        return


    @retry.retry(socket.error, timeout_min=BASE_RPC_TIMEOUT*2)
    def _set_test_list(self, next_list):
        """Set the given test list for execution.

        Confirm that the given test list is a test that has been baked into
        the image, then run it. Some test lists are configured to start
        execution automatically when we call SetTestList, while others wait
        for a corresponding RunTest.

        @param next_list: The name of the test list.

        @raise jsonrpclib.ProtocolError: If the test list we're trying to switch
                                         to isn't on the DUT.
        """

        # As part of SwitchTestList we perform a factory restart,
        # which will throw a BadStatusLine. We don't want to retry
        # on this exception though, as that will lead to setting the same
        # test list over and over till the timeout expires. If the test
        # list is not already on the DUT this method will fail, emitting
        # the possible test lists one can switch to.
        try:
            self._client.SwitchTestList(next_list)
        except httplib.BadStatusLine:
            logging.info('Switched to list %s, goofy restarting', next_list)
            pass


    @retry.retry((httplib.BadStatusLine, socket.error),
                 timeout_min=BASE_RPC_TIMEOUT*2)
    def _stop_running_tests(self):
       """Stop all running tests.

       Wrap the StopTest rpc so we can attempt to stop tests even while a DUT
       is suspended or rebooting.
       """
       logging.info('Stopping tests.')
       self._client.StopTest()


    def _get_test_map(self):
        """Get a mapping of test suites -> tests.

        Ignore entries for tests that don't have a path.

        @return: A dictionary of the form
                 {'suite_name': ['suite_name.path_to_test', ...]}.
        """
        test_all = set([test['path'] for test in self._client.GetTests()
                        if test.get('path')])

        test_map = collections.defaultdict(list)
        for names in test_all:
            test_map[names.split('.')[0]].append(names)
        return test_map


    def _log_test_results(self, test_status, current_suite):
        """Format test status results and write them to status.log.

        @param test_status: The status dictionary of a single test.
        @param current_suite: The current suite name.
        """
        try:
            self._host.job.record('INFO', None, None,
                                  'suite %s, test %s, status: %s' %
                                  (current_suite, test_status.get('path'),
                                   test_status.get('status')))
        except AttributeError as e:
            logging.error('Could not gather results for current test: %s', e)


    @retry.retry((httplib.BadStatusLine, socket.error),
                 timeout_min=BASE_RPC_TIMEOUT*2)
    def _get_test_info(self, test_name):
        """Get the status of one test.

        @param test_name: The name of the test we need the status of.

        @return: The entry for the test in the status dictionary.
        """
        for test in self._client.GetTests():
            if test['path'] == test_name:
                return test
        raise ValueError('Could not find test_name %s in _get_test_info.' %
                          test_name)


    def _wait_on_barrier(self, barrier_name):
        """Wait on a barrier.

        This method is designed to wait on the Barrier of a suite. A Barrier
        is used to synchronize several tests that run in parallel within a
        suite; it will cause the suite to hang while it attempts to show
        an operator the status of each test, and is activated once all the
        tests in the suite are done.

        @param barrier_name: The name of the barrier.
        """
        logging.info('Waiting on barrier %s', barrier_name)

        # TODO(beeps): crbug.com/279473
        while self._get_test_info(barrier_name)['status'] != 'ACTIVE':
            time.sleep(self.POLLING_INTERVAL)


    def _wait_on_suite(self, suite_name):
        """Wait till a suite stops being active.

        This method is designed to wait on the suite to change
        status if it lacks a 'Barrier'. If a suite has a barrier
        one should use _wait_on_barrier instead.

        @param suite_name: The name of the suite to wait on.
        """
        logging.info('Waiting on suite %s', suite_name)

        while self._get_test_info(suite_name)['status'] == 'ACTIVE':
            time.sleep(self.POLLING_INTERVAL)


    def _synchronous_run_suite(self, suite_name, barrier_name=None):
        """Run one suite and wait for it to finish.

        Will wait till the specified suite_name becomes active,
        then wait till it switches out of active. If the suite
        has a barrier, will wait till the barrier becomes active
        instead, as this indicates that all tests have finished
        running.

        @param suite_name: The name of the suite to wait for.
        @param barrier_name: The name of the barrier, if any.

        @raises GoofyProxyException: If the status of the suite
            doesn't switch to active after we call RunTest.

        @return: The result of the suite.
        """
        self._client.RunTest(suite_name)
        result = self._get_test_info(suite_name)

        #TODO(beeps): crbug.com/292975
        if result['status'] != 'ACTIVE':
            raise GoofyProxyException('Not waiting for test list %s. Either we '
                                      'could not start it or the test list '
                                      'already finished.' % suite_name)

        if barrier_name:
            self._wait_on_barrier(barrier_name)
        else:
            self._wait_on_suite(suite_name)

        # Since the barrier itself counts as a 'test' we need to stop
        # it before asking goofy for the suites results, or goofy will
        # think that the suite is still running. We also need to stop
        # any orphaned test that might have been kicked off during this
        # suite.
        self._stop_running_tests()
        return self._get_test_info(suite_name)


    def monitor_tests(self, test_list):
        """Run a test list.

        Will run each suite in the given list in sequence, starting each one
        by name and waiting on its results. This method makes the following
        assumptions:
            - A test list is made up of self contained suites.
            - These suites trigger several things in parallel.
            - After a suite finishes it leaves goofy in an idle state.

        It is not safe to pull results for individual tests during the suite
        as the device could be rebooting, or goofy could be under stress.
        Instead, this method synchronously waits on an entire suite, then
        asks goofy for the status of each test in the suite. Since certain
        test lists automatically start and others don't, this method stops
        test list execution regardless, and sequentially triggers each suite.

        @param test_list: The test list to run.
        """
        self._set_test_list(test_list)
        self._wait_for_goofy()
        self._stop_running_tests()

        test_map = self._get_test_map()
        for current_suite in test_map.keys():
            logging.info('Processing suite %s', current_suite)

            # Check if any of these tests are actually a Barrier.
            barrier = None
            for test in test_map.get(current_suite):
                if '.' in test and 'Barrier' in test.split('.')[1]:
                    barrier = test
                    break

            logging.info('Current suite = %s, barrier: %s', current_suite,
                         barrier)

            result = self._synchronous_run_suite(current_suite, barrier)
            logging.info(result)

            for test_names in test_map.get(current_suite):
                self._log_test_results(self._get_test_info(test_names),
                                       current_suite)


    @retry.retry((httplib.BadStatusLine, socket.timeout), timeout_min=1)
    def get_results(self, resultsdir):
        """Copies results from the DUT to a local results directory.

        Copy the tarball over to the results folder, untar, and delete the
        tarball if everything was successful. This will effectively place
        all the logs relevant to factory testing in the job's results folder.

        @param resultsdir: The directory in which to untar the contents of the
                           tarball factory_bug generates.
        """
        logging.info('Getting results logs for test_list.')

        try:
            factory_bug_log = self._host.run('factory_bug').stderr
        except error.CmdError as e:
            logging.error('Could not execute factory_bug: %s', e)
            return

        try:
            factory_bug_tar = re.match(self.FACTORY_BUG_RE,
                                       factory_bug_log).groups(1)[0]
        except (IndexError, AttributeError):
            logging.error('could not collect logs for factory results, '
                          'factory bug returned %s', factory_bug_log)
            return

        factory_bug_tar_file = os.path.basename(factory_bug_tar)
        local_factory_bug_tar = os.path.join(resultsdir, factory_bug_tar_file)

        try:
            self._host.get_file(factory_bug_tar, local_factory_bug_tar)
        except error.AutoservRunError as e:
            logging.error('Failed to pull back the results tarball: %s', e)
            return

        try:
            utils.run(self.UNTAR_COMMAND % (local_factory_bug_tar, resultsdir))
        except error.CmdError as e:
            logging.error('Failed to untar the results tarball: %s', e)
            return
        finally:
            if os.path.exists(local_factory_bug_tar):
                os.remove(local_factory_bug_tar)


