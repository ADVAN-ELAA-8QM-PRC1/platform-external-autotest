# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

""" The autotest performing FW update, both EC and AP."""

import logging, os

from autotest_lib.client.common_lib import autotemp
from autotest_lib.server import test, utils

class fwupdate(test.test):
    version = 1

    def initialize(self, servo, board, fwurl):
        self.tmpd = autotemp.tempdir(unique_id='fwimage')
        tarball = os.path.basename(fwurl)
        utils.system('gsutil cp %s %s' % (fwurl, self.tmpd.name))
        self._ap_image = 'image-%s.bin' % board
        self._ec_image = 'ec.bin'
        self._board = board
        self._servo = servo
        utils.system('tar xf %s -C %s %s %s' % (
                os.path.join(self.tmpd.name, tarball), self.tmpd.name,
                self._ap_image, self._ec_image), timeout=60)

    def cleanup(self):
        self.tmpd.clean()

    def run_once(self):
        logging.info('Will re-program EC now')
        self._servo.program_ec(self._board,
                               os.path.join(self.tmpd.name, self._ec_image))
        logging.info('Will re-program bootprom now')
        self._servo.program_bootprom(
            self._board,
            os.path.join(self.tmpd.name, self._ap_image))
