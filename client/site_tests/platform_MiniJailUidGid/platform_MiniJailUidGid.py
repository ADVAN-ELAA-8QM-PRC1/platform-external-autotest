# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
import re

from autotest_lib.client.bin import test
from autotest_lib.client.common_lib import error, utils

class platform_MiniJailUidGid(test.test):
    version = 1
    preserve_srcdir = True

    def setup(self):
        os.chdir(self.srcdir)
        utils.make('clean')
        utils.make('all')


    def __run_cmd(self, cmd):
        result = utils.system_output(cmd, retain_output=True,
                                     ignore_status=True)
        return result

    def test_jail(self, jailargs, testargs, message):
        check_cmd = (os.path.join(self.bindir, 'platform_MiniJailUidGid') +
                     ' ' + testargs)
        cmd = ('/sbin/minijail %s -- %s' % (jailargs, check_cmd))
        result = self.__run_cmd(cmd)
        succeed_pattern = re.compile(r"SUCCEED: (.+)")
        success = succeed_pattern.findall(result)
        if len(success) == 0:
          raise error.TestFail(message)

    def run_once(self):
        # Check that --uid [number] works
        # @TODO(fes): The autotest framework seems to preserve the ownership
        # from the source, so thest tests fail unless the bindir is changed to
        # be owned by root but read/execute by anyone
        self.__run_cmd(('chown -R root:root ' + self.bindir));
        self.__run_cmd(('chmod 755 ' + self.bindir));

        self.test_jail('--uid=1000', '--checkUid=1000', '--uid=int failed.')
        self.test_jail('--gid=1000', '--checkGid=1000', '--gid=int failed.')
        self.test_jail('--uid=chronos', '--checkUid=1000', '--uid=str failed.')
        self.test_jail('--gid=chronos', '--checkGid=1000', '--gid=str failed.')
