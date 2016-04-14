# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
import logging

import common
from autotest_lib.client.common_lib import hosts
from autotest_lib.server import afe_utils
from autotest_lib.server.hosts import label_verify
from autotest_lib.server.hosts import ssh_verify


class ACPowerVerifier(hosts.Verifier):
    """Check for AC power and a reasonable battery charge."""

    def verify(self, host):
        # Temporarily work around a problem caused by some old FSI
        # builds that don't have the power_supply_info command by
        # ignoring failures.  The repair triggers believe that this
        # verifier can't be fixed by re-installing, which means if a DUT
        # gets stuck with one of those old builds, it can't be repaired.
        #
        # TODO(jrbarnette): This is for crbug.com/599158; we need a
        # better solution.
        try:
            info = host.get_power_supply_info()
        except:
            logging.exception('get_power_supply_info() failed')
            return
        try:
            if info['Line Power']['online'] != 'yes':
                raise hosts.AutoservVerifyError(
                        'AC power is not online')
        except KeyError:
            logging.info('Cannot determine AC power status - '
                         'skipping check.')
        try:
            if float(info['Battery']['percentage']) < 50.0:
                raise hosts.AutoservVerifyError(
                        'Battery is less than 50%')
        except KeyError:
            logging.info('Cannot determine battery status - '
                         'skipping check.')


    @property
    def description(self):
        return 'The DUT is plugged in to AC power'


class UpdateSuccessVerifier(hosts.Verifier):
    """
    Checks that the DUT has not failed its last provision job.

    At the start of update (e.g. for a Provision job), the code touches
    the file named in `host.PROVISION_FAILED`.  The file is located
    in a part of the stateful partition that will be removed when the
    update finishes.  Thus, the presence of the file indicates that a
    prior update failed.

    @return: True if there exists file /var/tmp/provision_failed, which
             indicates the last provision job failed.
             False if the file does not exist or the dut can't be reached.
    """
    def verify(self, host):
        result = host.run('test -f %s' % host.PROVISION_FAILED,
                          ignore_status=True, timeout=5)
        if result.exit_status == 0:
            raise hosts.AutoservVerifyError(
                    'Last AU on this DUT failed')


    @property
    def description(self):
        return 'The most recent AU attempt on this DUT succeeded'




class TPMStatusVerifier(hosts.Verifier):
    """Verify that the host's TPM is in a good state."""

    def verify(self, host):
        # This cryptohome command emits status information in JSON format. It
        # looks something like this:
        # {
        #    "installattrs": {
        #       ...
        #    },
        #    "mounts": [ {
        #       ...
        #    } ],
        #    "tpm": {
        #       "being_owned": false,
        #       "can_connect": true,
        #       "can_decrypt": false,
        #       "can_encrypt": false,
        #       "can_load_srk": true,
        #       "can_load_srk_pubkey": true,
        #       "enabled": true,
        #       "has_context": true,
        #       "has_cryptohome_key": false,
        #       "has_key_handle": false,
        #       "last_error": 0,
        #       "owned": true
        #    }
        # }
        output = host.run('cryptohome --action=status').stdout.strip()
        try:
            status = json.loads(output)
        except ValueError:
            logging.info('Cannot determine the Crytohome valid status - '
                         'skipping check.')
            return
        try:
            tpm = status['tpm']
            if not tpm['enabled']:
                raise hosts.AutoservVerifyError(
                        'TPM is not enabled -- Hardware is not working.')
            if not tpm['can_connect']:
                raise hosts.AutoservVerifyError(
                        ('TPM connect failed -- '
                         'last_error=%d.' % tpm['last_error']))
            if (tpm['owned'] and not tpm['can_load_srk']):
                raise hosts.AutoservVerifyError(
                        'Cannot load the TPM SRK')
            if (tpm['can_load_srk'] and not tpm['can_load_srk_pubkey']):
                raise hosts.AutoservVerifyError(
                        'Cannot load the TPM SRK public key')
        except KeyError:
            logging.info('Cannot determine the Crytohome valid status - '
                         'skipping check.')


    @property
    def description(self):
        return 'The host\'s TPM is available and working'


class CrosHostVerifier(hosts.Verifier):
    """
    Ask a CrOS host to perform its own verification.

    This class exists as a temporary legacy during refactoring to
    provide access to code that hasn't yet been rewritten to use the new
    repair and verify framework.
    """

    def verify(self, host):
        host.verify_software()
        host.verify_hardware()


    @property
    def description(self):
        return 'Miscellaneous CrOS host verification checks'


class RPMCycleRepair(hosts.RepairAction):
    """
    Cycle AC power using the RPM infrastructure.

    This is meant to catch two distinct kinds of failure:
      * If the DUT is wedged and has no battery (i.e. a chromebox),
        power cycling it may force it back on.
      * If the DUT has had AC power incorrectly turned off, power
        cycling will turn AC power back on.
    """

    def repair(self, host):
        if not host.has_power():
            raise hosts.AutoservRepairError(
                    '%s has no RPM connection.' % host.hostname)
        host.power_cycle()
        if not host.wait_up(timeout=host.BOOT_TIMEOUT):
            raise hosts.AutoservRepairError(
                    '%s is still offline after powercycling' %
                    host.hostname)


    @property
    def description(self):
        return 'Power cycle the DUT with RPM'


class ServoResetRepair(hosts.RepairAction):
    """Repair a Chrome device by resetting it with servo."""

    def repair(self, host):
        if not host.servo:
            raise hosts.AutoservRepairError(
                    '%s has no servo support.' % host.hostname)
        host.servo.get_power_state_controller().reset()
        if host.wait_up(host.BOOT_TIMEOUT):
            return
        raise hosts.AutoservRepairError(
                '%s is still offline after reset.' % host.hostname)


    @property
    def description(self):
        return 'Reset the DUT via servo'


