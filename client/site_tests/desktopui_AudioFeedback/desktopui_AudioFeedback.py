# Copyright (c) 2012 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging, tempfile

from autotest_lib.client.bin import test
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros import cros_ui_test, httpd
from autotest_lib.client.cros.audio import audio_helper

# Names of mixer controls.
_CONTROL_MASTER = "'Master Playback Volume'"
_CONTROL_HEADPHONE = "'Headphone Playback Volume'"
_CONTROL_SPEAKER = "'Speaker Playback Volume'"
_CONTROL_MIC_BOOST = "'Mic Boost Volume'"
_CONTROL_MIC_CAPTURE = "'Mic Capture Volume'"
_CONTROL_CAPTURE = "'Capture Volume'"
_CONTROL_PCM = "'PCM Playback Volume'"
_CONTROL_DIGITAL = "'Digital Capture Volume'"
_CONTROL_CAPTURE_SWITCH = "'Capture Switch'"

# Default test configuration.
_DEFAULT_CARD = '0'
_DEFAULT_MIXER_SETTINGS = [{'name': _CONTROL_MASTER, 'value': "100%"},
                           {'name': _CONTROL_HEADPHONE, 'value': "100%"},
                           {'name': _CONTROL_SPEAKER, 'value': "0%"},
                           {'name': _CONTROL_MIC_BOOST, 'value': "50%"},
                           {'name': _CONTROL_MIC_CAPTURE, 'value': "50%"},
                           {'name': _CONTROL_PCM, 'value': "100%"},
                           {'name': _CONTROL_DIGITAL, 'value': "100%"},
                           {'name': _CONTROL_CAPTURE, 'value': "100%"},
                           {'name': _CONTROL_CAPTURE_SWITCH, 'value': "on"}]

_DEFAULT_NUM_CHANNELS = 2
_DEFAULT_RECORD_DURATION = 15
# Minimum RMS value to consider a "pass".
_DEFAULT_SOX_RMS_THRESHOLD = 0.30
_DEFAULT_VOLUME_LEVEL = 100
_DEFAULT_CAPTURE_GAIN = 2500


class desktopui_AudioFeedback(cros_ui_test.UITest):
    version = 1

    def initialize(self,
                   card=_DEFAULT_CARD,
                   mixer_settings=_DEFAULT_MIXER_SETTINGS,
                   num_channels=_DEFAULT_NUM_CHANNELS,
                   record_duration=_DEFAULT_RECORD_DURATION,
                   sox_min_rms=_DEFAULT_SOX_RMS_THRESHOLD,
                   volume_level=_DEFAULT_VOLUME_LEVEL,
                   capture_gain=_DEFAULT_CAPTURE_GAIN):
        """Setup the deps for the test.

        Args:
            card: The index of the sound card to use.
            mixer_settings: Alsa control settings to apply to the mixer before
                starting the test.
            num_channels: The number of channels on the device to test.
            record_duration: How long of a sample to record.
            sox_min_rms: The minimum RMS value to consider a pass.

        Raises:
            error.TestError if the deps can't be run.
        """
        self._card = card
        self._mixer_settings = mixer_settings
        self._volume_level = volume_level
        self._capture_gain = capture_gain

        cmd_rec = 'arecord -D hw:0,0 -d %f -f dat' % record_duration
        self._ah = audio_helper.AudioHelper(self,
                record_command=cmd_rec,
                sox_threshold=sox_min_rms,
                num_channels=num_channels)
        self._ah.setup_deps(['sox'])

        super(desktopui_AudioFeedback, self).initialize()
        self._test_url = 'http://localhost:8000/youtube.html'
        self._testServer = httpd.HTTPListener(8000, docroot=self.bindir)
        self._testServer.run()

    def run_once(self):
        self._ah.set_volume_levels(self._volume_level, self._capture_gain)
        if not self._ah.check_loopback_dongle():
            raise error.TestError('Audio loopback dongle is in bad state.')

        # Record a sample of "silence" to use as a noise profile.
        with tempfile.NamedTemporaryFile(mode='w+t') as noise_file:
            logging.info('Noise file: %s' % noise_file.name)
            self._ah.record_sample(noise_file.name)

            # Play the same video to test all channels.
            self._ah.loopback_test_channels(noise_file,
                    lambda channel: self.play_video())

    def play_video(self):
        """Plays a Youtube video to record audio samples.

           Skipping initial 60 seconds so we can ignore initial silence
           in the video.
        """
        logging.info('Playing back youtube media file %s.' % self._test_url)
        self.pyauto.NavigateToURL(self._test_url)
        if not self.pyauto.WaitUntil(lambda: self.pyauto.ExecuteJavascript("""
                    player_status = document.getElementById('player_status');
                    window.domAutomationController.send(player_status.innerHTML);
               """), expect_retval='player ready'):
            raise error.TestError('Failed to load the Youtube player')
        self.pyauto.ExecuteJavascript("""
            ytplayer.pauseVideo();
            ytplayer.seekTo(60, true);
            ytplayer.playVideo();
            window.domAutomationController.send('');
        """)
