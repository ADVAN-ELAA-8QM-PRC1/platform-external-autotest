# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""
MBIM_CID_DEVICE_SERVICES Sequence

Reference:
    [1] Universal Serial Bus Communication Class MBIM Compliance Testing: 22
        http://www.usb.org/developers/docs/devclass_docs/MBIM-Compliance-1.0.pdf
"""
import common
from autotest_lib.client.cros.cellular.mbim_compliance import mbim_channel
from autotest_lib.client.cros.cellular.mbim_compliance import mbim_constants
from autotest_lib.client.cros.cellular.mbim_compliance import mbim_control
from autotest_lib.client.cros.cellular.mbim_compliance import mbim_errors
from autotest_lib.client.cros.cellular.mbim_compliance.sequences \
        import sequence


class MBIMCIDDeviceServicesSequence(sequence.Sequence):
    """
    Implement |MBIMCIDDeviceServicesSequence|.
    In this sequence, cid |MBIM_CID_DEVICE_SERVICES| is used to query the device
    services supported by the MBIM devices and their properties.
    """

    def run_internal(self):
        """ Run the MBIM_CID_DEVICE_SERVICES Sequence. """
        # Step 1
        command_message = mbim_control.MBIMCommandMessage(
                device_service_id=mbim_control.UUID_BASIC_CONNECT.bytes,
                cid=mbim_constants.MBIM_CID_DEVICE_SERVICES,
                command_type=mbim_control.COMMAND_TYPE_QUERY,
                information_buffer_length=0)
        packets = command_message.generate_packets()
        device_context = self.device_context
        channel = mbim_channel.MBIMChannel(
                device_context._device,
                device_context.mbim_communication_interface.bInterfaceNumber,
                device_context.interrupt_endpoint.bEndpointAddress,
                device_context.max_control_transfer_size)
        response_packets = channel.bidirectional_transaction(*packets)
        channel.close()

        # Step 2
        response_message = mbim_control.parse_response_packets(response_packets)

        # Step 3
        if ((response_message.message_type ==
             mbim_constants.MBIM_COMMAND_DONE) and
            (response_message.status_codes !=
             mbim_constants.MBIM_STATUS_SUCCESS)):
            mbim_errors.log_and_raise(mbim_errors.MBIMComplianceAssertionError,
                                      'mbim1.0:9.4.3')

        return command_message, response_message
