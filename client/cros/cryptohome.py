# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import dbus, logging, os, random, re, shutil, string

import common, constants
from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error

CRYPTOHOME_CMD = '/usr/sbin/cryptohome'
GUEST_USER_NAME = '$guest'

class ChromiumOSError(error.TestError):
    """Generic error for ChromiumOS-specific exceptions."""
    pass


def __run_cmd(cmd):
    return utils.system_output(cmd + ' 2>&1', retain_output=True,
                               ignore_status=True).strip()


def get_user_hash(user):
    """Get the user hash for the given user."""
    return utils.system_output(['cryptohome', '--action=obfuscate_user',
                                '--user=%s' % user])


def user_path(user):
    """Get the user mount point for the given user."""
    return utils.system_output(['cryptohome-path', 'user', user])


def system_path(user):
    """Get the system mount point for the given user."""
    return utils.system_output(['cryptohome-path', 'system', user])


def ensure_clean_cryptohome_for(user, password=None):
    """Ensure a fresh cryptohome exists for user.

    @param user: user who needs a shiny new cryptohome.
    @param password: if unset, a random password will be used.
    """
    if not password:
        password = ''.join(random.sample(string.ascii_lowercase, 6))
    remove_vault(user)
    mount_vault(user, password, create=True)


def get_tpm_status():
    """Get the TPM status.

    Returns:
        A TPM status dictionary, for example:
        { 'Enabled': True,
          'Owned': True,
          'Being Owned': False,
          'Ready': True,
          'Password': ''
        }
    """
    out = __run_cmd(CRYPTOHOME_CMD + ' --action=tpm_status')
    status = {}
    for field in ['Enabled', 'Owned', 'Being Owned', 'Ready']:
        match = re.search('TPM %s: (true|false)' % field, out)
        if not match:
            raise ChromiumOSError('Invalid TPM status: "%s".' % out)
        status[field] = match.group(1) == 'true'
    match = re.search('TPM Password: (\w*)', out)
    status['Password'] = ''
    if match:
        status['Password'] = match.group(1)
    return status


def get_tpm_attestation_status():
    """Get the TPM attestation status.  Works similar to get_tpm_status().
    """
    out = __run_cmd(CRYPTOHOME_CMD + ' --action=tpm_attestation_status')
    status = {}
    for field in ['Prepared', 'Enrolled']:
        match = re.search('Attestation %s: (true|false)' % field, out)
        if not match:
            raise ChromiumOSError('Invalid attestation status: "%s".' % out)
        status[field] = match.group(1) == 'true'
    return status


def take_tpm_ownership():
    """Take TPM owernship.

    Blocks until TPM is owned.
    """
    __run_cmd(CRYPTOHOME_CMD + ' --action=tpm_take_ownership')
    __run_cmd(CRYPTOHOME_CMD + ' --action=tpm_wait_ownership')


def verify_ek():
    """Verify the TPM endorsement key.

    Returns true if EK is valid.
    """
    cmd = CRYPTOHOME_CMD + ' --action=tpm_verify_ek'
    return (utils.system(cmd, ignore_status=True) == 0)


def remove_vault(user):
    """Remove the given user's vault from the shadow directory."""
    logging.debug('user is %s', user)
    user_hash = get_user_hash(user)
    logging.debug('Removing vault for user %s with hash %s' % (user, user_hash))
    cmd = CRYPTOHOME_CMD + ' --action=remove --force --user=%s' % user
    __run_cmd(cmd)
    # Ensure that the vault does not exist.
    if os.path.exists(os.path.join(constants.SHADOW_ROOT, user_hash)):
        raise ChromiumOSError('Cryptohome could not remove the user''s vault.')


def remove_all_vaults():
    """Remove any existing vaults from the shadow directory.

    This function must be run with root privileges.
    """
    for item in os.listdir(constants.SHADOW_ROOT):
        abs_item = os.path.join(constants.SHADOW_ROOT, item)
        if os.path.isdir(os.path.join(abs_item, 'vault')):
            logging.debug('Removing vault for user with hash %s' % item)
            shutil.rmtree(abs_item)


def mount_vault(user, password, create=False):
    """Mount the given user's vault."""
    args = [CRYPTOHOME_CMD, '--action=mount', '--user=%s' % user,
            '--password=%s' % password]
    if create:
        args.append('--create')
    print utils.system_output(args)
    # Ensure that the vault exists in the shadow directory.
    user_hash = get_user_hash(user)
    if not os.path.exists(os.path.join(constants.SHADOW_ROOT, user_hash)):
        raise ChromiumOSError('Cryptohome vault not found after mount.')
    # Ensure that the vault is mounted.
    if not is_vault_mounted(
            user=user,
            device_regex=constants.CRYPTOHOME_DEV_REGEX_REGULAR_USER,
            allow_fail=True):
        raise ChromiumOSError('Cryptohome created a vault but did not mount.')


def mount_guest():
    """Mount the given user's vault."""
    print utils.system_output([CRYPTOHOME_CMD, '--action=mount_guest'])
    # Ensure that the guest tmpfs is mounted.
    if not is_guest_vault_mounted(allow_fail=True):
        raise ChromiumOSError('Cryptohome did not mount tmpfs.')


