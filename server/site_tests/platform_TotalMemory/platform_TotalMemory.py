# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging, re

from autotest_lib.server import autotest, test
from autotest_lib.client.common_lib import error


class platform_TotalMemory(test.test):
    version = 1


    def action_login(self):
        """Login i.e. runs running client test"""
        self.autotest_client.run_test('desktopui_SimpleLogin',
                                      exit_without_logout=True)

    def get_meminfo(self, key):
        """Get memtotal form meminfo

        @param key memory info title

        @return mem_total value

        """
        mem_total = self.host.read_from_meminfo(key)
        if mem_total is None:
            raise error.TestFail('Memory return no data' )
        return mem_total


    def run_once(self, host, reboot_counts):
        self.host = host
        mem_total_list = list()
        mem_free_list = list()
        self.autotest_client = autotest.Autotest(self.host)

        for reboot_count in xrange(reboot_counts):
            logging.info('Iteration %d', (reboot_count + 1))
            self.host.reboot()
            self.action_login()

            mem_total_size = self.get_meminfo('MemTotal')
            mem_total_list.append((mem_total_size))
            logging.info('MemTotalSize %d', mem_total_size)

            mem_free_size = self.get_meminfo('MemFree')
            mem_free_list.append(mem_free_size)
            logging.info('MemFreeSize %d', mem_free_size)

        errors = list()
        mem_total_list_size = len(set(mem_total_list))
        if mem_total_list_size > 1:
            errors.append('%d values of memtotal returned. MemoryTotal is not '
                          'consistent - %s' % (mem_total_list_size,
                                               str(set(mem_free_list))))

        mem_free_diff = max(mem_free_list) - min(mem_free_list)
        quarter_mem_total = max(mem_total_list) / 4
        if mem_free_diff > quarter_mem_total:
            errors.append('The difference between Free Memory readings '
                          '[%d] is bigger than 1/4 of Total Memory [%d]' %
                          (mem_free_diff, quarter_mem_total))

        if errors:
            raise error.TestFail('; '.join(errors))
