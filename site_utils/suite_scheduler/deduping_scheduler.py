# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


from autotest_lib.server.cros import frontend_wrappers
from autotest_lib.server import frontend


class DedupingSchedulerException(Exception):
    """Base class for exceptions from this module."""
    pass


class ScheduleException(DedupingSchedulerException):
    """Raised when an error is returned from the AFE during scheduling."""
    pass


class DedupException(DedupingSchedulerException):
    """Raised when an error occurs while checking for duplicate jobs."""
    pass


class DedupingScheduler(object):
    """A class that will schedule suites to run on a given board, build.

    Includes logic to check whether or not a given (suite, board, build)
    has already been run.  If so, it will skip scheduling that suite.

    @var _afe: a frontend.AFE instance used to talk to autotest.
    """


    def __init__(self, afe=None):
        """Constructor

        @param afe: an instance of AFE as defined in server/frontend.py.
                    Defaults to a frontend_wrappers.RetryingAFE instance.
        """
        self._afe = afe or frontend_wrappers.RetryingAFE(timeout_min=30,
                                                         delay_sec=10,
                                                         debug=False)


    def _ShouldScheduleSuite(self, suite, board, build):
        """Return if |suite| has not yet been run for |build| on |board|.

        True if |suite| has not been run for |build| on |board|.
        False if it has been.

        @param suite: the name of the suite to run, e.g. 'bvt'
        @param board: the board to run the suite on, e.g. x86-alex
        @param build: the build to install e.g.
                      x86-alex-release/R18-1655.0.0-a1-b1584.
        @return False if the suite was already scheduled, True if not
        @raise DedupException if the AFE raises while searching for jobs.
        """
        try:
            return not self._afe.get_jobs(name__startswith=build,
                                          name__endswith=suite)
        except Exception as e:
            raise DedupException(e)


    def _Schedule(self, suite, board, build, pool):
        """Schedule |suite|, if it hasn't already been run.

        @param suite: the name of the suite to run, e.g. 'bvt'
        @param board: the board to run the suite on, e.g. x86-alex
        @param build: the build to install e.g.
                      x86-alex-release/R18-1655.0.0-a1-b1584.
        @param pool: the pool of machines to use for scheduling purposes.
                     Default: None
        @return True if the suite got scheduled
        @raise ScheduleException if an error occurs while scheduling.
        """
        try:
            if self._afe.run('create_suite_job',
                             suite_name=suite,
                             board=board,
                             build=build,
                             check_hosts=False,
                             pool=pool) is not None:
                return True
            else:
                raise ScheduleException(
                    "Can't schedule %s for %s." % (suite, build))
        except Exception as e:
            raise ScheduleException(e)


    def ScheduleSuite(self, suite, board, build, pool, force=False):
        """Schedule |suite|, if it hasn't already been run.

        If |suite| has not already been run against |build| on |board|,
        schedule it and return True.  If it has, return False.

        @param suite: the name of the suite to run, e.g. 'bvt'
        @param board: the board to run the suite on, e.g. x86-alex
        @param build: the build to install e.g.
                      x86-alex-release/R18-1655.0.0-a1-b1584.
        @param pool: the pool of machines to use for scheduling purposes.
        @param force: Always schedule the suite.
        @return True if the suite got scheduled, False if not
        @raise DedupException if we can't check for dups.
        @raise ScheduleException if the suite cannot be scheduled.
        """
        if force or self._ShouldScheduleSuite(suite, board, build):
            return self._Schedule(suite, board, build, pool)
        return False
