# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from autotest_lib.client.bin import test
from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros import chrome
from telemetry.core import exceptions

SANDBOXES = [u'SUID Sandbox',
             u'\xa0\xa0PID namespaces',
             u'\xa0\xa0Network namespaces',
             u'Seccomp-BPF sandbox']

class security_SandboxStatusTelemetry(test.test):
    """Verify sandbox status."""
    version = 1


    def _TableEntry(self, row, column):
        '''Fetches table cell text content corresponding to row, column.'''

        table_js = ("document.getElementsByTagName('table')[0]."
                    "rows[%d].cells[%d].textContent" % (row, column))
        try:
            return self._tab.EvaluateJavaScript(table_js)
        except exceptions.EvaluateException:
            raise error.TestFail('Failed to evaluate in chrome://sandbox %s'
                                 % table_js)


    def _CheckRowName(self, row, expected_name):
        '''Ensures the name of the row is as we expect.'''

        actual_name = self._TableEntry(row, 0)
        if expected_name != actual_name:
            raise error.TestFail('Expected row %d to be %s, found %s',
                                 expected_name, actual_name)


    def _CheckRowNames(self, expected_names):
        for row in range(len(expected_names)):
            self._CheckRowName(row, expected_names[row])


    def _CheckRowValues(self, num_rows):
        '''Ensures all sandboxes are on.'''

        for row in range(num_rows):
            value = self._TableEntry(row, 1)
            if value != "Yes":
                name = self._TableEntry(row, 0)
                raise error.TestFail('%s enabled = %s', name, value)


    def _CheckGPUCell(self, cell, content, error_msg):
        '''Checks the content of the cells in the GPU sandbox row.'''

        gpu_js = ("document.getElementsByTagName('table')"
                  "[1].rows[1].cells[%d].textContent" % cell)
        try:
            res = self._tab.EvaluateJavaScript(gpu_js)
        except exceptions.EvaluateException:
            raise error.TestFail('Failed to evaluate in chrome://gpu %s'
                                 % gpu_js)
        if res.find(content) == -1:
            raise error.TestFail(error_msg)


    def run_once(self):
        with chrome.Chrome(logged_in=False) as cr:
            self._tab = cr.browser.tabs[0]
            self._tab.Navigate('chrome://sandbox')
            self._CheckRowNames(SANDBOXES)
            self._CheckRowValues(len(SANDBOXES))

            self._tab.Navigate('chrome://gpu')
            self._CheckGPUCell(0, 'Sandboxed',
                               'Could not locate "Sandboxed" row in table')
            self._CheckGPUCell(1, 'true', 'GPU not sandboxed')

