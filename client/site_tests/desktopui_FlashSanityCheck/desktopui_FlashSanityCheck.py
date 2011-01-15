# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


import logging, re, time
from autotest_lib.client.bin import test, utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros import cros_logging, cros_ui

class desktopui_FlashSanityCheck(test.test):
    version = 1


    def run_once(self, time_to_wait=25):
        # take a snapshot from /var/log/messages.
        self._log_reader = cros_logging.LogReader()
        self._log_reader.set_start_by_current()

        # open browser to youtube.com.
        session = cros_ui.ChromeSession('http://www.youtube.com')
        # wait some time till the webpage got fully loaded.
        time.sleep(time_to_wait)
        session.close()
        # Question: do we need to test with other popular flash websites?

        # any better pattern matching?
        if self._log_reader.can_find(' Received crash notification for '):
            # well, there is a crash.
            raise error.TestFail('Browser crashed during test.')
