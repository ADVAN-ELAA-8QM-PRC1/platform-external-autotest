# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging, os, re
from autotest_lib.client.bin import site_crash_test, site_log_reader, \
     site_utils, test
from autotest_lib.client.common_lib import error, utils


_KCRASH_FILE = '/sys/kernel/debug/preserved/kcrash'


class logging_KernelCrash(site_crash_test.CrashTest):
    version = 1


    def _test_reporter_startup(self):
        """Test that the crash_reporter is handling kernel crashes."""
        if not self._log_reader.can_find('Enabling kernel crash handling'):
            if not self._log_reader.can_find(
                'Kernel does not support crash dumping'):
                raise error.TestFail(
                    'Could not find kernel crash found message')


    def _get_kcrash_name(self):
        filename_match = re.search(
            r'Collected kernel crash diagnostics into (\S+)',
            self._log_reader.get_logs())
        if not filename_match:
            return None
        return filename_match.group(1)


    def _test_reporter_kcrash_storage(self):
        """Test that crash_reporter has properly stored the kcrash report."""
        if not self._log_reader.can_find('Cleared kernel crash diagnostics'):
            raise error.TestFail('Could not find clearing message')

        kcrash_report = self._get_kcrash_name()

        if self._consent:
            if kcrash_report is None:
                raise error.TestFail(
                    'Could not find message with kcrash filename')
        else:
            if kcrash_report is not None:
                raise error.TestFail('Should not have found kcrash filename')
            return

        if not os.path.exists(kcrash_report):
            raise error.TestFail('Crash report gone')
        report_contents = utils.read_file(kcrash_report)
        if not 'kernel BUG at fs/proc/breakme.c' in report_contents:
            raise error.TestFail('Crash report has unexpected contents')

        if not os.path.exists(_KCRASH_FILE):
            raise error.TestFail('Could not find %s' % _KCRASH_FILE)
        kcrash_file_contents = utils.read_file(_KCRASH_FILE)
        if kcrash_file_contents != '':
            raise error.TestFail('%s was not properly cleared' % _KCRASH_FILE)


    def _test_sender_send_kcrash(self):
        """Test that crash_sender properly sends the crash report."""
        if not self._consent:
            return
        kcrash_report = self._get_kcrash_name()
        if not os.path.exists(kcrash_report):
            raise error.TestFail('Crash report gone')
        result = self._call_sender_one_crash(
            report=os.path.basename(kcrash_report))
        if (not result['send_attempt'] or not result['send_success'] or
            result['report_exists']):
            raise error.TestFail('kcrash not sent properly')
        if result['exec_name'] != 'kernel' or result['report_kind'] != 'kcrash':
            raise error.TestFail('kcrash exec name or report kind wrong')
        if result['report_payload'] != kcrash_report:
            raise error.TestFail('Sent the wrong kcrash report')


    def run_once(self, is_before, consent):
        self._log_reader.set_start_by_reboot(-1)
        # We manage consent saving across tests.
        self._automatic_consent_saving = False
        self._consent = consent
        if is_before:
            self.run_crash_tests(['reporter_startup'], must_run_all=False)
            # Leave crash sending paused for the kernel crash.
            self._leave_crash_sending = False
        else:
            self.run_crash_tests(['reporter_startup',
                                  'reporter_kcrash_storage',
                                  'sender_send_kcrash'],
                                 clear_spool_first=False)
