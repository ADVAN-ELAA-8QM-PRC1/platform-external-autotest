# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re
from autotest_lib.client.bin import test
from autotest_lib.client.common_lib import error

class metrics_shutdown(test.test):
    version = 1

    # General method for parsing the disk file for desired field number (from 0)
    # Field 2 is disk sectors read, 6 is disk sectors written
    def parse_disk_shutdown(self, field_num):
        data_start = file('/var/log/metrics/disk_shutdown_start').read()
        vals_start = re.split(r' +', data_start.strip())
        data_stop = file('/var/log/metrics/disk_shutdown_stop').read()
        vals_stop = re.split(r' +', data_stop.strip())
        return float(vals_stop[field_num]) - float(vals_start[field_num])

    def run_once(self):
        try:
            uptime_shutdown_start = \
                float(file('/var/log/metrics/uptime_shutdown_start').read())
            uptime_shutdown_stop = \
                float(file('/var/log/metrics/uptime_shutdown_stop').read())
            results = {}
            results['ShutdownTime'] = \
                str(uptime_shutdown_stop - uptime_shutdown_start)
            results['ShutdownSectorsRead'] = \
                str(self.parse_disk_shutdown(2))
            results['ShutdownSectorsWritten'] = \
                str(self.parse_disk_shutdown(6))
            self.write_perf_keyval(results)
        except IOError, e:
            print e
            raise error.TestFail('Chrome OS shutdown metrics are missing')
