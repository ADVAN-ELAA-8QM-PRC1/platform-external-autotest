# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import itertools
import os
import logging
import time

from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros import chrome
from autotest_lib.client.cros import touch_playback_test_base


class touch_TapSettings(touch_playback_test_base.touch_playback_test_base):
    """Toggles tap-to-click and tap dragging settings to ensure correctness."""
    version = 1

    _test_timeout = 3 # Number of seconds the test will wait for a click.

    def _check_for_click(self, expected):
        """Playback and check whether tap-to-click occurred.  Fail if needed.

        @param expected: True if clicking should happen, else False.
        @raises: TestFail if actual value does not match expected.

        """
        expected_count = 1 if expected else 0
        self._reload_page()
        self._playback(filepath=self._click_filepath)
        time.sleep(self._test_timeout)
        actual_count = int(self._tab.EvaluateJavaScript('clickCount'))
        if actual_count is not expected_count:
            raise error.TestFail('Expected clicks=%s, actual=%s.'
                                 % (expected_count, actual_count))


    def _check_for_drag(self, expected):
        """Playback and check whether tap dragging occurred.  Fail if needed.

        @param expected: True if dragging should happen, else False.
        @raises: TestFail if actual value does not match expected.

        """
        self._reload_page()
        self._playback(filepath=self._drag_filepath)
        time.sleep(self._test_timeout)
        actual = self._tab.EvaluateJavaScript('movementOccurred')
        if actual is not expected:
            raise error.TestFail('Tap dragging movement was %s; expected %s.'
                                 % (actual, expected))


    def run_once(self):
        """Entry point of this test."""

        # Check if playback files are available on DUT to run test.
        device = utils.get_board()
        gest_dir = os.path.join(self.bindir, 'gestures')
        tap_click_file = '%s_tap_click' % device
        tap_drag_file = '%s_tap_drag' % device
        self._click_filepath = os.path.join(gest_dir, tap_click_file)
        self._drag_filepath = os.path.join(gest_dir, tap_drag_file)
        if not (os.path.exists(self._click_filepath) and
                os.path.exists (self._drag_filepath)):
            logging.info('Missing gesture files, Aborting test')
            return

        # Raise error if no touchpad detected.
        if not self._has_touchpad:
            raise error.TestFail('No touchpad found on this %d' % device)

        # Log in and start test.
        with chrome.Chrome(autotest_ext=True) as cr:
            # Pass in the autotest extension.
            self._set_autotest_ext(cr.autotest_ext)

            # Open test page.
            cr.browser.SetHTTPServerDirectories(self.bindir)
            self._tab = cr.browser.tabs[0]
            self._tab.Navigate(cr.browser.http_server.UrlOf(
                    os.path.join(self.bindir, 'test_page.html')))
            self._tab.WaitForDocumentReadyStateToBeComplete()

            # Check default setting values.
            logging.info('Checking for default setting values.')
            self._check_for_click(True)
            self._check_for_drag(False)

            # Toggle settings in all combinations and check.
            options = [True, False]
            option_pairs = itertools.product(options, options)
            for (click_value, drag_value) in option_pairs:
                self._set_tap_to_click(click_value)
                self._set_tap_dragging(drag_value)
                self._check_for_click(click_value)
                self._check_for_drag(click_value and drag_value)
