# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This is a server side HDMI audio test using the Chameleon board."""

import logging
import os
import time

from autotest_lib.client.common_lib import error
from autotest_lib.client.cros.audio import audio_test_data
from autotest_lib.client.cros.chameleon import chameleon_audio_helper
from autotest_lib.client.cros.chameleon import chameleon_audio_ids
from autotest_lib.server import test
from autotest_lib.server.cros.multimedia import remote_facade_factory


class audio_AudioBasicHDMI(test.test):
    """Server side HDMI audio test.

    This test talks to a Chameleon board and a Cros device to verify
    HDMI audio function of the Cros device.

    """
    version = 2
    DELAY_BEFORE_PLAYBACK = 2
    DELAY_AFTER_PLAYBACK = 2
    DELAY_AFTER_BINDING = 2

    def run_once(self, host):
        golden_file = audio_test_data.SWEEP_TEST_FILE

        chameleon_board = host.chameleon
        factory = remote_facade_factory.RemoteFacadeFactory(host)

        chameleon_board.reset()

        widget_factory = chameleon_audio_helper.AudioWidgetFactory(
                chameleon_board, factory)

        source = widget_factory.create_widget(
            chameleon_audio_ids.CrosIds.HDMI)
        recorder = widget_factory.create_widget(
            chameleon_audio_ids.ChameleonIds.HDMI)
        binder = widget_factory.create_binder(source, recorder)

        with chameleon_audio_helper.bind_widgets(binder):
            time.sleep(DELAY_AFTER_BINDING)
            audio_facade = factory.create_audio_facade()
            output_node, _ = audio_facade.get_selected_node_types()
            if output_node != 'HDMI':
                raise error.TestError(
                        '%s rather than HDMI is selected on Cros device' %
                                output_node)

            logging.info('Start recording from Chameleon.')
            recorder.start_recording()

            time.sleep(self.DELAY_BEFORE_PLAYBACK)

            logging.info('Start playing %s on Cros device',
                         golden_file.path)
            source.start_playback(golden_file, blocking=True)

            logging.info('Stopped playing %s on Cros device',
                         golden_file.path)
            time.sleep(self.DELAY_AFTER_PLAYBACK)

            recorder.stop_recording()
            logging.info('Stopped recording from Chameleon.')

        recorded_file = os.path.join(self.resultsdir, "recorded.raw")
        logging.info('Saving recorded data to %s', recorded_file)
        recorder.save_file(recorded_file)

        if not chameleon_audio_helper.compare_recorded_result(
                golden_file, recorder, 'correlation'):
            raise error.TestError(
                    'Recorded file does not match playback file')
