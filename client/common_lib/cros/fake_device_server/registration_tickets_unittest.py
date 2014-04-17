#! /usr/bin/python

# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for registration_tickets.py."""

import mox
import unittest

import common
from cros_lib.fake_device_server import common_util
from cros_lib.fake_device_server import commands
from cros_lib.fake_device_server import devices
from cros_lib.fake_device_server import registration_tickets
from cros_lib.fake_device_server import resource_delegate
from cros_lib.fake_device_server import server_errors


class RegistrationTicketsTest(mox.MoxTestBase):
    """Tests for the RegistrationTickets class."""

    def setUp(self):
        """Sets up mox and a ticket / registration objects."""
        mox.MoxTestBase.setUp(self)
        self.tickets = {}
        self.devices_resource = {}
        self.commands = commands.Commands(
                resource_delegate.ResourceDelegate({}))
        self.devices = devices.Devices(
                resource_delegate.ResourceDelegate(self.devices_resource),
                self.commands)

        self.registration = registration_tickets.RegistrationTickets(
                resource_delegate.ResourceDelegate(self.tickets), self.devices)


    def testFinalize(self):
        """Tests that the finalize workflow does the right thing."""
        # Unclaimed ticket
        self.tickets[(1234, None)] = dict(id=1234)
        self.assertRaises(server_errors.HTTPError,
                          self.registration.POST, 1234, 'finalize')

        # Claimed ticket
        expected_ticket = dict(id=1234, userEmail='buffet@tasty.org',
                               systemName='buffet_device', deviceKind='vendor',
                               channel=dict(supportedType='xmpp'))
        self.tickets[(1234, None)] = expected_ticket
        returned_json = self.registration.POST(1234, 'finalize')
        self.assertEquals(returned_json['id'], expected_ticket['id'])
        self.assertEquals(returned_json['userEmail'],
                          expected_ticket['userEmail'])
        self.assertIn('robotAccountEmail', returned_json)
        self.assertIn('robotAccountAuthorizationCode', returned_json)


    def testClaim(self):
        """Tests that we can claim a ticket."""
        self.tickets[(1234, None)] = dict(id=1234)
        self.mox.StubOutWithMock(common_util, 'grab_header_field')
        self.mox.StubOutWithMock(common_util, 'parse_serialized_json')
        update_ticket = dict(userEmail='me')
        common_util.parse_serialized_json().AndReturn(update_ticket)
        common_util.grab_header_field('Authorization').AndReturn(
                'Bearer %s' % self.registration.TEST_ACCESS_TOKEN)

        self.mox.ReplayAll()
        returned_json = self.registration.PATCH(1234)
        self.assertIn('userEmail', returned_json)
        # This should have changed to an actual user.
        self.assertNotEquals(returned_json['userEmail'], 'me')
        self.mox.VerifyAll()


    def testInsert(self):
        """Tests that we can create a new ticket."""
        self.mox.StubOutWithMock(common_util, 'parse_serialized_json')
        common_util.parse_serialized_json().AndReturn(None)

        self.mox.ReplayAll()
        returned_json = self.registration.POST()
        self.assertIn('id', returned_json)
        self.mox.VerifyAll()


    def testGet(self):
        """Tests that we can retrieve a ticket correctly."""
        self.tickets[(1234, None)] = dict(id=1234)
        returned_json = self.registration.GET(1234)
        self.assertEquals(returned_json, self.tickets[(1234, None)])

        # Non-existing ticket.
        self.assertRaises(server_errors.HTTPError,
                          self.registration.GET, 1235)


    def testPatchTicket(self):
        """Tests that we correctly patch a ticket."""
        expected_ticket = dict(id=1234, blah='hi')
        update_ticket = dict(blah='hi')
        self.tickets[(1234, None)] = dict(id=1234)

        self.mox.StubOutWithMock(common_util, 'parse_serialized_json')

        common_util.parse_serialized_json().AndReturn(update_ticket)

        self.mox.ReplayAll()
        returned_json = self.registration.PATCH(1234)
        self.assertEquals(expected_ticket, returned_json)
        self.mox.VerifyAll()


    def testReplaceTicket(self):
        """Tests that we correctly replace a ticket."""
        update_ticket = dict(id=12345, blah='hi')
        self.tickets[(12345, None)] = dict(id=12345)

        self.mox.StubOutWithMock(common_util, 'parse_serialized_json')

        common_util.parse_serialized_json().AndReturn(update_ticket)

        self.mox.ReplayAll()
        returned_json = self.registration.PUT(12345)
        self.assertEquals(update_ticket, returned_json)
        self.mox.VerifyAll()

        self.mox.ResetAll()

        # Ticket id doesn't match.
        update_ticket = dict(id=12346, blah='hi')
        common_util.parse_serialized_json().AndReturn(update_ticket)

        self.mox.ReplayAll()
        self.assertRaises(server_errors.HTTPError,
                          self.registration.PUT, 12345)
        self.mox.VerifyAll()


if __name__ == '__main__':
    unittest.main()
