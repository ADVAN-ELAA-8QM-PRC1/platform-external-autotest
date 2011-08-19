# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging, os, shutil, time
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros import cros_logging
from autotest_lib.client.cros.crash_test import CrashTest as CrashTestDefs
from autotest_lib.server import autotest, site_host_attributes, test

_CONSENT_FILE = '/home/chronos/Consent To Send Stats'
_STOWED_CONSENT_FILE = '/var/lib/kernel-crash-server.consent'


class logging_KernelCrashServer(test.test):
    version = 1


    def _exact_copy(self, source, dest):
        """Copy remote source to dest, where dest removed if src not present."""
        self._host.run('rm -f "%s"; cp "%s" "%s" 2>/dev/null; true' %
                       (dest, source, dest))

    def _exists_on_client(self, f):
        return self._host.run('ls "%s"' % f,
                               ignore_status=True).exit_status == 0

    # Taken from KernelErrorPaths, which duplicates it, but is up to date
    def _enable_consent(self):
        """ Enable consent so that crashes get stored in /var/spool/crash. """
        self._consent_files = [
            (CrashTestDefs._PAUSE_FILE, None, 'chronos'),
            (CrashTestDefs._CONSENT_FILE, None, 'chronos'),
            (CrashTestDefs._POLICY_FILE, 'mock_metrics_on.policy', 'root'),
            (CrashTestDefs._OWNER_KEY_FILE, 'mock_metrics_owner.key', 'root'),
            ]
        for dst, src, owner in self._consent_files:
            if self._exists_on_client(dst):
                self._host.run('mv "%s" "%s.autotest_backup"' % (dst, dst))
            if src:
                full_src = os.path.join(self.autodir, 'client/cros', src)
                self._host.send_file(full_src, dst)
            else:
                self._host.run('touch "%s"' % dst)
            self._host.run('chown "%s" "%s"' % (owner, dst))

    def _restore_consent_files(self):
        """ Restore consent files to their previous values. """
        for f, _, _ in self._consent_files:
            self._host.run('rm -f "%s"' % f)
            if self._exists_on_client('%s.autotest_backup' % f):
                self._host.run('mv "%s.autotest_backup" "%s"' % (f, f))

    def cleanup(self):
        self._exact_copy(_STOWED_CONSENT_FILE, _CONSENT_FILE)
        test.test.cleanup(self)


    def _can_disable_consent(self):
        """Returns whether or not host can have consent disabled.

        Presence of /etc/send_metrics causes ui.conf job (which starts
        after chromeos_startup) to regenerate a consent file if one
        does not exist.  Therefore, we cannot guarantee that
        crash-reporter.conf will start with the file gone if we
        removed it before causing a crash.
        """
        status = self._host.run('[ -r /etc/send_metrics ]', ignore_status=True)
        return status.exit_status != 0


    def _crash_it(self, consent):
        """Crash the host after setting the consent as given."""
        if consent:
            self._enable_consent()
        else:
            self._restore_consent_files()
        logging.info('KernelCrashServer: crashing %s' % self._host.hostname)
        boot_id = self._host.get_boot_id()
        self._host.run(
            'sh -c "sync; sleep 1; echo bug > /proc/breakme" >/dev/null 2>&1 &')
        self._host.wait_for_restart(old_boot_id=boot_id)


    def _run_while_paused(self, host):
        self._host = host
        client_at = autotest.Autotest(host)
        self._exact_copy(_CONSENT_FILE, _STOWED_CONSENT_FILE)

        client_at.run_test('logging_KernelCrash',
                           tag='before-crash',
                           is_before=True,
                           consent=True)

        client_attributes = site_host_attributes.HostAttributes(host.hostname)
        if not client_attributes.has_chromeos_firmware:
            raise error.TestNAError(
                'This device is unable to report kernel crashes')

        self._crash_it(True)

        # Check for crash handling with consent.
        client_at.run_test('logging_KernelCrash',
                           tag='after-crash-consent',
                           is_before=False,
                           consent=True)

        if not self._can_disable_consent():
            logging.info('This device always has metrics enabled, '
                         'skipping test of metrics disabled mode.')
        else:
            self._crash_it(False)

            # Check for crash handling without consent.
            client_at.run_test('logging_KernelCrash',
                               tag='after-crash-no-consent',
                               is_before=False,
                               consent=False)

    def run_once(self, host=None):
        # For the entire duration of this server test (across crashes
        # and boots after crashes) we want to disable log rotation.
        log_pauser = cros_logging.LogRotationPauser(host)
        try:
            log_pauser.begin()
            self._run_while_paused(host)
        finally:
            log_pauser.end()
