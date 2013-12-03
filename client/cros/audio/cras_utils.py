# Copyright (c) 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import re
import subprocess

from autotest_lib.client.bin import utils
from autotest_lib.client.cros.audio import cmd_utils

_CRAS_TEST_CLIENT = '/usr/bin/cras_test_client'
_RE_SELECTED_OUTPUT_NODE = re.compile('Selected Output Node: (.*)')
_RE_SELECTED_INPUT_NODE = re.compile('Selected Input Node: (.*)')

def playback(*args, **kargs):
    """A helper function to execute the playback_cmd."""
    cmd_utils.execute(playback_cmd(*args, **kargs))

def capture(*args, **kargs):
    """A helper function to execute the capture_cmd."""
    cmd_utils.execute(capture_cmd(*args, **kargs))

def playback_cmd(playback_file, buffer_frames=None, duration=None, rate=44100):
    """Gets a command to playback a file with given settings.

    @param playback_file: the name of the file to play. '-' indicates to
                          playback raw audio from the stdin.
    @param buffer_frames: total number of frames to buffer.
    @param duration: seconds to playback
    @param rate: the sampling rate
    """
    args = [_CRAS_TEST_CLIENT]
    args += ['--playback_file', playback_file]
    if buffer_frames is not None:
        args += ['--buffer_frames', str(buffer_frames)]
    if duration is not None:
        args += ['--duration', str(duration)]
    args += ['--rate', str(rate)]
    return args

def capture_cmd(capture_file, buffer_frames=None, duration=10, rate=44100):
    """Gets a command to capture the audio into the file with given settings.

    @param capture_file: the name of file the audio to be stored in.
    @param buffer_frames: total number of frames to bufffer.
    @param duration: seconds to record.
    @param rate: the sampling rate.
    """
    args = [_CRAS_TEST_CLIENT]
    args += ['--capture_file', capture_file]
    if buffer_frames is not None:
        args += ['--buffer_frames', str(buffer_frames)]
    args += ['--duration', str(duration)]
    args += ['--rate', str(rate)]
    return args

def set_system_volume(volume):
    """Set the system volume.

    @param volume: the system output vlume to be set(0 - 100).
    """
    args = [_CRAS_TEST_CLIENT]
    args += ['--volume', str(volume)]
    cmd_utils.execute(args)

def set_node_volume(node_id, volume):
    """Set the volume of the given output node.

    @param node_id: the id of the output node to be set the volume.
    @param volume: the volume to be set(0-100).
    """
    args = [_CRAS_TEST_CLIENT]
    args += ['--set_node_volume', '%s:%d' % (node_id, volume)]
    cmd_utils.execute(args)

def set_capture_gain(gain):
    """Set the system capture gain.
    @param gain the capture gain in db*100 (100 = 1dB)
    """
    args = [_CRAS_TEST_CLIENT]
    args += ['--capture_gain', str(gain)]
    cmd_utils.execute(args)

def dump_server_info():
    """Gets the CRAS's server information."""
    args = [_CRAS_TEST_CLIENT, '--dump_server_info']
    return cmd_utils.execute(args, stdout=subprocess.PIPE)

def get_selected_nodes():
    """Returns the pair of active output node and input node."""
    server_info = dump_server_info()
    output_match = _RE_SELECTED_OUTPUT_NODE.search(server_info)
    input_match = _RE_SELECTED_INPUT_NODE.search(server_info)
    if not output_match or not input_match:
        logging.error(server_info)
        raise RuntimeError('No match for the pattern')

    return (output_match.group(1).strip(), input_match.group(1).strip())
