# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from autotest_lib.client.bin import test
from autotest_lib.client.cros import power_suspend


class power_Resume(test.test):
    version = 1
    preserve_srcdir = True

    def initialize(self):
        self._suspender = power_suspend.Suspender(self.resultsdir,
                throw=True, device_times=True)


    def run_once(self, max_devs_returned=10, seconds=0):
        (results, device_times) = self._suspender.suspend(seconds)

        # return as keyvals the slowest n devices
        slowest_devs = sorted(
            device_times,
            key=device_times.get,
            reverse=True)[:max_devs_returned]
        for dev in slowest_devs:
            results[dev] = device_times[dev]

        self.output_perf_value(description='system_suspend',
                               value=results['seconds_system_suspend'],
                               units='sec', higher_is_better=False)
        self.output_perf_value(description='system_resume',
                               value=results['seconds_system_resume'],
                               units='sec', higher_is_better=False)
        self.write_perf_keyval(results)
