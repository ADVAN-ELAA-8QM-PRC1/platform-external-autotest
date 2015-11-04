# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re

from autotest_lib.client.bin import test, utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros import chrome
from telemetry.core import exceptions

class security_SandboxStatus(test.test):
    """Verify sandbox status."""
    version = 1


    def _EvaluateJavaScript(self, js):
        '''Evaluates js, returns None if an exception was thrown.'''

        try:
            return self._tab.EvaluateJavaScript(js)
        except exceptions.EvaluateException:
            return None


    def _CheckAdequatelySandboxed(self):
        '''Checks that chrome:///sandbox shows "You are adequately sandboxed."'''
        sandbox_good_js = "document.getElementsByTagName('p')[0].textContent"
        sandbox_good = utils.poll_for_condition(
                lambda: self._EvaluateJavaScript(sandbox_good_js),
                exception=error.TestError(
                       'Failed to evaluate in chrome://sandbox "%s"'
                        % sandbox_good_js),
                timeout=30)
        if not re.match('You are adequately sandboxed.', sandbox_good):
            raise error.TestFail('Could not find "You\'re adequately '
                                 'sandboxed." in chrome://sandbox')


    # TODO(jorgelo): This breaks with changes to the layout of chrome://gpu.
    # Make it more robust. crbug.com/549681.
    def _CheckGPUCell(self, table, row, cell, content):
        '''Checks the content of a cell in chrome://gpu.'''

        gpu_js = ("document.getElementsByTagName('table')"
                  "[%d].rows[%d].cells[%d].textContent" % (table, row, cell))
        try:
            res = utils.poll_for_condition(
                    lambda: self._EvaluateJavaScript(gpu_js),
                    timeout=30)
        except utils.TimeoutError:
            raise error.TestError('Failed to evaluate in chrome://gpu "%s"'
                                  % gpu_js)

        return res.find(content) != -1


    def run_once(self):
        '''Open various sandbox-related pages and test that we are sandboxed.'''
        with chrome.Chrome() as cr:
            self._tab = cr.browser.tabs[0]
            self._tab.Navigate('chrome://sandbox')
            self._CheckAdequatelySandboxed()

            self._tab.Navigate('chrome://gpu')

            if not self._CheckGPUCell(2, 2, 0, 'Sandboxed'):
                raise error.TestError('Could not locate "Sandboxed" row in table')

            if not self._CheckGPUCell(2, 2, 1, 'true'):
                raise error.TestError('GPU not sandboxed')
