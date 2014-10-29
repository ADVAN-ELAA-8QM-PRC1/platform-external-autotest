# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import tempfile

from PIL import Image

from autotest_lib.client.cros.multimedia.display_helper import DisplayInfo


class DisplayClient(object):
    """DisplayClient is a layer to control display logic over a remote DUT.

    The Autotest host object representing the remote DUT, passed to this
    class on initialization, can be accessed from its _client property.

    """
    def __init__(self, host, multimedia_client_connection):
        """Construct a DisplayClient.

        @param host: Host object representing a remote host.
        @param multimedia_client_connection: MultimediaClientConnection object.
        """
        self._client = host
        self._connection = multimedia_client_connection


    @property
    def _display_proxy(self):
        """Gets the proxy to DUT display utility.

        @return XML RPC proxy to DUT display utility.
        """
        return self._connection.xmlrpc_proxy.display


    def connect(self):
        """Connects the XML-RPC proxy on the client again."""
        # TODO(waihong): Move this method to a better place.
        self._connection.connect()


    def get_external_connector_name(self):
        """Gets the name of the external output connector.

        @return The external output connector name as a string; None if nothing
                is connected.
        """
        result = self._display_proxy.get_external_connector_name()
        return result if result else None


    def get_internal_connector_name(self):
        """Gets the name of the internal output connector.

        @return The internal output connector name as a string.
        """
        return self._display_proxy.get_internal_connector_name()


    def load_calibration_image(self, resolution):
        """Load a full screen calibration image from the HTTP server.

        @param resolution: A tuple (width, height) of resolution.
        """
        self._display_proxy.load_calibration_image(resolution)


    def close_tab(self, index=-1):
        """Closes the tab of the given index.

        @param index: The tab index to close. Defaults to the last tab.
        """
        return self._display_proxy.close_tab(index)


    def is_mirrored_enabled(self):
        """Checks the mirrored state.

        @return True if mirrored mode is enabled.
        """
        return self._display_proxy.is_mirrored_enabled()


    def set_mirrored(self, is_mirrored):
        """Sets mirrored mode.

        @param is_mirrored: True or False to indicate mirrored state.
        """
        return self._display_proxy.set_mirrored(is_mirrored)


    def suspend_resume(self, suspend_time=10):
        """Suspends the DUT for a given time in second.

        @param suspend_time: Suspend time in second, default: 10s.
        """
        # TODO(waihong): Use other general API instead of this RPC.
        return self._display_proxy.suspend_resume(suspend_time)


    def suspend_resume_bg(self, suspend_time=10):
        """Suspends the DUT for a given time in second in the background.

        @param suspend_time: Suspend time in second, default: 10s.
        """
        # TODO(waihong): Use other general API instead of this RPC.
        return self._display_proxy.suspend_resume_bg(suspend_time)


    def wait_for_output(self, output):
        """Waits for the specified output to be connected.

        @param output: The output name as a string.
        """
        self._display_proxy.wait_output_connected(output)


    def hide_cursor(self):
        """Hides mouse cursor by sending a keystroke."""
        self._display_proxy.press_key('Up')


    def _read_root_window_rect(self, w, h, x, y):
        """Reads the given rectangle from the X root window.

        @param w: The width of the rectangle to read.
        @param h: The height of the rectangle to read.
        @param x: The x coordinate.
        @param y: The y coordinate.

        @return: An Image object.
        """
        with tempfile.NamedTemporaryFile(suffix='.rgb') as f:
            basename = os.path.basename(f.name)
            remote_path = os.path.join('/tmp', basename)
            box = (x, y, x + w, y + h)
            self._display_proxy.take_screenshot_crop(remote_path, box)
            self._client.get_file(remote_path, f.name)
            return Image.fromstring('RGB', (w, h), open(f.name).read())


    def get_internal_display_resolution(self):
        """Gets the resolution of internal display on framebuffer.

        @return The resolution tuple (width, height). None if any error.
        """
        connector = self.get_internal_connector_name()
        if not connector:
            return None
        w, h, _, _ = self._display_proxy.get_resolution(connector)
        return (w, h)


    def capture_internal_screen(self):
        """Captures the internal screen framebuffer.

        @return: An Image object. None if any error.
        """
        connector = self.get_internal_connector_name()
        if not connector:
            return None
        return self._read_root_window_rect(
                *self._display_proxy.get_resolution(connector))


    def capture_external_screen(self):
        """Captures the external screen framebuffer.

        @return: An Image object.
        """
        output = self.get_external_connector_name()
        w, h, x, y = self._display_proxy.get_resolution(output)
        return self._read_root_window_rect(w, h, x, y)


    def get_resolution(self, connector=None):
        """Gets the resolution of the specified screen.

        @param connector: name of the connector of the target screen; if not
                specified, get_external_connector_name() is used.
        @return The resolution tuple (width, height)
        """
        if not connector:
            connector = self.get_external_connector_name()
        width, height, _, _ = self._display_proxy.get_resolution(connector)
        return (width, height)


    def set_resolution(self, display_index, width, height):
        """Sets the resolution on the specified display.

        @param display_index: index of the display to set resolutions for.
        @param width: width of the resolution
        @param height: height of the resolution
        """
        self._display_proxy.set_resolution(
                display_index, width, height)


    def get_display_info(self):
        """Gets the information of all the displays that are connected to the
                DUT.

        @return: list of object DisplayInfo for display informtion
        """
        return map(DisplayInfo, self._display_proxy.get_display_info())


    def get_display_modes(self, display_index):
        """Gets the display modes of the specified display.

        @param display_index: index of the display to get modes from; the index
            is from the DisplayInfo list obtained by get_display_info().

        @return: list of DisplayMode dicts.
        """
        return self._display_proxy.get_display_modes(display_index)


    def get_available_resolutions(self, display_index):
        """Gets the resolutions from the specified display.

        @return a list of (width, height) tuples.
        """
        # Start from M38 (refer to http://codereview.chromium.org/417113012),
        # a DisplayMode dict contains 'originalWidth'/'originalHeight'
        # in addition to 'width'/'height'.
        # OriginalWidth/originalHeight is what is supported by the display
        # while width/height is what is shown to users in the display setting.
        modes = self.get_display_modes(display_index)
        if modes:
            if 'originalWidth' in modes[0]:
                # M38 or newer
                # TODO(tingyuan): fix loading image for cases where original
                #                 width/height is different from width/height.
                return list(set([(mode['originalWidth'], mode['originalHeight'])
                        for mode in modes]))

        # pre-M38
        return [(mode['width'], mode['height']) for mode in modes
                if 'scale' not in mode]
