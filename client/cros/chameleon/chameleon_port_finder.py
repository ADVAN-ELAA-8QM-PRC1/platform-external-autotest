# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
from collections import namedtuple

from autotest_lib.client.cros.chameleon import chameleon

ChameleonPorts = namedtuple('ChameleonPorts', 'connected failed')


class ChameleonPortFinder(object):
    """
    Responsible for finding all ports connected to the chameleon board.

    It does not verify if these ports are connected to DUT.

    """

    def __init__(self, chameleon_board):
        """
        @param chameleon_board: a ChameleonBoard object representing the
                                Chameleon board whose ports we are interested
                                in finding.

        """
        self.chameleon_board = chameleon_board
        self.connected = None
        self.failed = None


    def find_all_ports(self):
        """
        @returns a named tuple ChameleonPorts() containing a list of connected
                 ports as the first element and failed ports as second element.

        """
        connected_ports = self.chameleon_board.get_all_ports()
        dut_failed_ports = []

        return ChameleonPorts(connected_ports, dut_failed_ports)


    def find_port(self, interface):
        """
        @param interface: string, the interface. e.g: HDMI, DP, VGA
        @returns a ChameleonPort object if port is found, else None.

        """
        connected_ports = self.find_all_ports().connected

        for port in connected_ports:
            if port.get_connector_type().lower() == interface.lower():
                return port

        return None


    def __str__(self):
        ports_to_str = lambda ports: ', '.join(
                '%s(%d)' % (p.get_connector_type(), p.get_connector_id())
                for p in ports)

        if self.connected is None:
            text = 'No port information. Did you run find_all_ports()?'
        elif self.connected == []:
            text = 'No port detected on the Chameleon board.'
        else:
            text = ('Detected %d connected port(s): %s.\t'
                    % (len(self.connected), ports_to_str(self.connected)))

        if self.failed:
            text += ('DUT failed to detect Chameleon ports: %s'
                     % ports_to_str(self.failed))

        return text


class ChameleonInputFinder(ChameleonPortFinder):
    """
    Responsible for finding all input ports connected to the chameleon board.

    """

    def find_all_ports(self):
        """
        @returns a named tuple ChameleonPorts() containing a list of connected
                 input ports as the first element and failed ports as second
                 element.

        """
        connected_ports = self.chameleon_board.get_all_inputs()
        dut_failed_ports = []

        return ChameleonPorts(connected_ports, dut_failed_ports)


class ChameleonOutputFinder(ChameleonPortFinder):
    """
    Responsible for finding all output ports connected to the chameleon board.

    """

    def find_all_ports(self):
        """
        @returns a named tuple ChameleonPorts() containing a list of connected
                 output ports as the first element and failed ports as second
                 element.

        """
        connected_ports = self.chameleon_board.get_all_outputs()
        dut_failed_ports = []

        return ChameleonPorts(connected_ports, dut_failed_ports)


class ChameleonVideoInputFinder(ChameleonInputFinder):
    """
    Responsible for finding all video inputs connected to the chameleon board.

    It also verifies if these ports are connected to DUT.

    """

    def __init__(self, chameleon_board, display_facade):
        """
        @param chameleon_board: a ChameleonBoard object representing the
                                Chameleon board whose ports we are interested
                                in finding.
        @param display_facade: a display facade object, to access the DUT
                               display functionality, either locally or
                               remotely.

        """
        super(ChameleonVideoInputFinder, self).__init__(chameleon_board)
        self.display_facade = display_facade
        self._TIMEOUT_VIDEO_STABLE_PROBE = 10


    def find_all_ports(self):
        """
        @returns a named tuple ChameleonPorts() containing a list of connected
                 video inputs as the first element and failed ports as second
                 element.

        """
        connected_ports = []
        dut_failed_ports = []

        all_ports = super(ChameleonVideoInputFinder, self).find_all_ports()
        for port in all_ports.connected:
            # Skip the non-video port.
            if not port.has_video_support():
                continue

            video_port = chameleon.ChameleonVideoInput(port)
            connector_type = video_port.get_connector_type()
            # Try to plug the port such that DUT can detect it.
            was_plugged = video_port.plugged

            if not was_plugged:
                video_port.plug()
            # DUT takes some time to respond. Wait until the video signal
            # to stabilize.
            video_stable = video_port.wait_video_input_stable(
                    self._TIMEOUT_VIDEO_STABLE_PROBE)
            logging.info('Chameleon detected video input stable: %r',
                         video_stable)

            output = self.display_facade.get_external_connector_name()
            logging.info('CrOS detected external connector: %r', output)

            if video_stable and output and output.startswith(connector_type):
                connected_ports.append(video_port)
            else:
                dut_failed_ports.append(video_port)
                if video_stable:
                    if output:
                        logging.error('Unexpected display on CrOS: %s', output)
                    else:
                        logging.error('Display detection seems broken')
                else:
                    if output:
                        logging.error('Chameleon timed out waiting CrOS video')
                    else:
                        logging.error('CrOS failed to see any external display')

            # Unplug the port afterward if it wasn't plugged to begin with.
            if not was_plugged:
                video_port.unplug()

        if not connected_ports and not dut_failed_ports:
            logging.error('No video input port detected by Chameleon')

        self.connected = connected_ports
        self.failed = dut_failed_ports

        return ChameleonPorts(connected_ports, dut_failed_ports)


class ChameleonAudioInputFinder(ChameleonInputFinder):
    """
    Responsible for finding all audio inputs connected to the chameleon board.

    It does not verify if these ports are connected to DUT.

    """

    def find_all_ports(self):
        """
        @returns a named tuple ChameleonPorts() containing a list of connected
                 audio inputs as the first element and failed ports as second
                 element.

        """
        all_ports = super(ChameleonAudioInputFinder, self).find_all_ports()
        connected_ports = [chameleon.ChameleonAudioInput(port)
                           for port in all_ports.connected
                           if port.has_audio_support()]
        dut_failed_ports = []

        return ChameleonPorts(connected_ports, dut_failed_ports)
