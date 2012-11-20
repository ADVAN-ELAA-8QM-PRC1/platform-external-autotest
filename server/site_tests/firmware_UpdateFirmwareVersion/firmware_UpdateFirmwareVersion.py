# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
from autotest_lib.server import utils
from autotest_lib.server.cros.faftsequence import FAFTSequence
from autotest_lib.client.common_lib import error


class firmware_UpdateFirmwareVersion(FAFTSequence):
    """
    Servo based firmware update test which checks the firmware version.

    This test requires a USB disk plugged-in, which contains a Chrome OS
    install shim (built by "build_image factory_install"). The firmware id of
    the current running firmware must matches the system shellball's, or user
    can provide a shellball to do this test. In this way, the client will be
    update with the given shellball first. On runtime, this test modifies the
    firmware version of the shellball and runs autoupdate. Check firmware
    version after boot with firmware B, and then recover firmware A and B to
    original shellball.
    """
    version = 1

    def check_firmware_version(self, expected_ver):
        actual_ver = self.faft_client.get_firmware_version('a')
        actual_tpm_fwver = self.faft_client.get_tpm_firmware_version()
        if actual_ver != expected_ver or actual_tpm_fwver != expected_ver:
            raise error.TestFail(
                'Firmware version should be %s,'
                'but got (fwver, tpm_fwver) = (%s, %s).' %
                (expected_ver, actual_ver, actual_tpm_fwver))
        else:
            logging.info(
                'Update success, now version is %s',
                actual_ver)


    def check_version_and_run_recovery(self):
        self.check_firmware_version(self._update_version)
        self.faft_client.run_firmware_recovery()


    def initialize(self, host, cmdline_args, use_pyauto=False, use_faft=True):
        dict_args = utils.args_to_dict(cmdline_args)
        self.use_shellball = dict_args.get('shellball', None)
        super(firmware_UpdateFirmwareVersion, self).initialize(
            host, cmdline_args, use_pyauto, use_faft)

    def setup(self):
        self.backup_firmware()
        updater_path = self.setup_firmwareupdate_shellball(self.use_shellball)
        self.faft_client.setup_firmwareupdate_temp_dir(updater_path)

        # Update firmware if needed
        if updater_path:
            self.faft_client.run_firmware_factory_install()
            self.sync_and_warm_reboot()
            self.wait_for_client_offline()
            self.wait_for_client()

        super(firmware_UpdateFirmwareVersion, self).setup()
        self.setup_usbkey(usbkey=True, host=False, install_shim=True)
        self.setup_dev_mode(dev_mode=False)
        self._fwid = self.faft_client.retrieve_shellball_fwid()

        actual_ver = self.faft_client.get_firmware_version('a')
        logging.info('Origin version is %s', actual_ver)
        self._update_version = actual_ver + 1
        logging.info('Firmware version will update to version %s',
            self._update_version)

        self.faft_client.resign_firmware(self._update_version)
        self.faft_client.repack_firmwareupdate_shellball('test')

    def cleanup(self):
        self.faft_client.cleanup_firmwareupdate_temp_dir()
        self.restore_firmware()
        self.invalidate_firmware_setup()
        super(firmware_UpdateFirmwareVersion, self).cleanup()


    def run_once(self):
        self.register_faft_sequence((
            {   # Step 1, Update firmware with new version.
                'state_checker': (self.checkers.crossystem_checker, {
                    'mainfw_act': 'A',
                    'mainfw_type': 'normal',
                    'tried_fwb': '0',
                    'fwid': self._fwid
                }),
                'userspace_action': (
                     self.faft_client.run_firmware_autoupdate,
                     'test'
                )
            },
            {   # Step2, Copy firmware form B to A.
                'state_checker': (self.checkers.crossystem_checker, {
                    'mainfw_act': 'B',
                    'tried_fwb': '1'
                }),
                'userspace_action': (self.faft_client.run_firmware_bootok,
                                     'test')
            },
            {   # Step3, Check firmware and TPM version, then recovery.
                'state_checker': (self.checkers.crossystem_checker, {
                    'mainfw_act': 'A',
                    'tried_fwb': '0'
                }),
                'userspace_action': (self.check_version_and_run_recovery),
                'reboot_action': (
                    self.sync_and_reboot_with_factory_install_shim)
            },
            {   # Step4, Check Rollback version.
                'state_checker': (self.checkers.crossystem_checker, {
                    'mainfw_act': 'A',
                    'tried_fwb': '0',
                    'fwid': self._fwid
                }),
                'userspace_action':(self.check_firmware_version,
                                    self._update_version - 1)

            }
        ))

        self.run_faft_sequence()
