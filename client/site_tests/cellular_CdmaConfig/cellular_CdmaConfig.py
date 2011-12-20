# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


from autotest_lib.client.bin import test
from autotest_lib.client.cros.cellular import cellular, cell_tools

import logging

from autotest_lib.client.cros import flimflam_test_path
import mm


class cellular_CdmaConfig(test.test):
    version = 1

    def run_once(self):
        manager = mm.ModemManager()
        modem_path = cell_tools.FactoryResetModem('')
        logging.info('After factory reset: status is: %s' %
                     manager.SimpleModem(modem_path).GetStatus())

        # PrepareModemForTechnology checks that it has succeeded, so a
        # successful return from here means that it worked.
        new_path = cell_tools.PrepareModemForTechnology(
            modem_path, cellular.Technology.CDMA_2000)

        logging.info('After PrepareModemForTechnology: status is: %s' %
                     manager.SimpleModem(new_path).GetStatus())
