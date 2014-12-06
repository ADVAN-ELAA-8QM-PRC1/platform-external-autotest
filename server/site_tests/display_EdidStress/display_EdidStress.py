# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This is a server side stressing DUT by switching Chameleon EDID."""

import glob
import logging
import os

from autotest_lib.client.common_lib import error
from autotest_lib.client.cros.chameleon import edid
from autotest_lib.server.cros.chameleon import chameleon_test


class display_EdidStress(chameleon_test.ChameleonTest):
    """Server side external display test.

    This test switches Chameleon EDID from among a large pool of EDIDs, tests
    DUT recognizes the emulated monitor and emits the correct video signal to
    Chameleon.
    """
    version = 1

    _EDID_TYPES = {'HDMI': {'HDMI', 'MHL', 'DVI'},
                   'DP': {'DP'},
                   'VGA': {'VGA'}}

    def initialize(self, host):
        super(display_EdidStress, self).initialize(host)
        self.backup_edid()


    def cleanup(self):
        super(display_EdidStress, self).cleanup()
        self.restore_edid()


    def run_once(self, host):
        edid_path = os.path.join(self.bindir, 'test_data', 'edids', '*')
        logging.info('See the display on Chameleon: port %d (%s)',
                     self.chameleon_port.get_connector_id(),
                     self.chameleon_port.get_connector_type())

        connector = self.chameleon_port.get_connector_type()
        supported_types = self._EDID_TYPES[connector]

        def _get_edid_type(s):
            i = s.rfind('_') + 1
            j = len(s) - len('.txt')
            return s[i:j].upper()

        failed_edids = []
        for filepath in glob.glob(edid_path):
            filename = os.path.basename(filepath)
            edid_type = _get_edid_type(filename)
            if edid_type not in supported_types:
                logging.info('Skip EDID: %s...', filename)
                continue

            logging.info('Apply EDID: %s...', filename)
            self.chameleon_port.apply_edid(
                    edid.Edid.from_file(filepath, skip_verify=True))

            framebuffer_resolution = (0, 0)
            try:
                self.reconnect_output()
                framebuffer_resolution = (
                        self.display_facade.get_external_resolution())
            except error.TestFail as e:
                logging.warning(e)

            if framebuffer_resolution == (0, 0):
                logging.error('EDID not supported: %s', filename)
                failed_edids.append(filename)
                continue

            if self.screen_test.test_resolution(framebuffer_resolution):
                logging.error('EDID not supported: %s', filename)
                failed_edids.append(filename)

        if failed_edids:
            message = ('Total %d EDIDs not supported: ' % len(failed_edids) +
                       ', '.join(failed_edids))
            logging.error(message)
            raise error.TestFail(message)
