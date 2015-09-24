# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os

import common
from autotest_lib.client.common_lib import error
from autotest_lib.server import site_gtest_runner
from autotest_lib.server import test


NATIVE_TESTS_PATH = '/data/nativetest'

class brillo_Gtests(test.test):
    """Run one or more native gTest Suites."""
    version = 1

    def _find_all_gtestsuites(self):
        """Find all the gTest Suites installed on the DUT."""
        nativetests_contents = self.host.run_output(
                'ls -d -1 %s/*/*' % NATIVE_TESTS_PATH)
        gtestSuites = nativetests_contents.splitlines()
        if not gtestSuites:
            raise error.TestWarn('No gTest executables found on the DUT!')
        logging.debug('gTest executables found:\n%s', '\n'.join(gtestSuites))
        return gtestSuites


    def run_gtestsuite(self, gtestSuite):
        """Run a gTest Suite.

        @param gtestSuite: Full path to gtestSuite executable or the relative
                           path to the executable under /data/nativetest

        @return True if the all the tests in the gTest Suite pass. False
                otherwise.
        """
        # Make sure the gTest Suite exists, if not try to see if it exists
        # within the native tests folder.
        result = self.host.run('test -e %s' % gtestSuite, ignore_status=True)
        if not result.exit_status == 0:
            try:
                alt_gtestSuite = os.path.join(NATIVE_TESTS_PATH, gtestSuite)
                self.host.run('test -e %s' % alt_gtestSuite)
                gtestSuite = alt_gtestSuite
            except error.AutoservRunError:
                logging.error('Unable to find %s', gtestSuite)
                return False

        try:
            self.host.run('test -x %s' % gtestSuite)
        except error.AutoservRunError:
            self.host.run('chmod +x %s' % gtestSuite)
        logging.debug('Running gTest Suite: %s', gtestSuite)
        result = self.host.run(gtestSuite, ignore_status=True)
        logging.debug(result.stdout)
        parser = site_gtest_runner.gtest_parser()
        for line in result.stdout.splitlines():
            parser.ProcessLogLine(line)
        passed_tests = parser.PassedTests()
        if passed_tests:
            logging.debug('Passed Tests: %s', passed_tests)
        failed_tests = parser.FailedTests(include_fails=True,
                                          include_flaky=True)
        if failed_tests:
            logging.error('Failed Tests: %s', failed_tests)
            for test in failed_tests:
                logging.error('Test %s failed:\n%s', test,
                              parser.FailureDescription(test))
            return False
        if result.exit_status != 0:
            logging.error('gTest Suite %s exited with exit code: %s',
                          gtestSuite, result.exit_status)
            return False
        return True


    def run_once(self, host=None, gtestSuites=None):
        """Run gTest Suites on the DUT.

        @param host: host object representing the device under test.
        @param gtestSuites: List of gTest suites to run. Default is to run
                            every gTest suite on the host.
        """
        self.host = host
        if not gtestSuites:
            gtestSuites = self._find_all_gtestsuites()

        failed_gtestSuites = []
        for gtestSuite in gtestSuites:
            if not self.run_gtestsuite(gtestSuite):
                failed_gtestSuites.append(gtestSuite)

        if failed_gtestSuites:
            logging.error('The following gTest Suites failed: \n %s',
                          '\n'.join(failed_gtestSuites))
            raise error.TestFail(
                    '\nNot all gTest Suites completed successfully.\n'
                    '%s out of %s suites failed.\n'
                    'Failed Suites: %s' % (len(failed_gtestSuites),
                                           len(gtestSuites),
                                           failed_gtestSuites))
