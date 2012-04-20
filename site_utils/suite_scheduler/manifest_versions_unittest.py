#!/usr/bin/python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for site_utils/manifest_versions.py."""

import logging, mox, os, unittest

from autotest_lib.client.common_lib import utils
import manifest_versions


class ManifestVersionsTest(mox.MoxTestBase):
    """Unit tests for ManifestVersions.

    @var _BRANCHES: canned branches that should parse out of the below.
    @var _MANIFESTS_STRING: canned (string) list of manifest file paths.
    """

    _BRANCHES = [('release', '18'), ('release', '19'), ('release', '20'),
                 ('factory', '20'), ('firmware', '20')]
    _MANIFESTS_STRING = """
build-name/x86-alex-release-group/pass/20/2057.0.9.xml


build-name/x86-alex-release-group/pass/20/2057.0.10.xml


build-name/x86-alex-release-group/pass/20/2054.0.0.xml


build-name/x86-alex-release/pass/18/1660.103.0.xml


build-name/x86-alex-release-group/pass/20/2051.0.0.xml


build-name/x86-alex-firmware/pass/20/2048.1.1.xml


build-name/x86-alex-release/pass/19/2046.3.0.xml


build-name/x86-alex-release-group/pass/20/2050.0.0.xml


build-name/x86-alex-release-group/pass/20/2048.0.0.xml


build-name/x86-alex-factory/pass/20/2048.1.0.xml
"""


    def setUp(self):
        super(ManifestVersionsTest, self).setUp()
        self.mv = manifest_versions.ManifestVersions()


    def testInitialize(self):
        """Ensure we can initialize a ManifestVersions."""
        self.mox.StubOutWithMock(self.mv, '_Clone')
        self.mv._Clone()
        self.mox.ReplayAll()
        self.mv.Initialize()


    def testGlobs(self):
        """Ensure that we expand globs correctly."""
        desired_paths = ['one/path', 'two/path', 'three/path']
        tempdir = self.mv._tempdir.name
        for path in desired_paths:
            os.makedirs(os.path.join(tempdir, path))
        for path in self.mv._ExpandGlobMinusPrefix(tempdir, '*/path'):
            self.assertTrue(path in desired_paths)


    def testAnyManifestsSinceRev(self):
        """Ensure we can tell if builds have succeeded since a given rev."""
        rev = 'rev'
        self.mox.StubOutWithMock(utils, 'system_output')
        utils.system_output(
            mox.And(mox.StrContains('log'),
                    mox.StrContains(rev))).MultipleTimes().AndReturn(
                        self._MANIFESTS_STRING)
        self.mox.ReplayAll()
        self.assertTrue(self.mv.AnyManifestsSinceRev(rev))


    def testNoManifestsSinceRev(self):
        """Ensure we can tell if no builds have succeeded since a given rev."""
        rev = 'rev'
        self.mox.StubOutWithMock(utils, 'system_output')
        utils.system_output(
            mox.And(mox.StrContains('log'),
                    mox.StrContains(rev))).MultipleTimes().AndReturn(' ')
        self.mox.ReplayAll()
        self.assertFalse(self.mv.AnyManifestsSinceRev(rev))


    def testManifestsSinceDays(self):
        """Ensure we can get manifests for a board since N days ago."""
        days_ago = 7
        board = 'x86-alex'
        self.mox.StubOutWithMock(utils, 'system_output')
        utils.system_output(
            mox.StrContains('log')).MultipleTimes().AndReturn(
                self._MANIFESTS_STRING)
        self.mox.ReplayAll()
        br_man = self.mv.ManifestsSinceDays(days_ago, board)
        for pair in br_man.keys():
            self.assertTrue(pair, self._BRANCHES)
        for manifest_list in br_man.itervalues():
            self.assertTrue(manifest_list)
        self.assertEquals(br_man[('release', '20')][-1], '2057.0.10')


    def testNoManifestsSinceDays(self):
        """Ensure we can deal with no manifests since N days ago."""
        days_ago = 7
        board = 'x86-alex'
        self.mox.StubOutWithMock(utils, 'system_output')
        utils.system_output(mox.StrContains('log')).AndReturn([])
        self.mox.ReplayAll()
        br_man = self.mv.ManifestsSinceDays(days_ago, board)
        self.assertEquals(br_man, {})


    def testManifestsSinceDaysExplodes(self):
        """Ensure we handle failures in querying manifests."""
        days_ago = 7
        board = 'x86-alex'
        self.mox.StubOutWithMock(utils, 'system_output')
        utils.system_output(mox.StrContains('log')).AndRaise(
            manifest_versions.QueryException())
        self.mox.ReplayAll()
        self.assertRaises(manifest_versions.QueryException,
                          self.mv.ManifestsSinceDays, days_ago, board)


if __name__ == '__main__':
    unittest.main()
