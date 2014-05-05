#!/usr/bin/python
#
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Tool to validate code in prod branch before pushing to lab.

The script runs push_to_prod suite to verify code in prod branch is ready to be
pushed. Link to design document:
https://docs.google.com/a/google.com/document/d/1JMz0xS3fZRSHMpFkkKAL_rxsdbNZomhHbC3B8L71uuI/edit

To verify if prod branch can be pushed to lab, run following command in
chromeos-autotest.cbf server:
/usr/locl/autotest/site_util/test_push.py -e someone@company.com

The script uses latest stumpy canary build as test build by default.

"""

import argparse
import getpass
import os
import re
import subprocess
import sys
import urllib2

import common
from autotest_lib.client.common_lib import global_config, mail
from autotest_lib.server import site_utils
from autotest_lib.server.cros.dynamic_suite import frontend_wrappers
from autotest_lib.server.cros.dynamic_suite import reporting

CONFIG = global_config.global_config

MAIL_FROM = 'chromeos-test@google.com'
DEVSERVER = CONFIG.get_config_value('CROS', 'dev_server', type=list,
                                    default=[])[0]
RUN_SUITE_COMMAND = 'run_suite.py'
PUSH_TO_PROD_SUITE = 'push_to_prod'
AU_SUITE = 'paygen_au_canary'

SUITE_JOB_START_INFO_REGEX = ('^.*Created suite job:.*'
                              'tab_id=view_job&object_id=(\d+)$')

# Dictionary of test results keyed by test name regular expression.
EXPECTED_TEST_RESULTS = {'^SERVER_JOB$':                 'GOOD',
                         # This is related to dummy_Fail/control.dependency.
                         'dummy_Fail.dependency$':       'TEST_NA',
                         'telemetry_CrosTests.*':        'GOOD',
                         'platform_InstallTestImage_SERVER_JOB$': 'GOOD',
                         'dummy_Pass.*':                 'GOOD',
                         'dummy_Fail.Fail$':             'FAIL',
                         'dummy_Fail.RetryFail$':        'FAIL',
                         'dummy_Fail.RetrySuccess':      'GOOD',
                         'dummy_Fail.Error$':            'ERROR',
                         'dummy_Fail.Warn$':             'WARN',
                         'dummy_Fail.NAError$':          'TEST_NA',
                         'dummy_Fail.Crash$':            'GOOD',
                         }

EXPECTED_TEST_RESULTS_AU = {'SERVER_JOB$':                        'GOOD',
         'autoupdate_EndToEndTest.paygen_au_canary_test_delta.*': 'GOOD',
         'autoupdate_EndToEndTest.paygen_au_canary_test_full.*':  'GOOD',
         }

# Anchor for the auto-filed bug for dummy_Fail tests.
BUG_ANCHOR = 'TestFailure(push_to_prod,dummy_Fail.Fail,always fail)'

URL_HOST = CONFIG.get_config_value('SERVER', 'hostname', type=str)
URL_PATTERN = CONFIG.get_config_value('CROS', 'log_url_pattern', type=str)

# Save all run_suite command output.
run_suite_output = []

class TestPushException(Exception):
    """Exception to be raised when the test to push to prod failed."""
    pass

def parse_arguments():
    """Parse arguments for test_push tool.

    @return: Parsed arguments.

    """
    parser = argparse.ArgumentParser()
    parser.add_argument('-b', '--board', dest='board', default='stumpy',
                        help='Default is stumpy.')
    parser.add_argument('-i', '--build', dest='build', default=None,
                        help='Default is the latest canary build of given '
                             'board. Must be a canary build, otherwise AU test '
                             'will fail.')
    parser.add_argument('-p', '--pool', dest='pool', default='bvt')
    parser.add_argument('-u', '--num', dest='num', type=int, default=3,
                        help='Run on at most NUM machines.')
    parser.add_argument('-f', '--file_bugs', dest='file_bugs', default='True',
                        help='File bugs on test failures. Must pass "True" or '
                             '"False" if used.')
    parser.add_argument('-e', '--email', dest='email', default=None,
                        help='Email address for the notification to be sent to '
                             'after the script finished running.')
    parser.add_argument('-d', '--devserver', dest='devserver',
                        default=DEVSERVER,
                        help='devserver to find what\'s the latest build.')

    arguments = parser.parse_args(sys.argv[1:])

    # Get latest canary build as default build.
    if not arguments.build:
        url = '%s/latestbuild?target=%s-release' % (arguments.devserver,
                                                    arguments.board)
        latest_build = urllib2.urlopen(url).read()
        default_build = '%s-release/%s' % (arguments.board, latest_build)
        arguments.build = default_build

    return arguments


def do_run_suite(suite_name, arguments):
    """Call run_suite to run a suite job, and return the suite job id.

    The script waits the suite job to finish before returning the suite job id.
    Also it will echo the run_suite output to stdout.

    @param suite_name: Name of a suite, e.g., dummy.
    @param arguments: Arguments for run_suite command.
    @return: Suite job ID.

    """
    dir = os.path.dirname(os.path.realpath(__file__))
    cmd = [os.path.join(dir, RUN_SUITE_COMMAND),
           '-s', suite_name,
           '-b', arguments.board,
           '-i', arguments.build,
           '-p', arguments.pool,
           '-u', str(arguments.num),
           '-f', arguments.file_bugs]

    suite_job_id = None

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)

    while True:
        line = proc.stdout.readline()

        # Break when run_suite process completed.
        if not line and proc.poll() != None:
            break
        print line.rstrip()
        run_suite_output.append(line.rstrip())

        if not suite_job_id:
            m = re.match(SUITE_JOB_START_INFO_REGEX, line)
            if m and m.group(1):
                suite_job_id = int(m.group(1))

    if not suite_job_id:
        raise TestPushException('Failed to retrieve suite job ID.')
    return suite_job_id


def test_suite(suite_name, expected_results, arguments):
    """Call run_suite to start a suite job and verify results.

    @param suite_name: Name of a suite, e.g., dummy
    @param expected_results: A dictionary of test name to test result.
    @param arguments: Arguments for run_suite command.

    """
    suite_job_id = do_run_suite(suite_name, arguments)

    # Find all tests and their status
    print 'Suite job %s is completed, comparing test results...' % suite_job_id
    TKO = frontend_wrappers.RetryingTKO(timeout_min=0.1, delay_sec=10)
    test_views = site_utils.get_test_views_from_tko(suite_job_id, TKO)

    mismatch_errors = []
    extra_test_errors = []

    found_keys = set()
    for test_name,test_status in test_views.items():
        print "%s%s" % (test_name.ljust(30), test_status)
        test_found = False
        for key,val in expected_results.items():
            if re.search(key, test_name):
                test_found = True
                found_keys.add(key)
                # TODO(dshi): result for this test is ignored until servo is
                # added to a host accessible by cbf server (crbug.com/277109).
                if key == 'platform_InstallTestImage_SERVER_JOB$':
                    continue
                # TODO(dshi): result for this test is ignored until the bug is
                # fixed in Telemetry (crbug.com/369671).
                if key == 'telemetry_CrosTests.*':
                    continue
                if val != test_status:
                    error = ('%s Expected: [%s], Actual: [%s]' %
                             (test_name, val, test_status))
                    mismatch_errors.append(error)
        if not test_found:
            extra_test_errors.append(test_name)

    missing_test_errors = set(expected_results.keys()) - found_keys
    # For latest build, npo_test_delta does not exist.
    if missing_test_errors == set(['autoupdate_EndToEndTest.npo_test_delta.*']):
        missing_test_errors = set([])
    # For trybot build, nmo_test_delta does not exist.
    if missing_test_errors == set(['autoupdate_EndToEndTest.nmo_test_delta.*']):
        missing_test_errors = set([])
    summary = []
    if mismatch_errors:
        summary.append(('Results of %d test(s) do not match expected '
                        'values:') % len(mismatch_errors))
        summary.extend(mismatch_errors)
        summary.append('\n')

    if extra_test_errors:
        summary.append('%d test(s) are not expected to be run:' %
                       len(extra_test_errors))
        summary.extend(extra_test_errors)
        summary.append('\n')

    if missing_test_errors:
        summary.append('%d test(s) are missing from the results:' %
                       len(missing_test_errors))
        summary.extend(missing_test_errors)
        summary.append('\n')

    # Test link to log can be loaded.
    job_name = '%s-%s' % (suite_job_id, getpass.getuser())
    log_link = URL_PATTERN % (URL_HOST, job_name)
    try:
        urllib2.urlopen(log_link).read()
    except urllib2.URLError:
        summary.append('Failed to load page for link to log: %s.' % log_link)

    if summary:
        raise TestPushException('\n'.join(summary))


def close_bug():
    """Close all existing bugs filed for dummy_Fail.

    @return: A list of issue ids to be used in check_bug_filed_and_deduped.
    """
    old_issue_ids = []
    reporter = reporting.Reporter()
    while True:
        issue = reporter.find_issue_by_marker(BUG_ANCHOR)
        if not issue:
            return old_issue_ids
        if issue.id in old_issue_ids:
            raise TestPushException('Failed to close issue %d' % issue.id)
        old_issue_ids.append(issue.id)
        reporter.modify_bug_report(issue.id,
                                   comment='Issue closed by test_push script.',
                                   label_update='',
                                   status='WontFix')


def check_bug_filed_and_deduped(old_issue_ids):
    """Confirm bug related to dummy_Fail was filed and deduped.

    @param old_issue_ids: A list of issue ids that was closed earlier. id of the
        new issue must be not in this list.
    @raise TestPushException: If auto bug file failed to create a new issue or
        dedupe multiple failures.
    """
    reporter = reporting.Reporter()
    issue = reporter.find_issue_by_marker(BUG_ANCHOR)
    if not issue:
        raise TestPushException('Auto bug file failed. Unable to locate bug '
                                'with marker %s' % BUG_ANCHOR)
    if old_issue_ids and issue.id in old_issue_ids:
        raise TestPushException('Auto bug file failed to create a new issue. '
                                'id of the old issue found is %d.' % issue.id)
    if not ('%s2' % reporter.AUTOFILED_COUNT) in issue.labels:
        raise TestPushException(('Auto bug file failed to dedupe for issue %d '
                                 'with labels of %s.') %
                                (issue.id, issue.labels))
    # Close the bug, and do the search again, which should return None.
    reporter.modify_bug_report(issue.id,
                               comment='Issue closed by test_push script.',
                               label_update='',
                               status='WontFix')
    second_issue = reporter.find_issue_by_marker(BUG_ANCHOR)
    if second_issue:
        ids = '%d, %d' % (issue.id, second_issue.id)
        raise TestPushException(('Auto bug file failed. Multiple issues (%s) '
                                 'filed with marker %s') % (ids, BUG_ANCHOR))
    print 'Issue %d was filed and deduped successfully.' % issue.id


def main():
    """Entry point for test_push script."""
    arguments = parse_arguments()

    try:
        # Close existing bugs. New bug should be filed in dummy_Fail test.
        old_issue_ids = close_bug()
        test_suite(PUSH_TO_PROD_SUITE, EXPECTED_TEST_RESULTS, arguments)
        check_bug_filed_and_deduped(old_issue_ids)

        # TODO(dshi): Remove following line after crbug.com/267644 is fixed.
        # Also, merge EXPECTED_TEST_RESULTS_AU to EXPECTED_TEST_RESULTS
        test_suite(AU_SUITE, EXPECTED_TEST_RESULTS_AU, arguments)
    except Exception as e:
        print 'Test for pushing to prod failed:\n'
        print str(e)
        # Send out email about the test failure.
        if arguments.email:
            mail.send(MAIL_FROM,
                      [arguments.email],
                      [],
                      'Test for pushing to prod failed. Do NOT push!',
                      ('Errors occurred during the test:\n\n%s\n\n' % str(e) +
                       'run_suite output:\n\n%s' % '\n'.join(run_suite_output)))
        raise

    message = ('\nAll tests are completed successfully, prod branch is ready to'
               ' be pushed.')
    print message
    # Send out email about test completed successfully.
    if arguments.email:
        mail.send(MAIL_FROM,
                  [arguments.email],
                  [],
                  'Test for pushing to prod completed successfully',
                  message)


if __name__ == '__main__':
    sys.exit(main())
