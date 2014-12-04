# Copyright 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""
Connect Sequence

Reference:
    [1] Universal Serial Bus Communication Class MBIM Compliance Testing: 20
        http://www.usb.org/developers/docs/devclass_docs/MBIM-Compliance-1.0.pdf
"""
import array
import common

from autotest_lib.client.cros.cellular.mbim_compliance import mbim_channel
from autotest_lib.client.cros.cellular.mbim_compliance \
        import mbim_command_message
from autotest_lib.client.cros.cellular.mbim_compliance import mbim_constants
from autotest_lib.client.cros.cellular.mbim_compliance import mbim_errors
from autotest_lib.client.cros.cellular.mbim_compliance \
        import mbim_message_request
from autotest_lib.client.cros.cellular.mbim_compliance \
        import mbim_message_response
from autotest_lib.client.cros.cellular.mbim_compliance.sequences \
        import sequence


class ConnectSequence(sequence.Sequence):
    """ Implement the Connect Sequence. """

    def run_internal(self):
        """
        Run the Connect Sequence.

        Once the command message is sent, there should be at least one
        notification received apart from the command done message.

        @returns command_message: The command message sent to device.
                |command_message| is a MBIMCommandMessage object.
        @returns response_message: The response to the |command_message|.
                |response_message| is a MBIMCommandDoneMessage object.
        @returns notifications: The list of notifications message sent from the
                modem to the host. |notifications| is a list of
                |MBIMIndicateStatusMessage| objects.
        """
        # Step 1
        # Send MBIM_COMMAND_MSG.
        context_type = mbim_constants.MBIM_CONTEXT_TYPE_INTERNET.bytes
        data_buffer = array.array('B', 'loopback'.encode('utf-16le'))
        information_buffer_length = (
                mbim_command_message.MBIMSetConnect.get_struct_len())
        information_buffer_length += len(data_buffer)
        device_context = self.device_context
        descriptor_cache = device_context.descriptor_cache

        command_message = (
                mbim_command_message.MBIMSetConnect(session_id=0,
                        activation_command=1,
                        access_string_offset=60,
                        access_string_size=16,
                        user_name_offset=0,
                        user_name_size=0,
                        password_offset=0,
                        password_size=0,
                        compression=0,
                        auth_protocol=0,
                        ip_type=1,
                        context_type=context_type,
                        information_buffer_length=information_buffer_length,
                        payload_buffer=data_buffer))
        packets = mbim_message_request.generate_request_packets(
                command_message,
                descriptor_cache.mbim_functional.wMaxControlMessage)
        channel = mbim_channel.MBIMChannel(
                device_context._device,
                descriptor_cache.mbim_communication_interface.bInterfaceNumber,
                descriptor_cache.interrupt_endpoint.bEndpointAddress,
                descriptor_cache.mbim_functional.wMaxControlMessage)
        response_packets = channel.bidirectional_transaction(*packets)
        notifications_packets = channel.get_outstanding_packets();
        channel.close()

        # Step 2
        response_message = mbim_message_response.parse_response_packets(
                response_packets)
        notifications = []
        for notification_packets in notifications_packets:
            notifications.append(
                    mbim_message_response.parse_response_packets(
                            notification_packets))

        # Step 3
        if (response_message.message_type != mbim_constants.MBIM_COMMAND_DONE or
            response_message.status_codes != mbim_constants.MBIM_STATUS_SUCCESS):
            mbim_errors.log_and_raise(mbim_errors.MBIMComplianceSequenceError,
                                      'Connect sequence failed.')

        return command_message, response_message, notifications
