# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging, os
from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros import constants as chromeos_constants
from autotest_lib.client.cros import cros_logging, cros_ui_test
from autotest_lib.client.cros import login

_SESSION_MANAGER_DEST='org.chromium.SessionManager'
_SESSION_MANAGER_OBJECT='org.chromium.SessionManagerInterface'
_SESSION_MANAGER_PATH='/org/chromium/SessionManager'

class login_DBusCalls(cros_ui_test.UITest):
    version = 1


    def initialize(self, creds = '$default', **dargs):
        cros_ui_test.UITest.initialize(self, creds, **dargs)


    def _call_session_manager_method(self, method, user='chronos'):
        """Call session manager dbus method as given user.

        We assume the method exists and succeeds.

        Args:
            method: name of method
            user: system user to run as
        Returns:
            None
        """
        utils.system('su %s -c \'dbus-send --system --type=method_call '
                     '--print-reply --dest=%s %s %s.%s\'' %
                     (user, _SESSION_MANAGER_DEST, _SESSION_MANAGER_PATH,
                      _SESSION_MANAGER_OBJECT, method))


    def _test_restart_entd(self):
        """Test the RestartEntd method."""
        message_log = cros_logging.LogReader()
        message_log.set_start_by_current()
        ui_log = cros_logging.LogReader(chromeos_constants.UI_LOG)
        ui_log.set_start_by_current()
        # Make sure we can call RestartEntd from user chronos.
        self._call_session_manager_method('RestartEntd')
        try:
            utils.poll_for_condition(
                lambda: ui_log.can_find('Restart was successful'),
                timeout=30,
                exception=error.TestFail(
                    'Found no ui log message about attempting to restart entd'))
        finally:
            logging.debug('UI log from RestartEntd: ' +
                          ui_log.get_logs())

        grep_bait = 'entdwife.sh: Username: ' + self.username
        try:
            utils.poll_for_condition(
                lambda: message_log.can_find(grep_bait),
                timeout=30,
                exception=error.TestFail('Did not find %s in message log' %
                                         grep_bait))
        finally:
            logging.debug('Message log from RestartEntd: ' +
                          message_log.get_logs())


    def run_once(self):
        login.wait_for_cryptohome()
        self._test_restart_entd()
