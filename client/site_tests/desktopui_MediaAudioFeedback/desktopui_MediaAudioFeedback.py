# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging, os, tempfile

from autotest_lib.client.bin import test, utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros import chrome
from autotest_lib.client.cros.audio import audio_helper

TEST_DURATION = 10
VOLUME_LEVEL = 100
CAPTURE_GAIN = 2500

# Media formats to test.
MEDIA_FORMATS = ['sine440.mp3',
                 'sine440.mp4',
                 'sine440.wav',
                 'sine440.ogv',
                 'sine440.webm']

PLAYER_READY_TIMEOUT = 45

class desktopui_MediaAudioFeedback(test.test):
    """Verifies if media playback can be captured."""
    version = 1

    _rec_cmd = 'arecord -d %f -f dat' % TEST_DURATION
    _mix_cmd = '/usr/bin/cras_test_client --show_total_rms ' \
               '--duration_seconds %f --num_channels 2 ' \
               '--rate 48000 --loopback_file' % TEST_DURATION

    @audio_helper.chrome_rms_test
    def run_once(self, chrome):
        chrome.browser.SetHTTPServerDirectories(self.bindir)
        self._cr = chrome

        def record_callback(filename):
            audio_helper.record_sample(filename, self._rec_cmd)

        def mix_callback(filename):
            utils.system("%s %s" % (self._mix_cmd, filename))

        # Record a sample of "silence" to use as a noise profile.
        with tempfile.NamedTemporaryFile(mode='w+t') as noise_file:
            logging.info('Noise file: %s', noise_file.name)
            audio_helper.record_sample(noise_file.name, self._rec_cmd)
            # Test each media file for all channels.
            for media_file in MEDIA_FORMATS:
                audio_helper.loopback_test_channels(noise_file.name,
                        self.resultsdir,
                        lambda channel: self.play_media(media_file),
                        self.wait_player_end_then_check_recorded,
                        num_channels=2,
                        record_callback=record_callback,
                        mix_callback=mix_callback)

    def wait_player_end_then_check_recorded(self, sox_output):
        """Wait for player ends playing and then check for recorded result.

        @param sox_output: sox statistics output of recorded wav file.
        """
        tab = self._cr.browser.tabs[0]
        utils.poll_for_condition(
            condition=lambda: tab.EvaluateJavaScript('getPlayerStatus()') ==
                    'Ended',
            exception=error.TestError('Player never end until timeout.'),
            sleep_interval=1,
            timeout=PLAYER_READY_TIMEOUT)
        audio_helper.check_audio_rms(sox_output)

    def play_media(self, media_file):
        """Plays a media file in Chromium.

        @param media_file: Media file to test.
        """
        logging.info('Playing back now media file %s.', media_file)

        # Navigate to play.html?<file-name>, javascript test will parse
        # the media file name and play it.
        url = self._cr.browser.http_server.UrlOf(
                os.path.join(self.bindir, 'play.html'))
        self._cr.browser.tabs[0].Navigate('%s?%s' % (url, media_file))
