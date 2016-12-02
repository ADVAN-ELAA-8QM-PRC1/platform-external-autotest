# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
Repair actions and verifiers relating to CrOS firmware.

This contains the repair actions and verifiers need to find problems
with the firmware installed on Chrome OS DUTs, and when necessary, to
fix problems by updating or re-installing the firmware.
"""

import logging
import re

import common
from autotest_lib.client.common_lib import global_config
from autotest_lib.client.common_lib import hosts
from autotest_lib.server import afe_utils
from autotest_lib.site_utils.suite_scheduler import constants


_CONFIG = global_config.global_config
_FIRMWARE_REPAIR_POOLS = set(_CONFIG.get_config_value('CROS',
            'pools_support_firmware_repair', type=str).split(','))
_POOL_PREFIX = constants.Labels.POOL_PREFIX

def _is_firmware_repair_supported(host):
    """
    Check if a host supports firmware repair.

    Firmware repair is only applicable to DUTs in pools listed in
    the global config setting CROS/pools_support_firmware_repair.

    @return: `True` if it is supported, or `False` otherwise.
    """
    pool_labels = afe_utils.get_labels(host, _POOL_PREFIX)
    pools = set([l[len(_POOL_PREFIX) : ] for l in pool_labels])
    return bool(pools & _FIRMWARE_REPAIR_POOLS)


class FirmwareStatusVerifier(hosts.Verifier):
    """
    Verify that a host's firmware is in a good state.

    For DUTs that run firmware tests, it's possible that the firmware
    on the DUT can get corrupted.  This verifier checks whether it
    appears that firmware should be re-flashed using servo.
    """

    def verify(self, host):
        if not _is_firmware_repair_supported(host):
            return
        try:
            # Read the AP firmware and dump the sections that we're
            # interested in.
            cmd = ('mkdir /tmp/verify_firmware; '
                   'cd /tmp/verify_firmware; '
                   'for section in VBLOCK_A VBLOCK_B FW_MAIN_A FW_MAIN_B; '
                   'do flashrom -r image.bin -i $section:$section; '
                   'done')
            host.run(cmd)

            # Verify the firmware blocks A and B.
            cmd = ('vbutil_firmware --verify /tmp/verify_firmware/VBLOCK_%c'
                   ' --signpubkey /usr/share/vboot/devkeys/root_key.vbpubk'
                   ' --fv /tmp/verify_firmware/FW_MAIN_%c')
            for c in ('A', 'B'):
                rv = host.run(cmd % (c, c), ignore_status=True)
                if rv.exit_status:
                    raise hosts.AutoservVerifyError(
                            'Firmware %c is in a bad state.' % c)
        finally:
            # Remove the temporary files.
            host.run('rm -rf /tmp/verify_firmware')

    @property
    def description(self):
        return 'Firmware on this DUT is clean'


class FirmwareVersionVerifier(hosts.Verifier):
    """
    Check for a firmware update, and apply it if appropriate.

    This verifier checks to ensure that either the firmware on the DUT
    is up-to-date, or that the target firmware can be installed from the
    currently running build.

    Failure occurs when all of the following apply:
     1. The DUT is not part of a FAFT pool.  (DUTs used for FAFT testing
        instead use `FirmwareRepair`, below.)
     2. The DUT has an assigned stable firmware version.
     3. The DUT is not running the assigned stable firmware.
     4. The firmware supplied in the running OS build is not the
        assigned stable firmware.

    If the DUT needs an upgrade and the currently running OS build
    supplies the necessary firmware, use `chromeos-firmwareupdate` to
    install the new firmware.  Failure to install will cause the
    verifier to fail.

    This verifier nominally breaks the rule that "verifiers must succeed
    quickly", since it can invoke `reboot()` during the success code
    path.  We're doing it anyway for two reasons:
      * The time between updates will typically be measured in months,
        so the amortized cost is low.
      * The reason we distinguish repair from verify is to allow
        rescheduling work immediately while the expensive repair happens
        out-of-band.  But a firmware update will likely hit all DUTs at
        once, so it's pointless to pass the buck to repair.

    N.B. This verifier is a trigger for all repair actions that install
    the stable repair image.  If the firmware is out-of-date, but the
    stable repair image does *not* contain the proper firmware version,
    _the target DUT will fail repair, and will be unable to fix itself_.
    """

    @staticmethod
    def _get_rw_firmware(host):
        result = host.run('crossystem fwid', ignore_status=True)
        if result.exit_status == 0:
            return result.stdout
        else:
            return None

    @staticmethod
    def _get_available_firmware(host):
        result = host.run('chromeos-firmwareupdate -V',
                          ignore_status=True)
        if result.exit_status == 0:
            version = re.search(r'BIOS version:\s*(?P<version>.*)',
                                result.stdout)
            if version is not None:
                return version.group('version')
        return None

    @staticmethod
    def _check_hardware_match(version_a, version_b):
        """
        Check that two firmware versions identify the same hardware.

        Firmware version strings look like this:
            Google_Gnawty.5216.239.34
        The part before the numbers identifies the hardware for which
        the firmware was built.  This function checks that the hardware
        identified by `version_a` and `version_b` is the same.

        This is a sanity check to protect us from installing the wrong
        firmware on a DUT when a board label has somehow gone astray.

        @param version_a  First firmware version for the comparison.
        @param version_b  Second firmware version for the comparison.
        """
        hardware_a = version_a.split('.')[0]
        hardware_b = version_b.split('.')[0]
        if hardware_a != hardware_b:
            message = 'Hardware/Firmware mismatch updating %s to %s'
            raise hosts.AutoservVerifyError(
                    message % (version_a, version_b))

    def verify(self, host):
        # Test 1 - The DUT is not part of a FAFT pool.
        if _is_firmware_repair_supported(host):
            return
        # Test 2 - The DUT has an assigned stable firmware version.
        stable_firmware = afe_utils.get_stable_firmware_version(
                host._get_board_from_afe())
        if stable_firmware is None:
            # This DUT doesn't have a firmware update target
            return

        # For tests 3 and 4:  If the output from `crossystem` or
        # `chromeos-firmwareupdate` isn't what we expect, we log an
        # error, but don't fail:  We don't want DUTs unable to test a
        # build merely because of a bug or change in either of those
        # commands.

        # Test 3 - The DUT is not running the target stable firmware.
        current_firmware = self._get_rw_firmware(host)
        if current_firmware is None:
            logging.error('DUT firmware version can\'t be determined.')
            return
        if current_firmware == stable_firmware:
            return
        # Test 4 - The firmware supplied in the running OS build is not
        # the assigned stable firmware.
        available_firmware = self._get_available_firmware(host)
        if available_firmware is None:
            logging.error('Supplied firmware version in OS can\'t be '
                          'determined.')
            return
        if available_firmware != stable_firmware:
            raise hosts.AutoservVerifyError(
                    'DUT firmware requires update from %s to %s' %
                    (current_firmware, stable_firmware))
        # Time to update the firmware.
        logging.info('Updating firmware from %s to %s',
                     current_firmware, stable_firmware)
        self._check_hardware_match(current_firmware, stable_firmware)
        try:
            host.run('chromeos-firmwareupdate --mode=autoupdate')
            host.reboot()
        except Exception as e:
            message = ('chromeos-firmwareupdate failed: from '
                       '%s to %s')
            logging.exception(message, current_firmware, stable_firmware)
            raise hosts.AutoservVerifyError(
                    message % (current_firmware, stable_firmware))

    @property
    def description(self):
        return 'The firmware on this DUT is up-to-date'


class FirmwareRepair(hosts.RepairAction):
    """
    Reinstall the firmware image using servo.

    This repair function attempts to use servo to install the DUT's
    designated "stable firmware version".

    This repair method only applies to DUTs used for FAFT.
    """

    def repair(self, host):
        if not _is_firmware_repair_supported(host):
            raise hosts.AutoservRepairError(
                    'Firmware repair is not applicable to host %s.' %
                    host.hostname)
        if not host.servo:
            raise hosts.AutoservRepairError(
                    '%s has no servo support.' % host.hostname)
        host.firmware_install()

    @property
    def description(self):
        return 'Re-install the stable firmware via servo'
