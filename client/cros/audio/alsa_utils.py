# Copyright (c) 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re
import shlex

from autotest_lib.client.cros.audio import cmd_utils


ARECORD_PATH = '/usr/bin/arecord'
APLAY_PATH = '/usr/bin/aplay'
AMIXER_PATH = '/usr/bin/amixer'
CARD_NUM_RE = re.compile('(\d+) \[.*\]:.*')
CONTROL_NAME_RE = re.compile("name='(.*)'")
SCONTROL_NAME_RE = re.compile("Simple mixer control '(.*)'")


def _get_format_args(channels, bits, rate):
    args = ['-c', str(channels)]
    args += ['-f', 'S%d_LE' % bits]
    args += ['-r', str(rate)]
    return args


def get_num_soundcards():
    '''Returns the number of soundcards.

    Number of soundcards is parsed from /proc/asound/cards.
    Sample content:

      0 [PCH            ]: HDA-Intel - HDA Intel PCH
                           HDA Intel PCH at 0xef340000 irq 103
      1 [NVidia         ]: HDA-Intel - HDA NVidia
                           HDA NVidia at 0xef080000 irq 36
    '''

    card_id = None
    with open('/proc/asound/cards', 'r') as f:
        for line in f:
            match = CARD_NUM_RE.search(line)
            if match:
                card_id = int(match.group(1))
    if card_id is None:
        return 0
    else:
        return card_id + 1


def _get_soundcard_controls(card_id):
    '''Gets the controls for a soundcard.

    @param card_id: Soundcard ID.
    @raise RuntimeError: If failed to get soundcard controls.

    Controls for a soundcard is retrieved by 'amixer controls' command.
    amixer output format:

      numid=32,iface=CARD,name='Front Headphone Jack'
      numid=28,iface=CARD,name='Front Mic Jack'
      numid=1,iface=CARD,name='HDMI/DP,pcm=3 Jack'
      numid=8,iface=CARD,name='HDMI/DP,pcm=7 Jack'

    Controls with iface=CARD are parsed from the output and returned in a set.
    '''

    cmd = AMIXER_PATH + ' -c %d controls' % card_id
    p = cmd_utils.popen(shlex.split(cmd), stdout=cmd_utils.PIPE)
    output, _ = p.communicate()
    if p.wait() != 0:
        raise RuntimeError('amixer command failed')

    controls = set()
    for line in output.splitlines():
        if not 'iface=CARD' in line:
            continue
        match = CONTROL_NAME_RE.search(line)
        if match:
            controls.add(match.group(1))
    return controls


def _get_soundcard_scontrols(card_id):
    '''Gets the simple mixer controls for a soundcard.

    @param card_id: Soundcard ID.
    @raise RuntimeError: If failed to get soundcard simple mixer controls.

    Simple mixer controls for a soundcard is retrieved by 'amixer scontrols'
    command.  amixer output format:

      Simple mixer control 'Master',0
      Simple mixer control 'Headphone',0
      Simple mixer control 'Speaker',0
      Simple mixer control 'PCM',0

    Simple controls are parsed from the output and returned in a set.
    '''

    cmd = AMIXER_PATH + ' -c %d scontrols' % card_id
    p = cmd_utils.popen(shlex.split(cmd), stdout=cmd_utils.PIPE)
    output, _ = p.communicate()
    if p.wait() != 0:
        raise RuntimeError('amixer command failed')

    scontrols = set()
    for line in output.splitlines():
        match = SCONTROL_NAME_RE.findall(line)
        if match:
            scontrols.add(match[0])
    return scontrols


def get_first_soundcard_with_control(cname, scname):
    '''Returns the soundcard ID with matching control name.

    @param cname: Control name to look for.
    @param scname: Simple control name to look for.
    '''

    for card_id in xrange(get_num_soundcards()):
        for name, func in [(cname, _get_soundcard_controls),
                           (scname, _get_soundcard_scontrols)]:
            if any(name in c for c in func(card_id)):
                return card_id
    return None


def get_default_playback_device():
    '''Gets the first playback device.

    Returns the first playback device or None if it fails to find one.
    '''

    card_id = get_first_soundcard_with_control(cname='Headphone Jack',
                                               scname='Headphone')
    if card_id is None:
        return None
    return 'plughw:%d' % card_id


def get_default_record_device():
    '''Gets the first record device.

    Returns the first record device or None if it fails to find one.
    '''

    card_id = get_first_soundcard_with_control(cname='Mic Jack', scname='Mic')
    if card_id is None:
        return None
    return 'plughw:%d' % card_id


def playback(*args, **kwargs):
    '''A helper funciton to execute playback_cmd.

    @param kwargs: kwargs passed to playback_cmd.
    '''
    cmd_utils.execute(playback_cmd(*args, **kwargs))


def playback_cmd(
        input, duration=None, channels=2, bits=16, rate=48000, device=None):
    '''Plays the given input audio by the ALSA utility: 'aplay'.

    @param input: The input audio to be played.
    @param duration: The length of the playback (in seconds).
    @param channels: The number of channels of the input audio.
    @param bits: The number of bits of each audio sample.
    @param rate: The sampling rate.
    @param device: The device to play the audio on.
    @raise RuntimeError: If no playback device is available.
    '''
    args = [APLAY_PATH]
    if duration is not None:
        args += ['-d', str(duration)]
    args += _get_format_args(channels, bits, rate)
    if device is None:
        device = get_default_playback_device()
        if device is None:
            raise RuntimeError('no playback device')
    args += ['-D', device]
    args += [input]
    return args


def record(*args, **kwargs):
    '''A helper function to execute record_cmd.

    @param kwargs: kwargs passed to record_cmd.
    '''
    cmd_utils.execute(record_cmd(*args, **kwargs))


def record_cmd(
        output, duration=None, channels=1, bits=16, rate=48000, device=None):
    '''Records the audio to the specified output by ALSA utility: 'arecord'.

    @param output: The filename where the recorded audio will be stored to.
    @param duration: The length of the recording (in seconds).
    @param channels: The number of channels of the recorded audio.
    @param bits: The number of bits of each audio sample.
    @param rate: The sampling rate.
    @param device: The device used to recorded the audio from.
    @raise RuntimeError: If no record device is available.
    '''
    args = [ARECORD_PATH]
    if duration is not None:
        args += ['-d', str(duration)]
    args += _get_format_args(channels, bits, rate)
    if device is None:
        device = get_default_record_device()
        if device is None:
            raise RuntimeError('no record device')
    args += ['-D', device]
    args += [output]
    return args
