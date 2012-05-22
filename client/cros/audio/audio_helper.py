#!/usr/bin/python
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
import re
import tempfile
import threading

from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error

LD_LIBRARY_PATH = 'LD_LIBRARY_PATH'

_DEFAULT_NUM_CHANNELS = 2
_DEFAULT_INPUT_DEVICE = 'default'
_DEFAULT_RECORD_DURATION = 10
_DEFAULT_SOX_FORMAT = '-t raw -b 16 -e signed -r 48000 -L'

_SOX_RMS_AMPLITUDE_RE = re.compile('RMS\s+amplitude:\s+(.+)')
_SOX_ROUGH_FREQ_RE = re.compile('Rough\s+frequency:\s+(.+)')
_SOX_FORMAT = '-t raw -b 16 -e signed -r 48000 -L'


class RecordSampleThread(threading.Thread):
    '''Wraps the execution of arecord in a thread.'''
    def __init__(self, audio, recordfile):
        threading.Thread.__init__(self)
        self._audio = audio
        self._recordfile = recordfile

    def run(self):
        self._audio.record_sample(self._recordfile)


class AudioHelper(object):
    '''
    A helper class contains audio related utility functions.
    '''
    def __init__(self, test, sox_format=_DEFAULT_SOX_FORMAT,
                 input_device=_DEFAULT_INPUT_DEVICE,
                 record_duration=_DEFAULT_RECORD_DURATION,
                 num_channels = _DEFAULT_NUM_CHANNELS):
        self._test = test
        self._sox_format = sox_format
        self._input_device = input_device
        self._record_duration = record_duration
        self._num_channels = num_channels

    def setup_deps(self, deps):
        '''
        Sets up audio related dependencies.
        '''
        for dep in deps:
            if dep == 'test_tones':
                dep_dir = os.path.join(self._test.autodir, 'deps', dep)
                self._test.job.install_pkg(dep, 'dep', dep_dir)
                self.test_tones_path = os.path.join(dep_dir, 'src', dep)
            elif dep == 'audioloop':
                dep_dir = os.path.join(self._test.autodir, 'deps', dep)
                self._test.job.install_pkg(dep, 'dep', dep_dir)
                self.audioloop_path = os.path.join(dep_dir, 'src',
                        'looptest')
            elif dep == 'sox':
                dep_dir = os.path.join(self._test.autodir, 'deps', dep)
                self._test.job.install_pkg(dep, 'dep', dep_dir)
                self.sox_path = os.path.join(dep_dir, 'bin', dep)
                self.sox_lib_path = os.path.join(dep_dir, 'lib')
                if os.environ.has_key(LD_LIBRARY_PATH):
                    paths = os.environ[LD_LIBRARY_PATH].split(':')
                    if not self.sox_lib_path in paths:
                        paths.append(self.sox_lib_path)
                        os.environ[LD_LIBRARY_PATH] = ':'.join(paths)
                else:
                    os.environ[LD_LIBRARY_PATH] = self.sox_lib_path

    def cleanup_deps(self, deps):
        '''
        Cleans up environments which has been setup for dependencies.
        '''
        for dep in deps:
            if dep == 'sox':
                if (os.environ.has_key(LD_LIBRARY_PATH)
                        and hasattr(self, 'sox_lib_path')):
                    paths = filter(lambda x: x != self.sox_lib_path,
                            os.environ[LD_LIBRARY_PATH].split(':'))
                    os.environ[LD_LIBRARY_PATH] = ':'.join(paths)

    def set_mixer_controls(self, mixer_settings={}, card='0'):
        '''
        Sets all mixer controls listed in the mixer settings on card.
        '''
        logging.info('Setting mixer control values on %s' % card)
        for item in mixer_settings:
            logging.info('Setting %s to %s on card %s' %
                         (item['name'], item['value'], card))
            cmd = 'amixer -c %s cset name=%s %s'
            cmd = cmd % (card, item['name'], item['value'])
            try:
                utils.system(cmd)
            except error.CmdError:
                # A card is allowed not to support all the controls, so don't
                # fail the test here if we get an error.
                logging.info('amixer command failed: %s' % cmd)

    def sox_stat_output(self, infile, channel):
        sox_mixer_cmd = self.get_sox_mixer_cmd(infile, channel)
        stat_cmd = '%s -c 1 %s - -n stat 2>&1' % (self.sox_path,
                self._sox_format)
        sox_cmd = '%s | %s' % (sox_mixer_cmd, stat_cmd)
        return utils.system_output(sox_cmd, retain_output=True)

    def get_audio_rms(self, sox_output):
        for rms_line in sox_output.split('\n'):
            m = _SOX_RMS_AMPLITUDE_RE.match(rms_line)
            if m is not None:
                return float(m.group(1))

    def get_rough_freq(self, sox_output):
        for rms_line in sox_output.split('\n'):
            m = _SOX_ROUGH_FREQ_RE.match(rms_line)
            if m is not None:
                return int(m.group(1))


    def get_sox_mixer_cmd(self, infile, channel):
        # Build up a pan value string for the sox command.
        if channel == 0:
            pan_values = '1'
        else:
            pan_values = '0'
        for pan_index in range(1, self._num_channels):
            if channel == pan_index:
                pan_values = '%s%s' % (pan_values, ',1')
            else:
                pan_values = '%s%s' % (pan_values, ',0')

        return '%s -c 2 %s %s -c 1 %s - mixer %s' % (self.sox_path,
                self._sox_format, infile, self._sox_format, pan_values)

    def noise_reduce_file(self, in_file, noise_file, out_file):
        '''Runs the sox command to noise-reduce in_file using
           the noise profile from noise_file.

        Args:
            in_file: The file to noise reduce.
            noise_file: The file containing the noise profile.
                        This can be created by recording silence.
            out_file: The file contains the noise reduced sound.

        Returns:
            The name of the file containing the noise-reduced data.
        '''
        prof_cmd = '%s -c 2 %s %s -n noiseprof' % (self.sox_path,
                _SOX_FORMAT, noise_file)
        reduce_cmd = ('%s -c 2 %s %s -c 2 %s %s noisered' %
                (self.sox_path, _SOX_FORMAT, in_file, _SOX_FORMAT, out_file))
        utils.system('%s | %s' % (prof_cmd, reduce_cmd))

    def record_sample(self, tmpfile):
        '''Records a sample from the default input device.

        Args:
            duration: How long to record in seconds.
            tmpfile: The file to record to.
        '''
        cmd_rec = 'arecord -D %s -d %f -f dat %s' % (self._input_device,
                self._record_duration, tmpfile)
        logging.info('Command %s recording now (%fs)' % (cmd_rec,
                self._record_duration))
        utils.system(cmd_rec)

    def loopback_test_channels(self, noise_file, loopback_callback,
            check_recorded_callback):
        '''Tests loopback on all channels.

        Args:
            noise_file: The file contains the pre-recorded noise.
            loopback_callback: The callback to do the loopback for one channel.
            check_recorded_callback: The callback function to check the
                    calculated RMS value.
        '''
        for channel in xrange(self._num_channels):
            # Temp file for the final noise-reduced file.
            with tempfile.NamedTemporaryFile(mode='w+t') as reduced_file:
                # Temp file that records before noise reduction.
                with tempfile.NamedTemporaryFile(mode='w+t') as tmpfile:
                    record_thread = RecordSampleThread(self, tmpfile.name)
                    record_thread.start()
                    loopback_callback(channel)
                    record_thread.join()

                    self.noise_reduce_file(tmpfile.name, noise_file.name,
                            reduced_file.name)

                sox_output = self.sox_stat_output(reduced_file.name, channel)
                check_recorded_callback(sox_output)
