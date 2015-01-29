# Copyright (c) 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import re

from autotest_lib.client.bin import utils
from autotest_lib.client.cros.audio import cmd_utils

_CRAS_TEST_CLIENT = '/usr/bin/cras_test_client'
_RE_SELECTED_OUTPUT_NODE = re.compile('Selected Output Node: (.*)')
_RE_SELECTED_INPUT_NODE = re.compile('Selected Input Node: (.*)')
_RE_NUM_ACTIVE_STREAM = re.compile('Num active streams: (.*)')

def playback(*args, **kargs):
    """A helper function to execute the playback_cmd."""
    cmd_utils.execute(playback_cmd(*args, **kargs))

def capture(*args, **kargs):
    """A helper function to execute the capture_cmd."""
    cmd_utils.execute(capture_cmd(*args, **kargs))

def playback_cmd(playback_file, block_size=None, duration=None,
                 channels=2, rate=48000):
    """Gets a command to playback a file with given settings.

    @param playback_file: the name of the file to play. '-' indicates to
                          playback raw audio from the stdin.
    @param block_size: the number of frames per callback(dictates latency).
    @param duration: seconds to playback
    @param rate: the sampling rate
    """
    args = [_CRAS_TEST_CLIENT]
    args += ['--playback_file', playback_file]
    if block_size is not None:
        args += ['--block_size', str(block_size)]
    if duration is not None:
        args += ['--duration', str(duration)]
    args += ['--num_channels', str(channels)]
    args += ['--rate', str(rate)]
    return args

def capture_cmd(
        capture_file, block_size=None, duration=10, channels=1, rate=48000):
    """Gets a command to capture the audio into the file with given settings.

    @param capture_file: the name of file the audio to be stored in.
    @param block_size: the number of frames per callback(dictates latency).
    @param duration: seconds to record. If it is None, duration is not set,
                     and command will keep capturing audio until it is
                     terminated.
    @param rate: the sampling rate.
    """
    args = [_CRAS_TEST_CLIENT]
    args += ['--capture_file', capture_file]
    if block_size is not None:
        args += ['--block_size', str(block_size)]
    if duration is not None:
        args += ['--duration', str(duration)]
    args += ['--num_channels', str(channels)]
    args += ['--rate', str(rate)]
    return args


def loopback(*args, **kargs):
    """A helper function to execute loopback_cmd."""
    cmd_utils.execute(loopback_cmd(*args, **kargs))


def loopback_cmd(output_file, duration=10, channels=2, rate=48000):
    """Gets a command to record the loopback.

    @param output_file: The name of the file the loopback to be stored in.
    @param channels: The number of channels of the recorded audio.
    @param duration: seconds to record.
    @param rate: the sampling rate.
    """
    args = [_CRAS_TEST_CLIENT]
    args += ['--loopback_file', output_file]
    args += ['--duration_seconds', str(duration)]
    args += ['--num_channels', str(channels)]
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
    return cmd_utils.execute(args, stdout=cmd_utils.PIPE)

def get_selected_nodes():
    """Returns the pair of active output node and input node."""
    server_info = dump_server_info()
    output_match = _RE_SELECTED_OUTPUT_NODE.search(server_info)
    input_match = _RE_SELECTED_INPUT_NODE.search(server_info)
    if not output_match or not input_match:
        logging.error(server_info)
        raise RuntimeError('No match for the pattern')

    return (output_match.group(1).strip(), input_match.group(1).strip())

def get_active_stream_count():
    """Gets the number of active streams."""
    server_info = dump_server_info()
    match = _RE_NUM_ACTIVE_STREAM.search(server_info)
    if not match:
        logging.error(server_info)
        raise RuntimeException('Cannot find matched pattern')
    return int(match.group(1))


def set_system_mute(is_mute):
    """Sets the system mute switch.

    @param is_mute: Set True to mute the system playback.
    """
    args = [_CRAS_TEST_CLIENT, '--mute', '1' if is_mute else '0']
    cmd_utils.execute(args)


def set_capture_mute(is_mute):
    """Sets the capture mute switch.

    @param is_mute: Set True to mute the capture.
    """
    args = [_CRAS_TEST_CLIENT, '--capture_mute', '1' if is_mute else '0']
    cmd_utils.execute(args)


def node_type_is_plugged(node_type, server_info=None):
    """Determine if there is any node of node_type plugged.

    Parses server info to get the plugged state of certain node type.
    The server info of interest is in this format:

    ...(other info)...

     ID   Vol   Plugged  L/R swapped Time      Type       Name
    3:0    75   yes     no     1419323058   HEADPHONE  *Headphone
    4:0     0   yes     no     1419323059   MIC        *Mic Jack

    ...(other info)...


    @param node_type: A str representing node type. e.g. 'HEADPHONE' or
                      'MIC'.
    @param server_info: A str containing server info. None to call
                        dump_server_info in this function.

    @returns: True if there is any node of node_type plugged. False otherwise.

    @raises: ValueError: if cras server info format is not as expected.
    """
    # The label line
    # ID   Vol   Plugged  L/R swapped Time      Type       Name
    _MIN_LEN_LABELS = 8
    _INDEX_LABEL_PLUGGED = 2
    _INDEX_LABEL_TYPE = 6

    # The value line
    # 3:0    75   yes     no     1419323058   HEADPHONE  *Headphone
    _MIN_LEN_VALUES = 7
    _INDEX_VALUE_PLUGGED = 2
    _INDEX_VALUE_TYPE = 5

    if not server_info:
        server_info = dump_server_info()
    state = False
    for line in server_info.splitlines():
        line_split = line.split()
        # Checks if a label line follows format.
        if 'Plugged' in line_split and 'Type' in line_split:
            if (len(line_split) < _MIN_LEN_LABELS or
                line_split[_INDEX_LABEL_PLUGGED] != 'Plugged' or
                line_split[_INDEX_LABEL_TYPE] != 'Type'):
                raise ValueError('cras server info format is not as '
                                 'expected')
        if len(line_split) < _MIN_LEN_VALUES:
            continue
        # Checks a value line of interest.
        # There might be other nodes of node_type, so keep searching if
        # this node is not plugged.
        if (line_split[_INDEX_VALUE_TYPE] == node_type and
            line_split[_INDEX_VALUE_PLUGGED] == 'yes'):
            state = True
    return state
