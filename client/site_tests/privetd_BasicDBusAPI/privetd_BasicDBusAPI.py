# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging

from autotest_lib.client.bin import test
from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros.tendo import privetd_helper
from autotest_lib.client.cros.tendo import privetd_dbus_helper

def check(value, expected, description):
    """Check that |value| == |expected|.

    @param value: actual value we found
    @param expected: expected value
    @param description: string description of what |value| is.

    """
    if value != expected:
        raise error.TestFail('Expected value of %s to be %r but got %r' %
                             (description, expected, value))


PAIRING_SESSION_ID_KEY = 'sessionId'


class privetd_BasicDBusAPI(test.test):
    """Check that basic privetd daemon DBus APIs are functional."""
    version = 1


    def run_once(self):
        """Test entry point."""
        # Initially, disable bootstapping.
        config = privetd_helper.PrivetdConfig(
                wifi_bootstrap_mode=privetd_helper.BOOTSTRAP_CONFIG_DISABLED,
                gcd_bootstrap_mode=privetd_helper.BOOTSTRAP_CONFIG_DISABLED,
                log_verbosity=3,
                disable_pairing_security=True)
        privetd = privetd_dbus_helper.make_dbus_helper(config)

        check(privetd.manager.Ping(), 'Hello world!', 'ping response')
        check(privetd.wifi_bootstrap_status,
              privetd_helper.WIFI_BOOTSTRAP_STATE_DISABLED,
              'wifi bootstrap status')
        check(privetd.pairing_info, {}, 'pairing info')
        # But we should still be able to pair.
        helper = privetd_helper.PrivetdHelper()
        data = {'pairing': 'embeddedCode', 'crypto': 'none'}
        pairing = helper.send_privet_request(privetd_helper.URL_PAIRING_START,
                                             request_data=data)
        # And now we should be able to see a pin code in our pairing status.
        pairing_info = privetd.pairing_info
        logging.debug(pairing_info)
        check(pairing_info.get(PAIRING_SESSION_ID_KEY, ''),
              pairing[PAIRING_SESSION_ID_KEY],
              'session id')
        if not 'code' in pairing_info:
            raise error.TestFail('No code in pairing info (%r)' % pairing_info)
        # And if we start a new pairing session, the session ID should change.
        old_session_id = pairing_info[PAIRING_SESSION_ID_KEY]
        pairing = helper.send_privet_request(privetd_helper.URL_PAIRING_START,
                                             request_data=data)
        if pairing[PAIRING_SESSION_ID_KEY] == old_session_id:
            raise error.TestFail('Session IDs should change on each new '
                                 'pairing attempt.')
        # And if we start and complete a pairing session, we should have no
        # pairing information exposed.
        helper.privet_auth()
        check(privetd.pairing_info, {}, 'pairing info')

        # Then enable bootstrapping, and check that we're waiting for creds.
        config.wifi_bootstrap_mode = privetd_helper.BOOTSTRAP_CONFIG_AUTOMATIC
        privetd = privetd_dbus_helper.make_dbus_helper(config)
        check(privetd.wifi_bootstrap_status,
              privetd_helper.WIFI_BOOTSTRAP_STATE_WAITING,
              'wifi bootstrap status')


    def clean(self):
        """Clean up processes altered during the test."""
        privetd_helper.PrivetdConfig.naive_restart()

