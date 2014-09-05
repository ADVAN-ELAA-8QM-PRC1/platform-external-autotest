# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import logging
import shutil
import time

from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros import chrome
from autotest_lib.client.cros import touch_playback_test_base


class touch_MouseScroll(touch_playback_test_base.touch_playback_test_base):
    """Plays back mouse scrolls and checks for correct page movement."""
    version = 1

    _DEFAULT_SCROLL = 5000
    _MOUSE_DESCRIPTION = 'amazon_mouse.prop'
    _EXPECTED_VALUE_1 = 16 # Expected value of one scroll wheel turn.
    _EXPECTED_DIRECTION = {'down': 1, 'up': -1}
    _TOLLERANCE = 4 # Fast scroll should go at least X times slow scroll.

    def _get_page_position(self):
        """Return current scroll position of page."""
        return self._tab.EvaluateJavaScript('document.body.scrollTop')

    def _reset_page_position(self):
        """Reset page position to default."""
        self._tab.ExecuteJavaScript('window.scrollTo(0, %d)'
                                    % self._DEFAULT_SCROLL)
        if self._get_page_position() != self._DEFAULT_SCROLL:
            raise error.TestError('Could not set default scroll value!')

    def _get_scroll_delta(self, name, expected_direction):
        """Playback the given test and return the amount the page moved.

        @param name: name of test filename.
        @param expected_direction: an integer that is + for down and - for up.

        @raise: TestFail if scrolling did not occur in expected direction.

        """
        self._reset_page_position()
        self._playback(self._dut_paths[name], touch_type='mouse')
        time.sleep(2) # Sleep while playback occurs.
        delta = self._get_page_position() - self._DEFAULT_SCROLL
        logging.info('Test %s: saw scroll delta of %d.  Expected direction %d.',
                     name, delta, expected_direction)

        if delta == 0:
            raise error.TestFail('No scrolling occured (%s)!' % name)
        if delta * expected_direction < 0:
            raise error.TestFail('Scroll was in wrong direction!  Delta '
                                 'for %s was %d.' % (name, delta))

        return delta

    def _verify_single_tick(self, direction):
        """Verify that using the scroll wheel goes the right distance.

        Expects a file named direction + '_1'.

        """
        name = direction + '_1'
        expected_direction = self._EXPECTED_DIRECTION[direction]
        expected_value = self._EXPECTED_VALUE_1 * expected_direction
        delta = self._get_scroll_delta(name, expected_direction)

        if delta != expected_value:
            raise error.TestFail('One tick scroll was wrong size: actual=%d, '
                                 'expected=%d.' % (delta, expected_value))

    def _verify_fast_vs_slow(self, direction):
        """Verify that fast scrolling goes farther than slow scrolling.

        Expects files named direction + '_slow' and direction + '_fast'.

        """
        slow = direction + '_slow'
        fast = direction + '_fast'
        expected = self._EXPECTED_DIRECTION[direction]

        slow_delta = self._get_scroll_delta(slow, expected)
        fast_delta = self._get_scroll_delta(fast, expected)

        if abs(fast_delta) < self._TOLLERANCE * abs(slow_delta):
            raise error.TestFail('Fast scroll should be much farther than '
                                 'slow! (%s).  %d vs. %d.' %
                                  (direction, slow_delta, fast_delta))

    def warmup(self):
        # Copy device file to DUT, if available.  Deleted during cleanup.
        self._copied_files = []
        self._mouse_file = os.path.join('/tmp', self._MOUSE_DESCRIPTION)
        self._copied_files.append(self._mouse_file)
        shutil.copyfile(os.path.join(self.bindir, self._MOUSE_DESCRIPTION),
                        self._mouse_file)

        # Initiate super with property file for emulation.
        super(touch_MouseScroll, self).warmup(mouse_props=self._mouse_file)

    def run_once(self):
        """Entry point of this test."""
        # Raise error if no mouse detected.
        if not self._has_mouse:
            raise error.TestError('No USB mouse found on this device.')

        # Copy playback files to DUT.  Deleted during cleanup.
        self._dut_paths = {}
        gestures_dir = os.path.join(self.bindir, 'gestures')
        for filename in os.listdir(gestures_dir):
            dut_path = os.path.join('/tmp', filename)
            host_path = os.path.join(gestures_dir, filename)
            self._copied_files.append(dut_path)
            self._dut_paths[filename] = dut_path
            shutil.copyfile(host_path, dut_path)

        with chrome.Chrome() as cr:
            # Open test page.
            cr.browser.SetHTTPServerDirectories(self.bindir)
            self._tab = cr.browser.tabs[0]
            self._tab.Navigate(cr.browser.http_server.UrlOf(
                    os.path.join(self.bindir, 'long_page.html')))
            self._tab.WaitForDocumentReadyStateToBeComplete()

            # Test
            for direction in ['down', 'up']:
                self._verify_single_tick(direction)
                self._verify_fast_vs_slow(direction)

    def cleanup(self):
        # Call parent cleanup to close mouse emulation
        super(touch_MouseScroll, self).cleanup()

        # Remove files, if present.
        for path in self._copied_files:
            try:
                os.remove(path)
            except OSError:
                pass


