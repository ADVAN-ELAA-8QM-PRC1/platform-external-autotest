# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This is a server side external microphone test using the Chameleon board."""

import logging
import os
import time

from autotest_lib.client.common_lib import error
from autotest_lib.client.cros.audio import audio_test_data
from autotest_lib.client.cros.chameleon import chameleon_audio_ids
from autotest_lib.client.cros.chameleon import chameleon_audio_helper
from autotest_lib.server import test
from autotest_lib.server.cros.multimedia import remote_facade_factory


class audio_AudioBasicExternalMicrophone(test.test):
    """Server side external microphone audio test.

    This test talks to a Chameleon board and a Cros device to verify
    external mic audio function of the Cros device.

    """
    version = 1
    DELAY_BEFORE_RECORD_SECONDS = 0.5
    RECORD_SECONDS = 9
    DELAY_AFTER_BINDING = 0.5

    def run_once(self, host):
        golden_file = audio_test_data.SIMPLE_FREQUENCY_TEST_FILE

        chameleon_board = host.chameleon
        factory = remote_facade_factory.RemoteFacadeFactory(host)

        chameleon_board.reset()

        widget_factory = chameleon_audio_helper.AudioWidgetFactory(
                chameleon_board, factory)

        source = widget_factory.create_widget(
            chameleon_audio_ids.ChameleonIds.LINEOUT)
        recorder = widget_factory.create_widget(
            chameleon_audio_ids.CrosIds.EXTERNAL_MIC)
        binder = widget_factory.create_binder(source, recorder)

        with chameleon_audio_helper.bind_widgets(binder):
            # Checks the node selected by cras is correct.
            time.sleep(self.DELAY_AFTER_BINDING)
            audio_facade = factory.create_audio_facade()
            _, input_node = audio_facade.get_selected_node_types()
            if input_node != 'MIC':
                raise error.TestError(
                        '%s rather than external mic is selected on Cros '
                        'device' % input_node)

            # Starts playing, waits for some time, and then starts recording.
            # This is to avoid artifact caused by chameleon codec initialization
            # in the beginning of playback.
            logging.info('Start playing %s from Chameleon',
                         golden_file.path)
            source.start_playback(golden_file)

            time.sleep(self.DELAY_BEFORE_RECORD_SECONDS)
            logging.info('Start recording from Cros device.')
            recorder.start_recording()

            time.sleep(self.RECORD_SECONDS)

            recorder.stop_recording()
            logging.info('Stopped recording from Cros device.')


        recorded_file = os.path.join(self.resultsdir, "recorded.raw")
        logging.info('Saving recorded data to %s', recorded_file)
        recorder.save_file(recorded_file)

        # Removes the beginning of recorded data. This is to avoid artifact
        # caused by Cros device codec initialization in the beginning of
        # recording.
        recorder.remove_head(1.5)

        # Removes noise by a lowpass filter.
        recorder.lowpass_filter(2000)
        recorded_file = os.path.join(self.resultsdir, "recorded_filtered.raw")
        logging.info('Saving filtered data to %s', recorded_file)
        recorder.save_file(recorded_file)

        # Compares data by frequency. Audio signal from Chameleon Line-Out to
        # Cros device external microphone has gone through analog processing.
        # This suffers from codec artifacts and noise on the path.
        # Comparing data by frequency is more robust than comparing them by
        # correlation, which is suitable for fully-digital audio path like USB
        # and HDMI.
        if not chameleon_audio_helper.compare_recorded_result(
                golden_file, recorder, 'frequency'):
            raise error.TestError(
                    'Recorded file does not match playback file')
