# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This is a server side audio nodes s test using the Chameleon board."""

import logging
import time

from autotest_lib.client.cros.chameleon import audio_test_utils
from autotest_lib.client.cros.chameleon import audio_widget_link
from autotest_lib.client.cros.chameleon import chameleon_audio_ids
from autotest_lib.server.cros.audio import audio_test



class audio_AudioNodeSwitch(audio_test.AudioTest):
    """Server side audio test.

    This test talks to a Chameleon board and a Cros device to verify
    audio nodes switch correctly.

    """
    version = 1
    _PLUG_DELAY = 5

    def check_default_nodes(self, host, audio_facade):
        """Checks default audio nodes for devices with onboard audio support.

        @param audio_facade: A RemoteAudioFacade to access audio functions on
                             Cros device.

        @param host: The CrosHost object.

        """
        if audio_test_utils.has_internal_microphone(host):
            audio_test_utils.check_audio_nodes(audio_facade,
                                               (None, ['INTERNAL_MIC']))
        if audio_test_utils.has_internal_speaker(host):
            audio_test_utils.check_audio_nodes(audio_facade,
                                               (['INTERNAL_SPEAKER'], None))


    def run_once(self, host, jack_node=False):
        chameleon_board = host.chameleon
        audio_board = chameleon_board.get_audio_board()
        factory = self.create_remote_facade_factory(host)

        chameleon_board.reset()
        audio_facade = factory.create_audio_facade()

        self.check_default_nodes(host, audio_facade)
        if jack_node:
            jack_plugger = audio_board.get_jack_plugger()
            jack_plugger.plug()
            time.sleep(self._PLUG_DELAY)

            audio_test_utils.dump_cros_audio_logs(
                    host, audio_facade, self.resultsdir)

            audio_test_utils.check_audio_nodes(audio_facade,
                                               (['HEADPHONE'], ['MIC']))

            jack_plugger.unplug()

        time.sleep(self._PLUG_DELAY)
        self.check_default_nodes(host, audio_facade)

