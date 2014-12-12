# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import time

from autotest_lib.client.cros.chameleon import screen_utility_factory


class ChameleonScreenTest(object):
    """Utility to test the screen between Chameleon and CrOS.

    This class contains the screen-related testing operations.

    """

    def __init__(self, chameleon_port, display_facade, output_dir):
        """Initializes the ScreenUtilityFactory objects."""
        self._display_facade = display_facade
        factory = screen_utility_factory.ScreenUtilityFactory(
                chameleon_port, display_facade)
        self._resolution_comparer = factory.create_resolution_comparer()
        self._screen_comparer = factory.create_screen_comparer(output_dir)
        self._mirror_comparer = factory.create_mirror_comparer(output_dir)


    def test_resolution(self, expected_resolution):
        """Tests if the resolution of Chameleon matches with the one of CrOS.

        @param expected_resolution: A tuple (width, height) for the expected
                                    resolution.
        @return: None if the check passes; otherwise, a string of error message.
        """
        return self._resolution_comparer.compare(expected_resolution)


    def test_screen(self, expected_resolution, test_mirrored=None,
                    error_list=None):
        """Tests if the screen of Chameleon matches with the one of CrOS.

        @param expected_resolution: A tuple (width, height) for the expected
                                    resolution.
        @param test_mirrored: True to test mirrored mode. False not to. None
                              to test mirrored mode iff the current mode is
                              mirrored.
        @param error_list: A list to append the error message to or None.
        @return: None if the check passes; otherwise, a string of error message.
        """
        if test_mirrored is None:
            test_mirrored = self._display_facade.is_mirrored_enabled()

        error = self._resolution_comparer.compare(expected_resolution)
        if not error:
            # Do two screen comparisons with and without hiding cursor, to
            # work-around some devices still showing cursor on CrOS FB.
            # TODO: Remove this work-around once crosbug/p/34524 got fixed.
            error = self._screen_comparer.compare()
            if error:
                logging.info('Hide cursor and do screen comparison again...')
                self._display_facade.hide_cursor()
                error = self._screen_comparer.compare()
        if not error and test_mirrored:
            error = self._mirror_comparer.compare()
        if error and error_list is not None:
            error_list.append(error)
        return error


    def load_test_image(self, image_size, calibration_image_setup_time=10):
        """Loads calibration image on the CrOS with logging

        @param image_size: A tuple (width, height) conforms the resolution.
        @param calibration_image_setup_time: Time to wait for the full screen
                bubble and the external display detecting notation to disappear.
        """
        self._display_facade.load_calibration_image(image_size)
        logging.info('Waiting for calibration image to stabilize...')
        time.sleep(calibration_image_setup_time)


    def unload_test_image(self):
        """Close the tab in browser to unload test image."""
        self._display_facade.close_tab()


    def test_screen_with_image(self, expected_resolution, test_mirrored=None,
                               error_list=None, retry_count=2):
        """Tests the screen with image loaded.

        @param expected_resolution: A tuple (width, height) for the expected
                                    resolution.
        @param test_mirrored: True to test mirrored mode. False not to. None
                              to test mirrored mode iff the current mode is
                              mirrored.
        @param error_list: A list to append the error message to or None.
        @param retry_count: A count to retry the screen test.
        @return: None if the check passes; otherwise, a string of error message.
        """
        if test_mirrored is None:
            test_mirrored = self._display_facade.is_mirrored_enabled()

        # TODO(tingyuan): Check test_image is keeping full-screen.
        if test_mirrored:
            test_image_size = self._display_facade.get_internal_resolution()
        else:
            test_image_size = self._display_facade.get_external_resolution()

        while retry_count:
            retry_count = retry_count - 1
            try:
                self.load_test_image(test_image_size)
                error = self.test_screen(expected_resolution, test_mirrored)
                if error is None:
                    return error
                elif retry_count == 0:
                    error_list.append(error)
                    return error
                else:
                    logging.info('Retry screen comparison again...')
            finally:
                self.unload_test_image()


    def check_external_display_connected(self, expected_display,
                                         error_list=None):
        """Checks the given external display connected.

        @param expected_display: Name of the expected display or False
                if no external display is expected.
        @param error_list: A list to append the error message to or None.
        @return: None if the check passes; otherwise, a string of error message.
        """
        error = None
        if not self._display_facade.wait_external_display_connected(
                expected_display):
            error = 'Waited for display %s but timed out' % expected_display

        if error and error_list is not None:
            logging.error(error)
            error_list.append(error)
        return error
