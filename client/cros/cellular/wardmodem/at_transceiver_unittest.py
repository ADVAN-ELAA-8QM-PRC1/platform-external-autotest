#!/usr/bin/env python

# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import at_transceiver

import logging
import mox
import os
import unittest

import at_channel
import task_loop

class ATTransceiverTestCase(unittest.TestCase):
    """
    Base test fixture for ATTransceiver class.

    """

    def setUp(self):
        self._mox = mox.Mox()

        # Create a temporary pty pair for the ATTransceiver constructor
        master, slave = os.openpty()

        self._at_transceiver = at_transceiver.ATTransceiver(slave, slave)

        # Now replace internal objects in _at_transceiver with mocks
        self._at_transceiver._modem_response_timeout_milliseconds = 0
        self._mock_modem_channel = self._mox.CreateMock(at_channel.ATChannel)
        self._at_transceiver._modem_channel = self._mock_modem_channel
        self._mock_mm_channel = self._mox.CreateMock(at_channel.ATChannel)
        self._at_transceiver._mm_channel = self._mock_mm_channel
        self._mock_task_loop = self._mox.CreateMock(task_loop.TaskLoop)
        self._at_transceiver._task_loop = self._mock_task_loop


    def test_successful_mode_selection(self):
        """
        Test that all modes can be selected, when both channels are provided.

        """
        self._at_transceiver.mode = at_transceiver.ATTransceiverMode.WARDMODEM
        self.assertEqual(self._at_transceiver.mode,
                         at_transceiver.ATTransceiverMode.WARDMODEM)
        self._at_transceiver.mode = (
                at_transceiver.ATTransceiverMode.PASS_THROUGH)
        self.assertEqual(self._at_transceiver.mode,
                         at_transceiver.ATTransceiverMode.PASS_THROUGH)
        self._at_transceiver.mode = (
               at_transceiver.ATTransceiverMode.SPLIT_VERIFY)
        self.assertEqual(self._at_transceiver.mode,
                         at_transceiver.ATTransceiverMode.SPLIT_VERIFY)

    def test_unsuccessful_mode_selection(self):
        """
        Test that only WARDMODEM mode can be selected if the modem channel is
        missing.

        """
        self._at_transceiver._modem_channel = None
        self._at_transceiver.mode = at_transceiver.ATTransceiverMode.WARDMODEM
        self.assertEqual(self._at_transceiver.mode,
                         at_transceiver.ATTransceiverMode.WARDMODEM)
        self._at_transceiver.mode = (
                at_transceiver.ATTransceiverMode.PASS_THROUGH)
        self.assertEqual(self._at_transceiver.mode,
                         at_transceiver.ATTransceiverMode.WARDMODEM)
        self._at_transceiver.mode = (
               at_transceiver.ATTransceiverMode.SPLIT_VERIFY)
        self.assertEqual(self._at_transceiver.mode,
                         at_transceiver.ATTransceiverMode.WARDMODEM)


class ATTransceiverWardModemTestCase(ATTransceiverTestCase):
    """
    Test ATTransceiver class in the WARDMODEM mode.

    """

    def setUp(self):
        super(ATTransceiverWardModemTestCase, self).setUp()
        self._at_transceiver.mode = at_transceiver.ATTransceiverMode.WARDMODEM


    def test_wardmodem_at_command(self):
        """
        Test the case when AT command is received from wardmodem.

        """
        at_command = 'AT+commmmmmmmmand'
        self._mock_mm_channel.send(at_command)

        self._mox.ReplayAll()
        self._at_transceiver._process_wardmodem_at_command(at_command)
        self._mox.VerifyAll()


    def test_mm_at_command(self):
        """
        Test the case when AT command is received from modem manager.

        """
        at_command = 'AT+commmmmmmmmand'
        self._mox.StubOutWithMock(self._at_transceiver,
                                  '_post_wardmodem_request')

        self._at_transceiver._post_wardmodem_request(at_command)

        self._mox.ReplayAll()
        self._at_transceiver._process_mm_at_command(at_command)
        self._mox.UnsetStubs()
        self._mox.VerifyAll()


class ATTransceiverPassThroughTestCase(ATTransceiverTestCase):
    """
    Test ATTransceiver class in the PASS_THROUGH mode.

    """

    def setUp(self):
        super(ATTransceiverPassThroughTestCase, self).setUp()
        self._at_transceiver.mode = (
                at_transceiver.ATTransceiverMode.PASS_THROUGH)


    def test_modem_at_command(self):
        """
        Test the case when AT command received from physical modem.

        """
        at_command = 'AT+commmmmmmmmand'
        self._mock_mm_channel.send(at_command)

        self._mox.ReplayAll()
        self._at_transceiver._process_modem_at_command(at_command)
        self._mox.VerifyAll()


    def test_mm_at_command(self):
        """
        Test the case when AT command is received from modem manager.

        """
        at_command = 'AT+commmmmmmmmand'
        self._mock_modem_channel.send(at_command)

        self._mox.ReplayAll()
        self._at_transceiver._process_mm_at_command(at_command)
        self._mox.VerifyAll()


