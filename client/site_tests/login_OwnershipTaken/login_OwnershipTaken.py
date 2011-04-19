# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import dbus
import dbus.glib
import logging
import sys
import os
from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros import constants, cros_ui_test, ownership, login


class login_OwnershipTaken(cros_ui_test.UITest):
    version = 1

    def setup(self):
        os.chdir(self.srcdir)
        utils.make('OUT_DIR=.')


    def initialize(self, creds='$default'):
        self.auto_login = False  # Will log in manually later.
        super(login_OwnershipTaken, self).initialize(creds,
                                                     is_creating_owner=True)
        if os.access(constants.OWNER_KEY_FILE, os.F_OK):
            raise error.TestFail("Ownership already taken!")
        self.login(self.username, self.password)


    def run_once(self):
        login.wait_for_ownership()

        sm = ownership.connect_to_session_manager()

        retrieved_policy = sm.RetrievePolicy(byte_arrays=True)
        if retrieved_policy is None:
            raise error.TestFail('Policy not found')

        # Pull in protobuf definitions.
        sys.path.append(self.srcdir)
        from device_management_backend_pb2 import PolicyFetchResponse
        from device_management_backend_pb2 import PolicyData
        from chrome_device_policy_pb2 import ChromeDeviceSettingsProto
        from chrome_device_policy_pb2 import UserWhitelistProto

        policy_proto = PolicyFetchResponse()
        policy_proto.ParseFromString(retrieved_policy)
        poldata = PolicyData()
        poldata.ParseFromString(policy_proto.policy_data)
        if (not poldata.HasField('username') or
            poldata.username != self.username):
            raise error.TestFail('Username not appropriately set in policy')

        polval = ChromeDeviceSettingsProto()
        polval.ParseFromString(poldata.policy_value)
        if (not polval.HasField('allow_new_users') or
            not polval.allow_new_users.HasField('allow_new_users') or
            not polval.allow_new_users):
            raise error.TestFail('Whitelisting not disabled in policy')

        if (not polval.HasField('user_whitelist') or
            not self.username in polval.user_whitelist.user_whitelist):
            raise error.TestFail('Owner not whitelisted')
