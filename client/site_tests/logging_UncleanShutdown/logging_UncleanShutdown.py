# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging, os, time
from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros import constants, cros_logging, cros_ui_test

_CRASH_PATH = '/sbin/crash_reporter'
_UNCLEAN_SHUTDOWN_MESSAGE = 'Last shutdown was not clean'

class logging_UncleanShutdown(cros_ui_test.UITest):
    version = 1
    auto_login = False


    def run_once(self):
        if not os.path.exists(constants.PENDING_SHUTDOWN_PATH):
            raise error.TestFail('pending shutdown file, %s, not found' %
                                 constants.PENDING_SHUTDOWN_PATH)

        log_reader = cros_logging.LogReader()
        log_reader.set_start_by_reboot(-1)

        if log_reader.can_find(_UNCLEAN_SHUTDOWN_MESSAGE):
            raise error.TestFail(
                'Unexpectedly detected unclean shutdown during boot')

        if os.path.exists(constants.UNCLEAN_SHUTDOWN_DETECTED_PATH):
            raise error.TestFail('an unclean shutdown file was detected')

        # Log in and out twice to make sure that doesn't cause
        # an unclean shutdown message.
        for i in range(2):
            self.login()
            time.sleep(5)
            self.logout()
            time.sleep(5)

        if log_reader.can_find(_UNCLEAN_SHUTDOWN_MESSAGE):
            logging.info('Unexpected logs: ', log_reader.get_logs())
            raise error.TestFail(
                'Unexpectedly detected kernel crash during login/logout')

        if os.path.exists(constants.UNCLEAN_SHUTDOWN_DETECTED_PATH):
            raise error.TestFail('an unclean shutdown file was generated')

        # Run the shutdown and verify it does not complain of unclean
        # shutdown.

        log_reader.set_start_by_current()
        utils.system('%s --clean_shutdown' % _CRASH_PATH)
        utils.system('%s --init' % _CRASH_PATH)

        if (log_reader.can_find(_UNCLEAN_SHUTDOWN_MESSAGE) or
            os.path.exists(constants.UNCLEAN_SHUTDOWN_DETECTED_PATH)):
            raise error.TestFail('Incorrectly signalled unclean shutdown')

        # Now simulate an unclean shutdown and test handling.

        log_reader.set_start_by_current()
        utils.system('%s --init' % _CRASH_PATH)

        if not log_reader.can_find(_UNCLEAN_SHUTDOWN_MESSAGE):
            raise error.TestFail('Did not signal unclean shutdown when should')

        if not os.path.exists(constants.UNCLEAN_SHUTDOWN_DETECTED_PATH):
            raise error.TestFail('Did not touch unclean shutdown file')

        os.remove(constants.UNCLEAN_SHUTDOWN_DETECTED_PATH)
