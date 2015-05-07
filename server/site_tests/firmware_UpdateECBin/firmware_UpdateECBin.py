# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


import logging
import os
import time

from autotest_lib.client.common_lib import error, utils
from autotest_lib.server.cros import vboot_constants as vboot
from autotest_lib.server.cros.faft.firmware_test import FirmwareTest


class firmware_UpdateECBin(FirmwareTest):
    """
    This test verified the EC software sync. The EC binary is embedded in
    the BIOS image. On AP startup, AP verifies the EC by comparing the
    hash of the current EC with the hash of the embedded EC image. So
    updating EC is simple and we just need to change the EC binary on
    the BIOS image.

    This test requires a new EC image for update. The new EC image should
    be different with the existing EC image on the current BIOS. In normal
    cases, we use the ec_autest_image.bin from firmware_from_source.tar.bz2.
    The ec_autest_image.bin is the same binary as ec.bin but shift'ed and its
    version string has the "_shift" suffix.

    The new EC image should be specified by the new_ec argument, like:
      run_remote_tests.sh --args "new_ec=ec_autest_image.bin" ...

    The test covers RONORMAL->TWOSTOP, TWOSTOP->TWOSTOP, and
    TWOSTOP->RONORMAL updates.
    """
    version = 1

    def initialize(self, host, cmdline_args, dev_mode=False):
        # Parse arguments from command line
        dict_args = utils.args_to_dict(cmdline_args)
        if 'new_ec' not in dict_args or not os.path.isfile(dict_args['new_ec']):
            raise error.TestError(
                    'Should specify a valid new_ec image for update, like: '
                    'run_remote_tests.sh --args "new_ec=/path/to/'
                    'ec_autest_image.bin". The ec_autest_image.bin file is '
                    'included in the firmware_from_source.tar.bz2.')
        self.arg_new_ec = dict_args['new_ec']
        logging.info('The EC image to-be-updated is: %s', self.arg_new_ec)
        super(firmware_UpdateECBin, self).initialize(host, cmdline_args)
        self.backup_firmware()
        self.switcher.setup_mode('dev' if dev_mode else 'normal')
        self.setup_usbkey(usbkey=False)

        temp_path = self.faft_client.updater.get_temp_path()
        self.faft_client.updater.setup()

        self.old_bios_path = os.path.join(temp_path, 'old_bios.bin')
        self.faft_client.bios.dump_whole(self.old_bios_path)

        self.new_ec_path = os.path.join(temp_path, 'new_ec.bin')
        host.send_file(self.arg_new_ec, self.new_ec_path)

    def cleanup(self):
        self.restore_firmware()
        self.faft_client.updater.cleanup()
        super(firmware_UpdateECBin, self).cleanup()

    def do_ronormal_update(self):
        self.faft_client.bios.setup_EC_image(self.new_ec_path)
        self.new_ec_sha = self.faft_client.bios.get_EC_image_sha()
        self.faft_client.bios.update_EC_from_image('a', 0)

    def do_twostop_update(self):
        # We update the original BIOS image back. This BIOS image contains
        # the original EC binary. But set RW boot. So it is a TWOSTOP ->
        # TWOSTOP update.
        self.faft_client.bios.write_whole(self.old_bios_path)
        self.faft_client.bios.set_preamble_flags('a', 0)

    def ec_checker(self, use_new_ec):
        ro_normal_checker = self.checkers.ro_normal_checker('A', twostop=True)
        sha_now = self.faft_client.ec.get_firmware_sha()
        if use_new_ec:
            sha_checker = (sha_now == self.new_ec_sha)
        else:
            sha_checker = (sha_now != self.new_ec_sha)
        return (ro_normal_checker and sha_checker)

    def software_sync_and_ctrl_d(self):
        time.sleep(self.faft_config.software_sync)
        self.wait_dev_screen_and_ctrl_d()

    def run_once(self, dev_mode=False):
        if not self.check_ec_capability():
            raise error.TestNAError("Nothing needs to be tested on this device")

        flags = self.faft_client.bios.get_preamble_flags('a')
        if flags & vboot.PREAMBLE_USE_RO_NORMAL == 0:
            logging.info('The firmware USE_RO_NORMAL flag is disabled.')
            return

        logging.info("Expected EC RO boot, update EC and disable RO flag.")
        self.check_state((self.checkers.ro_normal_checker, 'A'))
        self.do_ronormal_update()
        self.switcher.mode_aware_reboot(wait_for_dut_up=False)
        if dev_mode:
            self.software_sync_and_ctrl_d()
        self.wait_for_kernel_up()

        logging.info("Expected new EC and RW boot, restore the original BIOS.")
        self.check_state((self.ec_checker, True))
        self.do_twostop_update()
        # We use warm reboot here to test the following EC behavior:
        #   If EC is already into RW before powering on the AP, the AP
        #   will need to get the EC into RO first. It does this by
        #   telling the EC to wait for the AP to shut down, reboot
        #   into RO, then power on the AP automatically.
        self.switcher.mode_aware_reboot(wait_for_dut_up=False)
        if dev_mode:
            self.software_sync_and_ctrl_d()
        self.wait_for_kernel_up()

        logging.info("Expected different EC and RW boot, enable RO flag.")
        self.check_state((self.ec_checker, False))
        self.faft_client.bios.set_preamble_flags(('a', flags))
        self.switcher.mode_aware_reboot()

        logging.info("Expected EC RO boot, done.")
        self.check_state((self.checkers.ro_normal_checker, 'A'))
