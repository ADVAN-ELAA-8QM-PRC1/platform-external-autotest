# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
import logging
import os
import re
import time

import common
from autotest_lib.client.common_lib import hosts, error
from autotest_lib.server import afe_utils
from autotest_lib.server import crashcollect
from autotest_lib.server.hosts import repair


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
                        'AC power is not plugged in')
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


class WritableVerifier(hosts.Verifier):
    """
    Confirm the stateful file systems are writable.

    The standard linux response to certain unexpected file system errors
    (including hardware errors in block devices) is to change the file
    system status to read-only.  This checks that that hasn't happened.

    The test covers the two file systems that need to be writable for
    critical operations like AU:
      * The (unencrypted) stateful system which includes
        /mnt/stateful_partition.
      * The encrypted stateful partition, which includes /var.

    The test doesn't check various bind mounts; those are expected to
    fail the same way as their underlying main mounts.  Whether the
    Linux kernel can guarantee that is untested...
    """

    # N.B. Order matters here:  Encrypted stateful is loop-mounted from
    # a file in unencrypted stateful, so we don't test for errors in
    # encrypted stateful if unencrypted fails.
    _TEST_DIRECTORIES = ['/mnt/stateful_partition', '/var/tmp']

    def verify(self, host):
        # This deliberately stops looking after the first error.
        # See above for the details.
        for testdir in self._TEST_DIRECTORIES:
            filename = os.path.join(testdir, 'writable_test')
            command = 'touch %s && rm %s' % (filename, filename)
            rv = host.run(command=command, ignore_status=True)
            if rv.exit_status != 0:
                msg = 'Can\'t create a file in %s' % testdir
                raise hosts.AutoservVerifyError(msg)

    @property
    def description(self):
        return 'The stateful filesystems are writable'


class EXT4fsErrorVerifier(hosts.Verifier):
    """
    Confirm we have not seen critical file system kernel errors.
    """
    def verify(self, host):
        # grep for stateful FS errors of the type "EXT4-fs error (device sda1):"
        command = ("dmesg | grep -E \"EXT4-fs error \(device "
                   "$(cut -d ' ' -f 5,9 /proc/$$/mountinfo | "
                   "grep -e '^/mnt/stateful_partition ' | "
                   "cut -d ' ' -f 2 | cut -d '/' -f 3)\):\"")
        output = host.run(command=command, ignore_status=True).stdout
        if output:
            sample = output.splitlines()[0]
            message = 'Saw file system error: %s' % sample
            raise hosts.AutoservVerifyError(message)
        # Check for other critical FS errors.
        command = 'dmesg | grep "This should not happen!!  Data will be lost"'
        output = host.run(command=command, ignore_status=True).stdout
        if output:
            message = 'Saw file system error: Data will be lost'
            raise hosts.AutoservVerifyError(message)
        else:
            logging.error('Could not determine stateful mount.')

    @property
    def description(self):
        return 'Did not find critical file system errors'


class UpdateSuccessVerifier(hosts.Verifier):
    """
    Checks that the DUT successfully finished its last provision job.

    At the start of any update (e.g. for a Provision job), the code
    creates a marker file named `host.PROVISION_FAILED`.  The file is
    located in a part of the stateful partition that will be removed if
    an update finishes successfully.  Thus, the presence of the file
    indicates that a prior update failed.

    The verifier tests for the existence of the marker file and fails if
    it still exists.
    """
    def verify(self, host):
        result = host.run('test -f %s' % host.PROVISION_FAILED,
                          ignore_status=True)
        if result.exit_status == 0:
            raise hosts.AutoservVerifyError(
                    'Last AU on this DUT failed')

    @property
    def description(self):
        return 'The most recent AU attempt on this DUT succeeded'


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

    def verify(self, host):
        # Test 1 - The DUT is not part of a FAFT pool.
        if host._is_firmware_repair_supported():
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
            if tpm['owned'] and not tpm['can_load_srk']:
                raise hosts.AutoservVerifyError(
                        'Cannot load the TPM SRK')
            if tpm['can_load_srk'] and not tpm['can_load_srk_pubkey']:
                raise hosts.AutoservVerifyError(
                        'Cannot load the TPM SRK public key')
        except KeyError:
            logging.info('Cannot determine the Crytohome valid status - '
                         'skipping check.')

    @property
    def description(self):
        return 'The host\'s TPM is available and working'


class PythonVerifier(hosts.Verifier):
    """Confirm the presence of a working Python interpreter."""

    def verify(self, host):
        result = host.run('python -c "import cPickle"',
                          ignore_status=True)
        if result.exit_status != 0:
            message = 'The python interpreter is broken'
            if result.exit_status == 127:
                search = host.run('which python', ignore_status=True)
                if search.exit_status != 0 or not search.stdout:
                    message = ('Python is missing; may be caused by '
                               'powerwash')
            raise hosts.AutoservVerifyError(message)

    @property
    def description(self):
        return 'Python on the host is installed and working'


