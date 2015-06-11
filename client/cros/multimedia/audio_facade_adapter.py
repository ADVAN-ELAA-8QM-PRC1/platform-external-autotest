# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""An adapter to access the local audio facade."""

import os
import shutil

from autotest_lib.client.cros.multimedia import audio_facade_native


class AudioFacadeLocalAdapterError(Exception):
    """Error in AudioFacadeLocalAdapter."""
    pass


class AudioFacadeLocalAdapter(audio_facade_native.AudioFacadeNative):
    """AudioFacadeLocalAdapter is an adapter to control the local audio.

    Methods with non-native-type arguments go to this class and do some
    conversion; otherwise, go to the AudioFacadeNative class.
    """
    # TODO: Add methods to adapt the native ones once any non-native-type
    # methods are added.
    def set_playback_file(self, path):
        """Set playback file.

        This call is for consistency with audio_facade_adapter on server side.

        @param path: A path to the file.

        @returns: path itself.

        @raises: AudioFacadeLocalAdapterError if path does not exist.

        """
        if not os.exists(path):
            raise AudioFacadeLocalAdapter(
                    'Path %s does not exist' % path)
        return path


    def get_recorded_file(self, src_path, dst_path):
        """Gets a recorded file.

        @param src_path: The path to the recorded file.
        @param dst_path: The local path for copy destination.

        """
        shutil.copy(src_path, dst_path)
