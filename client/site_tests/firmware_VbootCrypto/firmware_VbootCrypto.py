# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os

from autotest_lib.client.bin import test, utils
from autotest_lib.client.common_lib import error

class firmware_VbootCrypto(test.test):
    """
    Tests for correctness of verified boot reference crypto implementation.
    """
    version = 1
    preserve_srcdir = True

    def setup(self):
        os.chdir(self.srcdir)
        utils.system('make clean')
        utils.system('make all')


    def __sha_test(self):
        sha_test_cmd = os.path.join(self.bindir, "sha_tests")
        return_code = utils.system(sha_test_cmd, ignore_status = True)
        if return_code == 255:
            return False
        if return_code == 1:
            raise error.TestError("SHA Test Error")
        return True


    def run_once(self):
        success = self.__sha_test()
        if not success:
            raise error.TestFail("SHA Test Failed")
