# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This module provides the audio board interface."""

import logging

from autotest_lib.client.cros.chameleon import chameleon_audio_ids as ids


class AudioBoard(object):
    """AudioBoard is an abstraction of an audio board on a Chameleon board.

    It provides methods to control audio board.

    A ChameleonConnection object is passed to the construction.

    """
    def __init__(self, chameleon_connection):
        """Constructs an AudioBoard.

        @param chameleon_connection: A ChameleonConnection object.

        """
        self._audio_buses = {
                1: AudioBus(1, chameleon_connection),
                2: AudioBus(2, chameleon_connection)}

        self._jack_plugger = None
        try:
            self._jack_plugger = AudioJackPlugger(chameleon_connection)
        except AudioJackPluggerException:
            logging.warning(
                    'There is no jack plugger on this audio board. '
                    'Use DummyAudioJackPlugger instead')
            self._jack_plugger = DummyAudioJackPlugger()

        self._bluetooth_controller = BluetoothController(chameleon_connection)


    def get_audio_bus(self, bus_index):
        """Gets an audio bus on this audio board.

        @param bus_index: The bus index 1 or 2.

        @returns: An AudioBus object.

        """
        return self._audio_buses[bus_index]


    def get_jack_plugger(self):
        """Gets an AudioJackPlugger on this audio board.

        @returns: An AudioJackPlugger object if there is an audio jack plugger.
                  A DummyAudioJackPlugger object if there is no audio jack
                  plugger.

        """
        return self._jack_plugger


    def get_bluetooth_controller(self):
        """Gets an BluetoothController on this audio board.

        @returns: An BluetoothController object.

        """
        return self._bluetooth_controller


class AudioBus(object):
    """AudioBus is an abstraction of an audio bus on an audio board.

    It provides methods to control audio bus.

    A ChameleonConnection object is passed to the construction.

    @properties:
        bus_index: The bus index 1 or 2.

    """
    # Maps port id defined in chameleon_audio_ids to endpoint name used in
    # chameleond audio bus API.
    _PORT_ID_AUDIO_BUS_ENDPOINT_MAP = {
            ids.ChameleonIds.LINEIN: 'Chameleon FPGA line-in',
            ids.ChameleonIds.LINEOUT: 'Chameleon FPGA line-out',
            ids.CrosIds.HEADPHONE: 'Cros device headphone',
            ids.CrosIds.EXTERNAL_MIC: 'Cros device external microphone',
            ids.PeripheralIds.SPEAKER: 'Peripheral speaker',
            ids.PeripheralIds.MIC: 'Peripheral microphone'}

    def __init__(self, bus_index, chameleon_connection):
        """Constructs an AudioBus.

        @param bus_index: The bus index 1 or 2.
        @param chameleon_connection: A ChameleonConnection object.

        """
        self.bus_index = bus_index
        self._chameleond_proxy = chameleon_connection.chameleond_proxy


    def _get_endpoint_name(self, port_id):
        """Gets the endpoint name used in audio bus API.

        @param port_id: A string, that is, id in ChameleonIds, CrosIds, or
                        PeripheralIds defined in chameleon_audio_ids.

        @returns: The endpoint name for the port used in audio bus API.

        """
        return self._PORT_ID_AUDIO_BUS_ENDPOINT_MAP[port_id]


    def connect(self, port_id):
        """Connects an audio port to this audio bus.

        @param port_id: A string, that is, id in ChameleonIds, CrosIds, or
                        PeripheralIds defined in chameleon_audio_ids.

        """
        endpoint = self._get_endpoint_name(port_id)
        self._chameleond_proxy.AudioBoardConnect(self.bus_index, endpoint)


    def disconnect(self, port_id):
        """Disconnects an audio port from this audio bus.

        @param port_id: A string, that is, id in ChameleonIds, CrosIds, or
                        PeripheralIds defined in chameleon_audio_ids.

        """
        endpoint = self._get_endpoint_name(port_id)
        self._chameleond_proxy.AudioBoardDisconnect(self.bus_index, endpoint)


class AudioJackPluggerException(Exception):
    """Errors in AudioJackPlugger."""
    pass


class AudioJackPlugger(object):
    """AudioJackPlugger is an abstraction of plugger controlled by audio board.

    There is a motor in the audio box which can plug/unplug 3.5mm 4-ring
    audio cable to/from audio jack of Cros deivce.
    This motor is controlled by audio board.

    A ChameleonConnection object is passed to the construction.

    """
    def __init__(self, chameleon_connection):
        """Constructs an AudioJackPlugger.

        @param chameleon_connection: A ChameleonConnection object.

        @raises:
            AudioJackPluggerException if there is no jack plugger on
            this audio board.

        """
        self._chameleond_proxy = chameleon_connection.chameleond_proxy
        if not self._chameleond_proxy.AudioBoardHasJackPlugger():
            raise AudioJackPluggerException(
                'There is no jack plugger on audio board. '
                'Perhaps the audio board is not connected to audio box.')


    def plug(self):
        """Plugs the audio cable into audio jack of Cros device."""
        self._chameleond_proxy.AudioBoardAudioJackPlug()
        logging.info('Plugged 3.5mm audio cable to Cros device')


    def unplug(self):
        """Unplugs the audio cable from audio jack of Cros device."""
        self._chameleond_proxy.AudioBoardAudioJackUnplug()
        logging.info('Unplugged 3.5mm audio cable from Cros device')


class DummyAudioJackPlugger(object):
    """An abstraction of plugger whose state remains plugged.

    In the case where there is no audio box, the 3.5mm 4-ring audio cable
    should be plugged to Cros device and remains there.
    This dummy plugger only logs messages and does nothing upon the request
    to plug/unplug.
    """
    def __init__(self):
        """Constructs a DummyAudioJackPlugger."""
        logging.info(
                'Init a DummyAudioJackPlugger which assumes 3.5mm audio '
                'cable is always plugged to Cros device.')
        pass


    def plug(self):
        """Plugs the audio cable into audio jack of Cros device."""
        logging.info(
                'Do nothing as DummyAudioJackPlugger has audio jack '
                'always plugged.')


    def unplug(self):
        """Unplugs the audio cable from audio jack of Cros device."""
        logging.warning(
                'Do nothing as DummyAudioJackPlugger has audio jack '
                'always plugged.')


class BluetoothController(object):
    """An abstraction of bluetooth module on audio board.

    There is a bluetooth module on the audio board. It can be controlled through
    API provided by chameleon proxy.

    """
    def __init__(self, chameleon_connection):
        """Constructs an BluetoothController.

        @param chameleon_connection: A ChameleonConnection object.

        """
        self._chameleond_proxy = chameleon_connection.chameleond_proxy


    def reset(self):
        """Resets the bluetooth module."""
        self._chameleond_proxy.AudioBoardResetBluetooth()
        logging.info('Resets bluetooth module on audio board.')


    def disable(self):
        """Disables the bluetooth module."""
        self._chameleond_proxy.AudioBoardDisableBluetooth()
        logging.info('Disables bluetooth module on audio board.')
