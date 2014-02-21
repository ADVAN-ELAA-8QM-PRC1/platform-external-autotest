#!/usr/bin/env python
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""XML RPC server for display testing."""

import argparse
import code
import logging
import multiprocessing
import os
import re
import time
import xmlrpclib

import common   # pylint: disable=W0611
from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib.cros import chrome, xmlrpc_server
from autotest_lib.client.cros import constants, sys_power
from Xlib import display, ext, X

EXT_PATH = os.path.join(os.path.dirname(__file__), 'display_test_extension')


class DisplayTestingXmlRpcDelegate(xmlrpc_server.XmlRpcDelegate):
    """XML RPC delegate for display testing."""

    def __init__(self, chrome):
        self._chrome = chrome
        self._browser = chrome.browser

    def get_display_info(self):
        """Gets the display info from Chrome.system.display API.

        @return A dict of display info.
        """
        extension = self._chrome.get_extension(EXT_PATH)
        if not extension:
            raise RuntimeError('Graphics test extension not found')
        extension.ExecuteJavaScript('window.__display_info = null;')
        extension.ExecuteJavaScript(
                "chrome.system.display.getInfo(function(info) {"
                "window.__display_info = info;})")
        utils.wait_for_value(lambda: (
                extension.EvaluateJavaScript("window.__display_info") != None),
                expected_value=True)
        return extension.EvaluateJavaScript("window.__display_info")

    def get_resolution(self, output):
        """Gets the resolution of the specified output.

        @param output: The output name as a string.

        @return The resolution of output as a tuple (width, height,
            fb_offset_x, fb_offset_y) of ints.
        """
        regexp = re.compile(
                r'^([-A-Za-z0-9]+)\s+connected\s+(\d+)x(\d+)\+(\d+)\+(\d+)',
                re.M)
        match = regexp.findall(utils.call_xrandr())
        for m in match:
            if m[0] == output:
                return (int(m[1]), int(m[2]), int(m[3]), int(m[4]))
        return (0, 0, 0, 0)

    def take_tab_screenshot(self, url_pattern, output_suffix):
        """Takes a screenshot of the tab specified by the given url pattern.

        The captured screenshot is saved to:
            /tmp/screenshot_<output_suffix>_<last_part_of_url>.png

        @param url_pattern: A string of url pattern used to search for tabs.
        @param output_suffix: A suffix appended to the file name of captured
                PNG image.
        """
        if not url_pattern:
            # If no URL pattern is provided, defaults to capture all the tabs
            # that show PNG images.
            url_pattern = '.png'

        tabs = self._browser.tabs
        screenshots = []
        for i in xrange(0, len(tabs)):
            if url_pattern in tabs[i].url:
                screenshots.append((tabs[i].url, tabs[i].Screenshot(timeout=5)))

        output_file = ('/tmp/screenshot_%s_%%s.png' % output_suffix)
        for url, screenshot in screenshots:
            image_filename = os.path.splitext(url.rsplit('/', 1)[-1])[0]
            screenshot.WriteFile(output_file % image_filename)
        return True

    def toggle_mirrored(self):
        """Toggles mirrored.

        Emulates L_Ctrl + Maximize in X server to toggle mirrored.
        """
        L_CTRL_KEYCODE = 37
        MAXIMIZE_KEYCODE = 70
        xdisplay = display.Display()
        root_window = xdisplay.screen().root
        ext.xtest.fake_input(root_window, X.KeyPress, L_CTRL_KEYCODE)
        ext.xtest.fake_input(root_window, X.KeyPress, MAXIMIZE_KEYCODE)
        ext.xtest.fake_input(root_window, X.KeyRelease, MAXIMIZE_KEYCODE)
        ext.xtest.fake_input(root_window, X.KeyRelease, L_CTRL_KEYCODE)
        xdisplay.sync()
        return True

    def set_mirrored(self, is_mirrored):
        """Sets mirrored mode.

        @param is_mirrored: True or False to indicate mirrored state.
        """
        def _is_mirrored_enabled():
            return bool(self.get_display_info()[0]['mirroringSourceId'])

        retries = 3
        while _is_mirrored_enabled() != is_mirrored and retries > 0:
            self.toggle_mirrored()
            time.sleep(3)
            retries -= 1
        return _is_mirrored_enabled() == is_mirrored

    def suspend_resume(self, suspend_time=10):
        """Suspends the DUT for a given time in second.

        @param suspend_time: Suspend time in second.
        """
        sys_power.do_suspend(suspend_time)
        return True

    def suspend_resume_bg(self, suspend_time=10):
        """Suspends the DUT for a given time in second in the background.

        @param suspend_time: Suspend time in second.
        """
        process = multiprocessing.Process(target=self.suspend_resume,
                                          args=(suspend_time,))
        process.start()
        return True

    def get_ext_connector_name(self):
        """Gets the name of the external output connector.

        @return The external output connector name as a string.
        """
        xrandr_output = utils.get_xrandr_output_state()
        for output in xrandr_output.iterkeys():
            if (output.startswith('HDMI') or
                output.startswith('DP') or
                output.startswith('DVI')):
                return output
        return False

    def wait_output_connected(self, output):
        """Wait for output to connect.

        @param output: The output name as a string.

        @return: True if output is connected; False otherwise.
        """
        def _is_connected(output):
            xrandr_output = utils.get_xrandr_output_state()
            if output not in xrandr_output:
                return False
            return xrandr_output[output]
        return utils.wait_for_value(lambda: _is_connected(output),
                                    expected_value=True)

    def load_url(self, url):
        """Loads the given url in a new tab.

        @param url: The url to load as a string.
        """
        tab = self._browser.tabs.New()
        tab.Navigate(url)
        tab.Activate()
        return True

    def close_tab(self, index=-1):
        """Closes the tab of the given index.

        @param index: The tab index to close. Defaults to the last tab.
        """
        self._browser.tabs[index].Close()
        return True

    def reconnect_output(self, output):
        """Reconnects output.

        @param output: The output name as a string.
        """
        utils.set_xrandr_output(output, False)
        utils.set_xrandr_output(output, True)
        return True


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--debug', action='store_true', required=False,
                        help=('create a debug console with a ServerProxy "s" '
                              'connecting to the XML RPC sever at localhost'))
    args = parser.parse_args()

    if args.debug:
        s = xmlrpclib.ServerProxy('http://localhost:%d' %
                                  constants.DISPLAY_TESTING_XMLRPC_SERVER_PORT)
        code.interact(local=locals())
    else:
        logging.basicConfig(level=logging.DEBUG)
        logging.debug('display_xmlrpc_server main...')

        os.environ['DISPLAY'] = ':0.0'
        os.environ['XAUTHORITY'] = '/home/chronos/.Xauthority'

        extra_browser_args = ['--enable-gpu-benchmarking']

        with chrome.Chrome(extension_paths=[EXT_PATH],
                           extra_browser_args=extra_browser_args) as cr:
            server = xmlrpc_server.XmlRpcServer(
                    'localhost', constants.DISPLAY_TESTING_XMLRPC_SERVER_PORT)
            server.register_delegate(DisplayTestingXmlRpcDelegate(cr))
            server.run()
