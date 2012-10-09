# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import pexpect

from autotest_lib.client.common_lib import error
from autotest_lib.server.cros.faftsequence import FAFTSequence

class firmware_ECPeci(FAFTSequence):
    """
    Servo based EC PECI test.
    """
    version = 1

    # Repeat read count
    READ_COUNT = 200

    def _check_read(self):
        """Read CPU temperature through PECI.

        Raises:
          error.TestFail: Raised when read fails.
        """
        try:
            t = int(self.send_uart_command_get_output("pecitemp",
                    ["CPU temp = (\d+) K"])[0][1])
            if t < 273 or t > 400:
                raise error.TestFail("Abnormal CPU temperature %d K" % t)
        except pexpect.TIMEOUT:
            raise error.TestFail("Error reading PECI CPU temperature")


    def run_once(self, host=None):
        if not self.check_ec_capability(['peci']):
            return
        logging.info("Reading PECI CPU temperature for %d times." %
                     self.READ_COUNT)
        for i in xrange(self.READ_COUNT):
            self._check_read()