class ServoSysRqRepair(hosts.RepairAction):
    """
    Repair a Chrome device by sending a system request to the kernel.

    Sending 3 times the Alt+VolUp+x key combination (aka sysrq-x)
    will ask the kernel to panic itself and reboot while conserving
    the kernel logs in console ramoops.
    """

    def repair(self, host):
        if not host.servo:
            raise hosts.AutoservRepairError(
                    '%s has no servo support.' % host.hostname)
        # Press 3 times Alt+VolUp+X
        # no checking DUT health between each press as
        # killing Chrome is not really likely to fix the DUT SSH.
        for _ in range(3):
            try:
                host.servo.sysrq_x()
            except error.TestFail, ex:
                raise hosts.AutoservRepairError(
                      'cannot press sysrq-x: %s.' % str(ex))
            # less than 5 seconds between presses.
            time.sleep(2.0)

        if host.wait_up(host.BOOT_TIMEOUT):
            # Collect logs once we regain ssh access before clobbering them.
            local_log_dir = crashcollect.get_crashinfo_dir(host, 'after_sysrq')
            host.collect_logs('/var/log', local_log_dir, ignore_errors=True)
            # Collect crash info.
            crashcollect.get_crashinfo(host, None)
            return
        raise hosts.AutoservRepairError(
                '%s is still offline after reset.' % host.hostname)

    @property
    def description(self):
        return 'Reset the DUT via kernel sysrq'


class ServoResetRepair(hosts.RepairAction):
    """Repair a Chrome device by resetting it with servo."""

    def repair(self, host):
        if not host.servo:
            raise hosts.AutoservRepairError(
                    '%s has no servo support.' % host.hostname)
        host.servo.get_power_state_controller().reset()
        if host.wait_up(host.BOOT_TIMEOUT):
            # Collect logs once we regain ssh access before clobbering them.
            local_log_dir = crashcollect.get_crashinfo_dir(host, 'after_reset')
            host.collect_logs('/var/log', local_log_dir, ignore_errors=True)
            # Collect crash info.
            crashcollect.get_crashinfo(host, None)
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
        (repair.SshVerifier,         'ssh',      []),
        (ACPowerVerifier,            'power',    ['ssh']),
        (EXT4fsErrorVerifier,        'ext4',     ['ssh']),
        (WritableVerifier,           'writable', ['ssh']),
        (TPMStatusVerifier,          'tpm',      ['ssh']),
        (UpdateSuccessVerifier,      'good_au',  ['ssh']),
        (FirmwareVersionVerifier,    'rwfw',     ['ssh']),
        (PythonVerifier,             'python',   ['ssh']),
        (repair.LegacyHostVerifier,  'cros',     ['ssh']),
    ]

    # The dependencies and triggers for the 'au', 'powerwash', and 'usb'
    # repair actions stack up:  Each one is able to repair progressively
    # more verifiers than the one before.  The 'triggers' lists below
    # show the progression.
    #
    # N.B. AC power detection depends on software on the DUT, and there
    # have been bugs where detection failed even though the DUT really
    # did have power.  So, we make the 'power' verifier a trigger for
    # reinstall repair actions, too.
    #
    # TODO(jrbarnette):  AU repair can't fix all problems reported by
    # the 'cros' verifier; it's listed as an AU trigger as a
    # simplification.  The ultimate fix is to split the 'cros' verifier
    # into smaller individual verifiers.

    usb_triggers       = ['ssh', 'writable']
    powerwash_triggers = ['tpm', 'good_au', 'ext4']
    au_triggers        = ['power', 'rwfw', 'python', 'cros']

    repair_actions = [
        # RPM cycling must precede Servo reset:  if the DUT has a dead
        # battery, we need to reattach AC power before we reset via servo.
        (repair.RPMCycleRepair, 'rpm', [], ['ssh', 'power']),
        (ServoSysRqRepair, 'sysrq', [], ['ssh']),
        (ServoResetRepair, 'servoreset', [], ['ssh']),

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

        (repair.RebootRepair, 'reboot', ['ssh'], ['writable']),

        (AutoUpdateRepair, 'au',
                usb_triggers + powerwash_triggers, au_triggers),
        (PowerWashRepair, 'powerwash',
                usb_triggers, powerwash_triggers + au_triggers),
        (ServoInstallRepair, 'usb',
                [], usb_triggers + powerwash_triggers + au_triggers),
    ]
    return hosts.RepairStrategy(verify_dag, repair_actions)



def create_moblab_repair_strategy():
    """
    Return a `RepairStrategy` for a `MoblabHost`.

    Moblab is a subset of the CrOS verify and repair.  Several pieces
    are removed because they're not expected to be meaningful.  Some
    others are removed for more specific reasons:

    'tpm':  Moblab DUTs don't run the tests that matter to this
        verifier.  TODO(jrbarnette)  This assertion is unproven.

    'good_au':  This verifier can't pass, because the Moblab AU
        procedure doesn't properly delete CrosHost.PROVISION_FAILED.
        TODO(jrbarnette) We should refactor _machine_install() so that
        it can be different for Moblab.

    'firmware':  Moblab DUTs shouldn't be in FAFT pools, so we don't try
        this.

    'powerwash':  Powerwash on Moblab causes trouble with deleting the
        DHCP leases file, so we skip it.
    """
    verify_dag = [
        (repair.SshVerifier,         'ssh',     []),
        (ACPowerVerifier,            'power',   ['ssh']),
        (FirmwareVersionVerifier,    'rwfw',    ['ssh']),
        (PythonVerifier,             'python',  ['ssh']),
        (repair.LegacyHostVerifier,  'cros',    ['ssh']),
    ]
    au_triggers = ['power', 'rwfw', 'python', 'cros']
    repair_actions = [
        (repair.RPMCycleRepair, 'rpm', [], ['ssh', 'power']),
        (AutoUpdateRepair, 'au', ['ssh'], au_triggers),
    ]
    return hosts.RepairStrategy(verify_dag, repair_actions)
