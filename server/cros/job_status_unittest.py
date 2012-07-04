#!/usr/bin/python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for server/cros/dynamic_suite.py."""

import logging
import mox
import shutil
import tempfile
import time
import unittest

from autotest_lib.server.cros import job_status
from autotest_lib.server.cros.dynamic_suite_fakes import FakeJob, FakeStatus
from autotest_lib.server import frontend


class StatusTest(mox.MoxTestBase):
    """Unit tests for job_status.Status.
    """


    def setUp(self):
        super(StatusTest, self).setUp()
        self.afe = self.mox.CreateMock(frontend.AFE)
        self.tko = self.mox.CreateMock(frontend.TKO)

        self.tmpdir = tempfile.mkdtemp(suffix=type(self).__name__)


    def tearDown(self):
        super(StatusTest, self).tearDown()
        shutil.rmtree(self.tmpdir, ignore_errors=True)


    def expect_result_gathering(self, job):
        self.afe.get_jobs(id=job.id, finished=True).AndReturn(job)
        entries = map(lambda s: s.entry, job.statuses)
        self.afe.run('get_host_queue_entries',
                     job=job.id).AndReturn(entries)
        if True not in map(lambda e: 'aborted' in e and e['aborted'], entries):
            self.tko.get_status_counts(job=job.id).AndReturn(job.statuses)


    def testWaitForResults(self):
        """Should gather status and return records for job summaries."""

        jobs = [FakeJob(0, [FakeStatus('GOOD', 'T0', ''),
                            FakeStatus('GOOD', 'T1', '')]),
                FakeJob(1, [FakeStatus('ERROR', 'T0', 'err', False),
                            FakeStatus('GOOD', 'T1', '')]),
                FakeJob(2, [FakeStatus('TEST_NA', 'T0', 'no')]),
                FakeJob(3, [FakeStatus('FAIL', 'T0', 'broken')]),
                FakeJob(4, [FakeStatus('ERROR', 'T0', 'gah', True)])]
        # To simulate a job that isn't ready the first time we check.
        self.afe.get_jobs(id=jobs[0].id, finished=True).AndReturn([])
        # Expect all the rest of the jobs to be good to go the first time.
        for job in jobs[1:]:
            self.expect_result_gathering(job)
        # Then, expect job[0] to be ready.
        self.expect_result_gathering(jobs[0])
        # Expect us to poll twice.
        self.mox.StubOutWithMock(time, 'sleep')
        time.sleep(5)
        time.sleep(5)
        self.mox.ReplayAll()

        results = [result for result in job_status.wait_for_results(self.afe,
                                                                    self.tko,
                                                                    jobs)]
        for job in jobs:
            for status in job.statuses:
                self.assertTrue(True in map(status.equals_record, results))


    def testGatherPerHostResults(self):
        """Should gather per host results."""
        # For the 0th job, the 1st entry is more bad/specific.
        # For all the others, it's the 0th that we expect.
        jobs = [FakeJob(0, [FakeStatus('FAIL', 'T0', '', hostname='h0'),
                            FakeStatus('FAIL', 'T1', 'bad', hostname='h0')]),
                FakeJob(1, [FakeStatus('ERROR', 'T0', 'err', False, 'h1'),
                            FakeStatus('GOOD', 'T1', '', hostname='h1')]),
                FakeJob(2, [FakeStatus('TEST_NA', 'T0', 'no', hostname='h2')]),
                FakeJob(3, [FakeStatus('FAIL', 'T0', 'broken', hostname='h3')]),
                FakeJob(4, [FakeStatus('ERROR', 'T0', 'gah', True, 'h4')]),
                FakeJob(5, [FakeStatus('GOOD', 'T0', 'Yay', hostname='h5')])]
        # Method under test returns status available right now.
        for job in jobs:
            entries = map(lambda s: s.entry, job.statuses)
            self.afe.run('get_host_queue_entries',
                         job=job.id).AndReturn(entries)
            self.tko.get_status_counts(job=job.id).AndReturn(job.statuses)
        self.mox.ReplayAll()

        results = job_status.gather_per_host_results(self.afe,
                                                     self.tko,
                                                     jobs).values()
        for status in [jobs[0].statuses[1]] + [j.statuses[0] for j in jobs[1:]]:
            self.assertTrue(True in map(status.equals_hostname_record, results))