def test_auth(user, password):
    cmd = [CRYPTOHOME_CMD, '--action=test_auth', '--user=%s' % user,
           '--password=%s' % password, '--async']
    return 'Authentication succeeded' in utils.system_output(cmd)


def unmount_vault(user):
    """Unmount the given user's vault.

    Once unmounting for a specific user is supported, the user parameter will
    name the target user. See crosbug.com/20778.
    """
    cmd = (CRYPTOHOME_CMD + ' --action=unmount')
    __run_cmd(cmd)
    # Ensure that the vault is not mounted.
    if is_vault_mounted(user, allow_fail=True):
        raise ChromiumOSError('Cryptohome did not unmount the user.')


def __get_mount_info(mount_point, allow_fail=False):
    """Get information about the active mount at a given mount point."""
    print utils.system_output('cat /proc/$(pgrep cryptohomed)/mounts')
    mount_line = utils.system_output(
        'grep %s /proc/$(pgrep cryptohomed)/mounts' % mount_point,
        ignore_status=allow_fail)
    return mount_line.split()


def __get_user_mount_info(user, allow_fail=False):
    """Get information about the active mounts for a given user.

    Returns the active mounts at the user's user and system mount points. If no
    user is given, the active mount at the shared mount point is returned
    (regular users have a bind-mount at this mount point for backwards
    compatibility; the guest user has a mount at this mount point only).
    """
    return [__get_mount_info(mount_point=user_path(user),
                             allow_fail=allow_fail),
            __get_mount_info(mount_point=system_path(user),
                             allow_fail=allow_fail)]

def is_vault_mounted(
        user,
        device_regex=constants.CRYPTOHOME_DEV_REGEX_ANY,
        fs_regex=constants.CRYPTOHOME_FS_REGEX_ANY,
        allow_fail=False):
    """Check whether a vault is mounted for the given user.

    If no user is given, the shared mount point is checked, determining whether
    a vault is mounted for any user.
    """
    user_mount_info = __get_user_mount_info(user=user, allow_fail=allow_fail)
    for mount_info in user_mount_info:
        if (len(mount_info) < 3 or
                not re.match(device_regex, mount_info[0]) or
                not re.match(fs_regex, mount_info[2])):
            return False
    return True


def is_guest_vault_mounted(allow_fail=False):
    """Check whether a vault backed by tmpfs is mounted for the guest user."""
    return is_vault_mounted(
        user=GUEST_USER_NAME,
        device_regex=constants.CRYPTOHOME_DEV_REGEX_GUEST,
        fs_regex=constants.CRYPTOHOME_FS_REGEX_TMPFS,
        allow_fail=allow_fail)


def get_mounted_vault_devices(user, allow_fail=False):
    """Get the device(s) backing the vault mounted for the given user.

    Returns the devices mounted at the user's user and system mount points. If
    no user is given, the device mounted at the shared mount point is returned.
    """
    return [mount_info[0]
            for mount_info
            in __get_user_mount_info(user=user, allow_fail=allow_fail)
            if len(mount_info)]


def canonicalize(credential):
    """Perform basic canonicalization of |email_address|.

    Perform basic canonicalization of |email_address|, taking into account that
    gmail does not consider '.' or caps inside a username to matter. It also
    ignores everything after a '+'. For example,
    c.masone+abc@gmail.com == cMaSone@gmail.com, per
    http://mail.google.com/support/bin/answer.py?hl=en&ctx=mail&answer=10313
    """
    if not credential:
      return None

    parts = credential.split('@')
    if len(parts) != 2:
        raise error.TestError('Malformed email: ' + credential)

    (name, domain) = parts
    name = name.partition('+')[0]
    if (domain == constants.SPECIAL_CASE_DOMAIN):
        name = name.replace('.', '')
    return '@'.join([name, domain]).lower()


class CryptohomeProxy:
    def __init__(self):
        BUSNAME = 'org.chromium.Cryptohome'
        PATH = '/org/chromium/Cryptohome'
        INTERFACE = 'org.chromium.CryptohomeInterface'
        bus = dbus.SystemBus()
        obj = bus.get_object(BUSNAME, PATH)
        self.iface = dbus.Interface(obj, INTERFACE)

    def mount(self, user, password, create=False):
        """Mounts a cryptohome.

        Returns True if the mount succeeds or False otherwise.
        TODO(ellyjones): Migrate mount_vault() to use a multi-user-safe
        heuristic, then remove this method. See <crosbug.com/20778>.
        """
        return self.iface.Mount(user, password, create, False, [])[1]

    def unmount(self, user):
        """Unmounts a cryptohome.

        Returns True if the unmount suceeds or false otherwise.
        TODO(ellyjones): Once there's a per-user unmount method, use it. See
        <crosbug.com/20778>.
        """
        return self.iface.Unmount()

    def is_mounted(self, user):
        """Tests whether a user's cryptohome is mounted."""
        return (utils.is_mountpoint(user_path(user))
                and utils.is_mountpoint(system_path(user)))

    def require_mounted(self, user):
        """Raises a test failure if a user's cryptohome is not mounted."""
        utils.require_mountpoint(user_path(user))
        utils.require_mountpoint(system_path(user))

    def migrate(self, user, oldkey, newkey):
        """Migrates the specified user's cryptohome from one key to another."""
        return self.iface.MigrateKey(user, oldkey, newkey)

    def remove(self, user):
        return self.iface.Remove(user)
