# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import httplib
import logging
import os
import re
import urlparse

from autotest_lib.client.common_lib import error, global_config

# Local stateful update path is relative to the CrOS source directory.
LOCAL_STATEFUL_UPDATE_PATH = 'src/platform/dev/stateful_update'
REMOTE_STATEUL_UPDATE_PATH = '/usr/local/bin/stateful_update'
STATEFUL_UPDATE = '/tmp/stateful_update'
UPDATER_BIN = '/usr/bin/update_engine_client'
UPDATER_IDLE = 'UPDATE_STATUS_IDLE'
UPDATER_NEED_REBOOT = 'UPDATE_STATUS_UPDATED_NEED_REBOOT'
UPDATED_MARKER = '/var/run/update_engine_autoupdate_completed'


class ChromiumOSError(error.InstallError):
    """Generic error for ChromiumOS-specific exceptions."""
    pass


def url_to_version(update_url):
    # The ChromiumOS updater respects the last element in the path as
    # the requested version. Parse it out.
    return urlparse.urlparse(update_url).path.split('/')[-1]


class ChromiumOSUpdater():
    KERNEL_A = {'name': 'KERN-A', 'kernel': 2, 'root': 3}
    KERNEL_B = {'name': 'KERN-B', 'kernel': 4, 'root': 5}


    def __init__(self, update_url, host=None):
        self.host = host
        self.update_url = update_url
        self.update_version = url_to_version(update_url)


    def check_update_status(self):
        """Return current status from update-engine."""
        update_status = self._run(
            '%s -status 2>&1 | grep CURRENT_OP' % UPDATER_BIN)
        return update_status.stdout.strip().split('=')[-1]


    def reset_update_engine(self):
        """Restarts the update-engine service."""
        self._run('rm -f %s' % UPDATED_MARKER)
        try:
            self._run('initctl stop update-engine')
        except error.AutoservRunError:
            logging.warn('Stopping update-engine service failed. Already dead?')
        self._run('initctl start update-engine')

        if self.check_update_status() != UPDATER_IDLE:
            raise ChromiumOSError('%s is not in an installable state' %
                                  self.host.hostname)


    def _run(self, cmd, *args, **kwargs):
        """Abbreviated form of self.host.run(...)"""
        return self.host.run(cmd, *args, **kwargs)


    def rootdev(self, options=''):
        """Returns the stripped output of rootdev <options>."""
        return self._run('rootdev %s' % options).stdout.strip()


    def get_kernel_state(self):
        """Returns the (<active>, <inactive>) kernel state as a pair."""
        active_root = int(re.findall('\d+\Z', self.rootdev('-s'))[0])
        if active_root == self.KERNEL_A['root']:
            return self.KERNEL_A, self.KERNEL_B
        elif active_root == self.KERNEL_B['root']:
            return self.KERNEL_B, self.KERNEL_A
        else:
            raise ChromiumOSError('Encountered unknown root partition: %s' %
                                  active_root)


    def _cgpt(self, flag, kernel, dev='$(rootdev -s -d)'):
        """Return numeric cgpt value for the specified flag, kernel, device. """
        return int(self._run('cgpt show -n -i %d %s %s' % (
            kernel['kernel'], flag, dev)).stdout.strip())


    def get_kernel_priority(self, kernel):
        """Return numeric priority for the specified kernel."""
        return self._cgpt('-P', kernel)


    def get_kernel_success(self, kernel):
        """Return boolean success flag for the specified kernel."""
        return self._cgpt('-S', kernel) != 0


    def get_kernel_tries(self, kernel):
        """Return tries count for the specified kernel."""
        return self._cgpt('-T', kernel)


    def revert_boot_partition(self):
        part = self.rootdev()
        logging.warn('Reverting update; Boot partition will be %s', part)
        return self._run('/postinst %s 2>&1' % part)


    def _update_root(self):
        # Reset update_engine's state & check that update_engine is idle.
        self.reset_update_engine()

        # Run update_engine using the specified URL.
        try:
            autoupdate_cmd = '%s --update --omaha_url=%s 2>&1' % (
                UPDATER_BIN, self.update_url)
            self._run(autoupdate_cmd, timeout=900)
        except error.AutoservRunError:
            raise ChromiumOSError('update-engine failed on %s' %
                                  self.host.hostname)

        # Check that the installer completed as expected.
        status = self.check_update_status()
        if status != UPDATER_NEED_REBOOT:
            raise ChromiumOSError('update-engine error on %s: %s' %
                                  (self.host.hostname, status))


    def _update_stateful(self):
        # Attempt stateful partition update; this must succeed so that the newly
        # installed host is testable after update.
        statefuldev_url = self.update_url.replace('update', 'static/archive')

        # Load the Chrome OS source tree location.
        stateful_update_path = os.path.join(
            global_config.global_config.get_config_value(
                'CROS', 'source_tree', default=''),
            LOCAL_STATEFUL_UPDATE_PATH)

        if os.path.exists(stateful_update_path):
            self.host.send_file(
                stateful_update_path, STATEFUL_UPDATE, delete_dest=True)
            statefuldev_cmd = [STATEFUL_UPDATE]
        else:
            logging.warn('Could not find local stateful_update script, falling'
                         ' back on client copy.')
            statefuldev_cmd = [REMOTE_STATEUL_UPDATE_PATH]

        statefuldev_cmd += [statefuldev_url, '--stateful_change=clean', '2>&1']
        try:
            self._run(' '.join(statefuldev_cmd), timeout=600)
        except error.AutoservRunError:
            self.revert_boot_partition()
            raise ChromiumOSError('stateful_update failed on %s' %
                                  self.host.hostname)


    def run_update(self, force_update):
        booted_version = self.get_booted_version()
        if booted_version in self.update_version and not force_update:
            logging.info('System is already up to date. Skipping update.')
            return False

        logging.info(
            'Updating from version %s to %s.', booted_version,
            self.update_version)

        # Check that Dev Server is accepting connections (from autoserv's host).
        # If we can't talk to it, the machine host probably can't either.
        auserver_host = urlparse.urlparse(self.update_url)[1]
        try:
            httplib.HTTPConnection(auserver_host).connect()
        except IOError:
            raise ChromiumOSError(
                'Update server at %s not available' % auserver_host)

        logging.info(
            'Installing from %s to: %s', self.update_url, self.host.hostname)

        logging.info('Updating root partition...')
        self._update_root()

        logging.info('Updating stateful partition...')
        self._update_stateful()

        logging.info('Update complete.')
        return True


    def get_booted_version(self):
        booted_version = self.get_build_id()
        if not booted_version:
            booted_version = self.get_dev_build_id()
        return booted_version


    def check_version(self):
        booted_version = self.get_booted_version()
        if not booted_version in self.update_version:
            logging.error('Expected Chromium OS version: %s.'
                          'Found Chromium OS %s',
                          self.update_version, booted_version)
            raise ChromiumOSError('Updater failed on host %s' %
                                  self.host.hostname)
        else:
            return True


    def get_build_id(self):
        """Turns the CHROMEOS_RELEASE_DESCRIPTION into a string that
        matches the build ID."""
        version = self._run('grep CHROMEOS_RELEASE_DESCRIPTION'
                            ' /etc/lsb-release').stdout
        build_re = (r'CHROMEOS_RELEASE_DESCRIPTION='
                    '(\d+\.\d+\.\d+\.\d+) \(\w+ \w+ (\w+)(.*)\)')
        version_match = re.match(build_re, version)
        if version_match:
            version, build_id, builder = version_match.groups()
            build_match = re.match(r'.*: (\d+)', builder)
            if build_match:
                builder_num = '-b%s' % build_match.group(1)
            else:
                builder_num = ''
            return '%s-r%s%s' % (version, build_id, builder_num)


    def get_dev_build_id(self):
        """Pulls the CHROMEOS_RELEASE_VERSION string from /etc/lsb-release."""
        return self._run('grep CHROMEOS_RELEASE_VERSION'
                         ' /etc/lsb-release').stdout.split('=')[1].strip()