class FirmwareRepair(hosts.RepairAction):
    """
    Reinstall the firmware image using servo.

    This repair function attempts to use servo to install the DUT's
    designated "stable firmware version".

    This repair method only applies to DUTs used for FAFT.
    """

    def repair(self, host):
        if not host._is_firmware_repair_supported():
            raise hosts.AutoservRepairError(
                    'Firmware repair is not applicable to host %s.' %
                    host.hostname)
        if not host.servo:
            raise hosts.AutoservRepairError(
                    '%s has no servo support.' % host.hostname)
        host.firmware_install()


    @property
    def description(self):
        return 'Re-install the stable firmware'


class AutoUpdateRepair(hosts.RepairAction):
    """
    Repair by re-installing a test image using autoupdate.

    Try to install the DUT's designated "stable test image" using the
    standard procedure for installing a new test image via autoupdate.
    """

    def repair(self, host):
        afe_utils.machine_install_and_update_labels(host, repair=True)


    @property
    def description(self):
        return 'Re-install the stable build via AU'


class PowerWashRepair(AutoUpdateRepair):
    """
    Powerwash the DUT, then re-install using autoupdate.

    Powerwash the DUT, then attempt to re-install a stable test image as
    for `AutoUpdateRepair`.
    """

    def repair(self, host):
        host.run('echo "fast safe" > '
                 '/mnt/stateful_partition/factory_install_reset')
        host.reboot(timeout=host.POWERWASH_BOOT_TIMEOUT, wait=True)
        super(PowerWashRepair, self).repair(host)


    @property
    def description(self):
        return 'Powerwash and then re-install the stable build via AU'


class ServoInstallRepair(hosts.RepairAction):
    """
    Reinstall a test image from USB using servo.

    Use servo to re-install the DUT's designated "stable test image"
    from servo-attached USB storage.
    """

    def repair(self, host):
        if not host.servo:
            raise hosts.AutoservRepairError(
                    '%s has no servo support.' % host.hostname)
        host.servo_install(host.stage_image_for_servo())


    @property
    def description(self):
        return 'Reinstall from USB using servo'


def create_cros_repair_strategy():
    """Return a `RepairStrategy` for a `CrosHost`."""
    verify_dag = [
        (ssh_verify.SshVerifier,      'ssh',     []),
        (ACPowerVerifier,             'power',   ['ssh']),
        (TPMStatusVerifier,           'tpm',     ['ssh']),
        (UpdateSuccessVerifier,       'good_au', ['ssh']),
        (CrosHostVerifier,            'cros',    ['ssh']),
        (label_verify.LabelVerifier,  'label',   ['ssh']),
    ]
    repair_actions = [
        # RPM cycling must precede Servo reset:  if the DUT has a dead
        # battery, we need to reattach AC power before we reset via servo.
        (RPMCycleRepair, 'rpm', [], ['ssh', 'power']),
        (ServoResetRepair, 'reset', [], ['ssh']),

        # TODO(jrbarnette):  the real dependency for firmware isn't
        # 'cros', but rather a to-be-created verifier that replaces
        # CrosHost.verify_firmware_status()
        #
        # N.B. FirmwareRepair can't fix a 'good_au' failure directly,
        # because it doesn't remove the flag file that triggers the
        # failure.  We include it as a repair trigger because it's
        # possible the the last update failed because of the firmware,
        # and we want the repair steps below to be able to trust the
        # firmware.
        (FirmwareRepair, 'firmware', [], ['ssh', 'cros', 'good_au']),

        # TODO(jrbarnette):  AU repair can't fix all problems reported
        # by the 'cros' verifier; some problems require powerwash.  Once
        # the 'cros' verifier is properly split into its component
        # parts, some of the 'cros' checks will be dependencies, others
        # will be triggers.
        (AutoUpdateRepair, 'au', ['ssh', 'tpm', 'good_au'], ['cros']),
        (PowerWashRepair, 'powerwash', ['ssh'], ['tpm', 'good_au', 'cros']),
        (ServoInstallRepair, 'usb', [], ['ssh', 'tpm', 'good_au', 'cros']),
    ]
    return hosts.RepairStrategy(verify_dag, repair_actions)



def create_moblab_repair_strategy():
    """
    Return a `RepairStrategy` for a `MoblabHost`.

    Moblab is a subset of the CrOS verify and repair.  Several pieces
    are removed, for various reasons:

    'tpm':  Moblab DUTs don't run the tests that matter to this
        verifier.  TODO(jrbarnette)  This assertion is unproven.

    'good_au':  This verifier can't pass, because the Moblab AU
        procedure doesn't properly delete CrosHost.PROVISION_FAILED.
        TODO(jrbarnette) We should refactor _machine_install() so that it
        can be different for Moblab.

    'firmware':  Moblab DUTs shouldn't be in FAFT pools, so we don't try
        this.

    'powerwash':  Powerwash on Moblab causes trouble with deleting the
        DHCP leases file, so we skip it.
    """
    verify_dag = [
        (ssh_verify.SshVerifier,  'ssh',     []),
        (ACPowerVerifier,         'power',   ['ssh']),
        (CrosHostVerifier,        'cros',    ['ssh']),
    ]
    repair_actions = [
        (RPMCycleRepair, 'rpm', [], ['ssh', 'power']),
        (ServoResetRepair, 'reset', [], ['ssh']),
        (AutoUpdateRepair, 'au', ['ssh'], ['cros']),
        (ServoInstallRepair, 'usb', [], ['ssh', 'cros']),
    ]
    return hosts.RepairStrategy(verify_dag, repair_actions)
