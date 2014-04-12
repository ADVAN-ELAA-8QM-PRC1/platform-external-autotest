#!/usr/bin/python
#
# Copyright (c) 2010 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

__author__ = 'kdlucas@chromium.org (Kelly Lucas)'

import logging, re

from autotest_lib.client.bin import utils, test
from autotest_lib.client.common_lib import error


class platform_MemCheck(test.test):
    """
    Verify memory usage looks correct.
    """
    version = 1
    swap_disksize_file = '/sys/block/zram0/disksize'

    def run_once(self):
        errors = 0
        keyval = dict()
        # The total memory will shrink if the system bios grabs more of the
        # reserved memory. We derived the value below by giving a small
        # cushion to allow for more system BIOS usage of ram. The memref value
        # is driven by the supported netbook model with the least amount of
        # total memory.  ARM and x86 values differ considerably.
        cpuType = utils.get_cpu_arch()
        memref = 986392
        vmemref = 102400
        if cpuType == "arm":
            memref = 700000
            vmemref = 210000

        speedref = 1333
        os_reserve = 600000

        # size reported in /sys/block/zram0/disksize is in byte
        swapref = int(utils.read_one_line(self.swap_disksize_file)) / 1024

        less_refs = ['MemTotal', 'MemFree', 'VmallocTotal']
        approx_refs = ['SwapTotal']

        # read physical HW size from mosys and adjust memref if need
        cmd = 'mosys memory spd print geometry -s size_mb'
        phy_size_run = utils.run(cmd)
        phy_size = 0
        for line in phy_size_run.stdout.split():
            phy_size += int(line)
        logging.info('Physical memory size is %d MB', phy_size)
        # memref is in KB but phy_size is in MB
        phy_size *= 1024
        keyval['PhysicalSize'] = phy_size
        memref = max(memref, phy_size - os_reserve)

        ref = {'MemTotal': memref,
               'MemFree': memref / 2,
               'SwapTotal': swapref,
               'VmallocTotal': vmemref,
              }


        for k in ref:
            value = utils.read_from_meminfo(k)
            keyval[k] = value
            if k in less_refs:
                if value < ref[k]:
                    logging.warn('%s is %d', k, value)
                    logging.warn('%s should be at least %d', k, ref[k])
                    errors += 1
            elif k in approx_refs:
                if value < ref[k] * 0.9 or ref[k] * 1.1 < value:
                    logging.warn('%s is %d', k, value)
                    logging.warn('%s should be within 10%% of %d', k, ref[k])
                    errors += 1

        # read spd timings
        cmd = 'mosys memory spd print timings -s speeds'
        # result example
        # DDR3-800, DDR3-1066, DDR3-1333, DDR3-1600
        pattern = 'DDR([3-9]|[1-9]\d+)-(?P<speed>\d+)'
        timing_run = utils.run(cmd)

        keyval['speedref'] = speedref
        for dimm, line in enumerate(timing_run.stdout.split('\n')):
            if not line:
                continue
            max_timing = line.split(', ')[-1]
            keyval['timing_dimm_%d' % dimm] = max_timing
            m = re.match(pattern, max_timing)
            if not m:
                logging.warn('Error parsing timings for dimm #%d (%s)',
                             dimm, max_timing)
                errors += 1
                continue
            logging.info('dimm #%d timings: %s', dimm, max_timing)
            max_speed = int(m.group('speed'))
            keyval['speed_dimm_%d' % dimm] = max_speed
            if max_speed < speedref:
                logging.warn('ram speed is %s', max_timing)
                logging.warn('ram speed should be at least %d', speedref)
                errors += 1

        # If self.error is not zero, there were errors.
        if errors > 0:
            raise error.TestFail('Found %d incorrect values' % errors)

        self.write_perf_keyval(keyval)
