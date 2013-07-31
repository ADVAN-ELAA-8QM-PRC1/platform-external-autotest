#!/usr/bin/python
#
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


import datetime, logging, os, subprocess, sys

import common
from autotest_lib.client.common_lib import mail
from autotest_lib.frontend import setup_django_readonly_environment

# Django and the models are only setup after
# the setup_django_readonly_environment module is imported.
from autotest_lib.frontend.afe import models as afe_models
from autotest_lib.frontend.health import utils


# Keep tests that have not failed for at least this many days.
_MIN_DAYS_SINCE_FAILURE = 30
# Ignore any tests that have not passed in this many days.
_MAX_DAYS_SINCE_LAST_PASS = 30

_MAIL_RESULTS_FROM = 'chromeos-test-health@google.com'
_MAIL_RESULTS_TO = 'chromeos-lab-infrastructure@google.com'


def update_afe_autotests_table():
    """Runs the test_importer.py script to update the afe_autotests table."""
    dirname = os.path.dirname(__file__)
    utils_dir = os.path.abspath(os.path.join(dirname, os.pardir, os.pardir,
                                             'utils'))
    test_importer_script = os.path.join(utils_dir, 'test_importer.py')
    return_code = subprocess.call([test_importer_script])

    if return_code != 0:
        logging.warn('Update DB failed: '
                     'test_importer.py had nonzero return code %d.',
                      return_code)


def get_experimental_tests():
    """
    Get all the tests marked experimental from the afe_autotests table.

    @return the set of experimental test names.

    """
    entries = afe_models.Test.objects.values('name').filter(experimental=True)
    return {entry['name'] for entry in entries}


def find_long_passing_tests(pass_times, fail_times, valid_names):
    """
    Determine the experimental tests that have been passsing for a long time.

    @param pass_times: The dictionary of test_name:pass_time pairs.
    @param fail_times: The dictionary of test_name:fail_time pairs.
    @param valid_names: An iterable of experimental test names.

    @return the list of experimental test names that have been passing for a
        long time.

    """
    failure_cutoff_date = (datetime.datetime.today() -
                           datetime.timedelta(_MIN_DAYS_SINCE_FAILURE))
    pass_cutoff_date = (datetime.datetime.today() -
                        datetime.timedelta(_MAX_DAYS_SINCE_LAST_PASS))

    valid_passes = {test for test in valid_names if test in pass_times}
    valid_failures = {test for test in valid_names if test in fail_times}

    recent_passes = {test for test in valid_passes
                     if (pass_times[test] > pass_cutoff_date)}
    recent_fails = {test for test in valid_failures
                    if (fail_times[test] > failure_cutoff_date)}

    return recent_passes - recent_fails


def main():
    """
    The script code.

    Allows other python code to import and run this code. This will be more
    important if a nice way to test this code can be determined.

    """
    update_afe_autotests_table()

    experimental_tests = get_experimental_tests()
    pass_times = utils.get_last_pass_times()
    fail_times = utils.get_last_fail_times()

    long_passers = find_long_passing_tests(pass_times, fail_times,
                                           experimental_tests)

    if long_passers:
        mail.send(_MAIL_RESULTS_FROM,
                  [_MAIL_RESULTS_TO],
                  [],
                  'Long Passing Experimental Tests',
                  'The following experimental tests have been passing for at '
                  'least %i days:\n\n%s'
                  % (_MIN_DAYS_SINCE_FAILURE, '\n'.join(sorted(long_passers))))

    return 0


if __name__ == '__main__':
    sys.exit(main())
