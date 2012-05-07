#!/usr/bin/python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for site_utils/build_event.py."""

import datetime, logging, mox, unittest
import build_event, manifest_versions, task


class BuildEventTestBase(mox.MoxTestBase):
    """Base class for BuildEvent unit test classes.

    @var BOARD: faux board.
    """


    BOARD = 'faux_board'


    def setUp(self):
        super(BuildEventTestBase, self).setUp()
        self.mv = self.mox.CreateMock(manifest_versions.ManifestVersions)


    def CreateEvent(self):
        """Return an instance of the BuildEvent subclass being tested."""
        raise NotImplementedError()


    def VetBranchBuilds(self, board, branch_manifests, branch_builds):
        """Assert that branch_builds is derived from branch_manifests.

        @param board: the board to get builds for.
        @param branch_manifests: {(type, milestone): [manifests]}
        @param branch_builds: {type-or-milestone: [build-names]}
        """
        for (type, milestone), manifests in branch_manifests.iteritems():
            builds = []
            if type in task.BARE_BRANCHES:
                builds = branch_builds[type]
                for build in builds:
                    self.assertTrue(build.startswith('%s-%s' % (board, type)))
            else:
                builds = branch_builds[milestone]
                for build in builds:
                    self.assertTrue(build.startswith('%s-release' % board))
            for build, manifest in zip(builds, manifests):
                self.assertTrue('R%s-%s' % (milestone, manifest) in build)


    def doTestGetBranchBuilds(self, board, branch_manifests):
        """Set expectations for and run BuildEvent.GetBranchBuildsForBoard().

        @param board: the board to get builds for.
        @param branch_manifests: {(type, milestone): [manifests]}
        @return per-branch builds; {type-or-milestone: [build-names]}
        """
        head = '1cedcafe'
        self.mv.GetCheckpoint().AndReturn(head)
        self.mv.ManifestsSinceRev(head, board).AndReturn(branch_manifests)
        self.mox.ReplayAll()

        event = self.CreateEvent()
        event.Prepare()
        return event.GetBranchBuildsForBoard(board)


class NewBuildTest(BuildEventTestBase):
    """Unit tests for build_event.NewBuild."""


    def CreateEvent(self):
        return build_event.NewBuild(self.mv, False)


    def testGetBranchBuilds(self):
        """Ensure that we handle the appearance of new branch builds."""
        branch_manifests = {('factory','16'): ['last16'],
                            ('release','17'): ['first17', 'last17']}
        branch_builds = self.doTestGetBranchBuilds(self.BOARD, branch_manifests)
        self.VetBranchBuilds(self.BOARD, branch_manifests, branch_builds)



    def testGetNoBranchBuilds(self):
        """Ensure that we tolerate the appearance of no new branch builds."""
        branch_builds = self.doTestGetBranchBuilds(self.BOARD, {})
        self.assertEquals(branch_builds, {})


    def testShouldHandle(self):
        """Ensure that we suggest Handle() iff new successful builds exist."""
        initial_hash = '1cedcafe'
        expected_hash = 'deadbeef'
        self.mv.GetCheckpoint().AndReturn(initial_hash)
        self.mv.AnyManifestsSinceRev(initial_hash).AndReturn(False)
        self.mv.GetCheckpoint().AndReturn(expected_hash)
        self.mv.AnyManifestsSinceRev(expected_hash).AndReturn(True)
        self.mox.ReplayAll()
        new_build = self.CreateEvent()
        new_build.Prepare()
        self.assertFalse(new_build.ShouldHandle())
        new_build.UpdateCriteria()
        self.assertTrue(new_build.ShouldHandle())


    def testRunThrough(self):
        """Ensure we can run through a couple passes of expected workflow."""
        initial_hash = '1cedcafe'
        expected_hash = 'deadbeef'
        branch_manifests = {('factory','16'): ['last16'],
                            ('release','17'): ['first17', 'last17']}

        # Expect Prepare()
        self.mv.GetCheckpoint().AndReturn(initial_hash)

        # Expect one run through.
        self.mv.AnyManifestsSinceRev(initial_hash).AndReturn(True)
        self.mv.ManifestsSinceRev(initial_hash,
                                  self.BOARD).AndReturn(branch_manifests)
        self.mv.GetCheckpoint().AndReturn(expected_hash)

        # Expect a second run through.
        self.mv.AnyManifestsSinceRev(expected_hash).AndReturn(True)
        self.mv.ManifestsSinceRev(expected_hash,
                                  self.BOARD).AndReturn(branch_manifests)
        self.mox.ReplayAll()

        new_build = self.CreateEvent()

        new_build.Prepare()

        self.assertTrue(new_build.ShouldHandle())
        self.assertTrue(new_build.GetBranchBuildsForBoard(self.BOARD))
        new_build.Handle(None, {}, self.BOARD)
        new_build.UpdateCriteria()

        self.assertTrue(new_build.ShouldHandle())
        self.assertTrue(new_build.GetBranchBuildsForBoard(self.BOARD))
        new_build.Handle(None, {}, self.BOARD)


if __name__ == '__main__':
  unittest.main()