class ATTransceiverSplitVerifyTestCase(ATTransceiverTestCase):
    """
    Test ATTransceiver class in the SPLIT_VERIFY mode.

    """

    def setUp(self):
        super(ATTransceiverSplitVerifyTestCase, self).setUp()
        self._at_transceiver.mode = (
                at_transceiver.ATTransceiverMode.SPLIT_VERIFY)


    def test_mm_at_command(self):
        """
        Test that that incoming modem manager command is multiplexed to
        wardmodem and physical modem.

        """
        at_command = 'AT+commmmmmmmmand'
        self._mox.StubOutWithMock(self._at_transceiver,
                                  '_post_wardmodem_request')
        self._mock_modem_channel.send(at_command).InAnyOrder()
        self._at_transceiver._post_wardmodem_request(at_command).InAnyOrder()

        self._mox.ReplayAll()
        self._at_transceiver._process_mm_at_command(at_command)
        self._mox.UnsetStubs()
        self._mox.VerifyAll()


    def test_successful_single_at_response_modem_wardmodem(self):
        """
        Test the case when one AT response is received successfully.
        In this case, physical modem command comes first.

        """
        at_command = 'AT+commmmmmmmmand'
        self._mock_mm_channel.send(at_command)

        self._mox.ReplayAll()
        self._at_transceiver._process_modem_at_command(at_command)
        self._at_transceiver._process_wardmodem_at_command(at_command)
        self._mox.VerifyAll()


    def test_successful_single_at_response_wardmodem_modem(self):
        """
        Test the case when one AT response is received successfully.
        In this case, wardmodem command comes first.

        """
        at_command = 'AT+commmmmmmmmand'
        task_id = 3
        self._mock_task_loop.post_task_after_delay(
                self._at_transceiver._modem_response_timed_out,
                mox.IgnoreArg()).AndReturn(task_id)
        self._mock_task_loop.cancel_posted_task(task_id)
        self._mock_mm_channel.send(at_command)

        self._mox.ReplayAll()
        self._at_transceiver._process_wardmodem_at_command(at_command)
        self._at_transceiver._process_modem_at_command(at_command)
        self._mox.VerifyAll()

    def test_mismatched_at_response(self):
        """
        Test the case when both responses arrive, but are not identical.

        """
        wardmodem_command = 'AT+wardmodem'
        modem_command = 'AT+modem'
        self._mox.StubOutWithMock(self._at_transceiver,
                                  '_report_verification_failure')
        self._at_transceiver._report_verification_failure(
                self._at_transceiver.VERIFICATION_FAILED_MISMATCH,
                modem_command,
                wardmodem_command)
        self._mock_mm_channel.send(wardmodem_command)

        self._mox.ReplayAll()
        self._at_transceiver._process_modem_at_command(modem_command)
        self._at_transceiver._process_wardmodem_at_command(wardmodem_command)
        self._mox.UnsetStubs()
        self._mox.VerifyAll()


    def test_modem_response_times_out(self):
        """
        Test the case when the physical modem fails to respond.

        """
        at_command = 'AT+commmmmmmmmand'
        task_id = 3
        self._mox.StubOutWithMock(self._at_transceiver,
                                  '_report_verification_failure')

        self._mock_task_loop.post_task_after_delay(
                self._at_transceiver._modem_response_timed_out,
                mox.IgnoreArg()).AndReturn(task_id)
        self._at_transceiver._report_verification_failure(
                self._at_transceiver.VERIFICATION_FAILED_TIME_OUT,
                None,
                at_command)
        self._mock_mm_channel.send(at_command)

        self._mox.ReplayAll()
        self._at_transceiver._process_wardmodem_at_command(at_command)
        self._at_transceiver._modem_response_timed_out()
        self._mox.UnsetStubs()
        self._mox.VerifyAll()


    def test_multiple_successful_responses(self):
        """
        Test the case two wardmodem responses are queued, and then two matching
        modem responses are received.

        """
        first_at_command = 'AT+first'
        second_at_command = 'AT+second'
        first_task_id = 3
        second_task_id = 4

        self._mock_task_loop.post_task_after_delay(
                self._at_transceiver._modem_response_timed_out,
                mox.IgnoreArg()).AndReturn(first_task_id)
        self._mock_task_loop.cancel_posted_task(first_task_id)
        self._mock_mm_channel.send(first_at_command)
        self._mock_task_loop.post_task_after_delay(
                self._at_transceiver._modem_response_timed_out,
                mox.IgnoreArg()).AndReturn(second_task_id)
        self._mock_task_loop.cancel_posted_task(second_task_id)
        self._mock_mm_channel.send(second_at_command)

        self._mox.ReplayAll()
        self._at_transceiver._process_wardmodem_at_command(first_at_command)
        self._at_transceiver._process_wardmodem_at_command(second_at_command)
        self._at_transceiver._process_modem_at_command(first_at_command)
        self._at_transceiver._process_modem_at_command(second_at_command)
        self._mox.VerifyAll()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
