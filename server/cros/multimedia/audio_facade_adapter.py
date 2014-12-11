# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""An adapter to remotely access the audio facade on DUT."""

class AudioFacadeRemoteAdapter(object):
    """AudioFacadeRemoteAdapter is an adapter to remotely control DUT audio."""
    def __init__(self, remote_facade_proxy):
        """Construct an AudioFacadeRemoteAdapter.

        @param remote_facade_proxy: RemoteFacadeProxy object.

        """
        self._proxy = remote_facade_proxy


    @property
    def _audio_proxy(self):
        """Gets the proxy to DUT audio facade.

        @return XML RPC proxy to DUT audio facade.

        """
        return self._proxy.audio


    def playback(self, file_path, blocking=False):
        """Playback an audio file on DUT.

        @param file_path: The path to the file on DUT.
        @param blocking: Blocks this call until playback finishes.

        """
        self._audio_proxy.playback(file_path, blocking)
