# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from autotest_lib.client.common_lib import error
from autotest_lib.server.cros.bluetooth import bluetooth_test

class bluetooth_SDP_ServiceAttributeRequest(bluetooth_test.BluetoothTest):
    """
    Verify the correct behaviour of the device when searching for attributes of
    services.
    """
    version = 1

    MAX_REC_CNT                      = 3
    MAX_ATTR_BYTE_CNT                = 300

    SDP_SERVER_CLASS_ID              = 0x1000
    SERVICE_RECORD_HANDLE_ATTR_ID    = 0x0000

    GAP_CLASS_ID                     = 0x1800
    BROWSE_GROUP_LIST_ATTR_ID        = 0x0005
    PUBLIC_BROWSE_ROOT               = 0x1002


    def get_single_handle(self, class_id):
        """Send a Service Search Request to get a handle for specific class ID.

        @return -1 if request failed, record handle as int otherwise

        """
        res = self.tester.service_search_request([class_id], self.MAX_REC_CNT)
        if not (isinstance(res, list) and len(res) > 0):
            return -1
        return res[0]


    def test_record_handle_attribute(self):
        """Implementation of test TP/SERVER/SA/BV-01-C from SDP Specification.

        @return True if test passes, False if test fails

        """
        # Send Service Search Request to find out record handle for
        # SDP Server service.
        record_handle = self.get_single_handle(self.SDP_SERVER_CLASS_ID)
        if record_handle == -1:
            return False

        # Send Service Attribute Request for Service Record Handle Attribute.
        res = self.tester.service_attribute_request(
                  record_handle,
                  self.MAX_ATTR_BYTE_CNT,
                  [self.SERVICE_RECORD_HANDLE_ATTR_ID])

        # Ensure that returned attribute is correct.
        return res == [self.SERVICE_RECORD_HANDLE_ATTR_ID, record_handle]


    def test_browse_group_attribute(self):
        """Implementation of test TP/SERVER/SA/BV-08-C from SDP Specification.

        @return True if test passes, False if test fails

        """
        record_handle = self.get_single_handle(self.GAP_CLASS_ID)
        if record_handle == -1:
            return False

        res = self.tester.service_attribute_request(
                  record_handle,
                  self.MAX_ATTR_BYTE_CNT,
                  [self.BROWSE_GROUP_LIST_ATTR_ID])

        return res == [self.BROWSE_GROUP_LIST_ATTR_ID,
                       [self.PUBLIC_BROWSE_ROOT]]


    def correct_request(self):
        """Run basic tests for Service Attribute Request.

        @return True if all tests finishes correctly, False otherwise

        """
        # Connect to the DUT via L2CAP using SDP socket.
        self.tester.connect(self.adapter['Address'])

        return (self.test_record_handle_attribute() and
                self.test_browse_group_attribute())


    def run_once(self):
        # Reset the adapter to the powered on, discoverable state.
        if not (self.device.reset_on() and
                self.device.set_discoverable(True)):
            raise error.TestFail('DUT could not be reset to initial state')

        self.adapter = self.device.get_adapter_properties()

        # Setup the tester as a generic computer.
        if not self.tester.setup('computer'):
            raise error.TestFail('Tester could not be initialized')

        # Since radio is involved, this test is not 100% reliable; instead we
        # repeat a few times until it succeeds.
        for failed_attempts in range(0, 5):
            if self.correct_request():
                break
        else:
            raise error.TestFail('Expected device was not found')

        # Record how many attempts this took, hopefully we'll one day figure out
        # a way to reduce this to zero and then the loop above can go away.
        self.write_perf_keyval({'failed_attempts': failed_attempts })
