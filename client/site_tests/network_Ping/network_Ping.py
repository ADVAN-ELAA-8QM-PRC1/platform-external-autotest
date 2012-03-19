# Copyright (c) 2012 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging

from autotest_lib.client.bin import test, utils
from autotest_lib.client.common_lib import error


class network_Ping(test.test):
    """
    Verify we can ping internal and external hosts.
    """
    version = 1

    def get_gateway(self):
        """Determine the IP address of the default gateway.
        Returns:
            string, dotted ip address of gateway.
        """
        gateway = 'UGH'
        cmd = 'netstat -nr'
        address = None
        output = utils.system_output('%s' % cmd)

        linesout = output.splitlines()
        for line in linesout:
            if gateway in line:
                s = line.split()
                address = s[1]
                break

        if not address:
            logging.error('Error determining default gateway!')

        return address


    def run_once(self):
        errors = 0
        remote_hosts = ['www.google.com']

        default_gateway = self.get_gateway()
        if default_gateway:
            remote_hosts.append(default_gateway)
        else:
            raise error.TestFail('Failure to get default gateway!')

        for rhost in remote_hosts:
            if utils.ping(rhost, tries=5):
                logging.error('Error pinging %s' % rhost)
                errors += 1

        if errors:
            raise error.TestFail('%d failures pinging %d hosts' % (
                                 errors, len(remote_hosts)))
