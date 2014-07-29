#!/usr/bin/env python

# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# This file defines script for getting host_history for DUTs in Autotest.

"""Script for checking host history for a selected group of hosts.

Currently only supports aggregating stats for each host.
TODOs:
    Write unit tests for host_history_utils
    Aggregate stats for > 1 host
    Incorporate jobs

Example usage:
    python host_history.py --index=cautotest -n 10000 \
                           -l 24 --board=daisy

Output:

    trying to get all duts...
    making the query...
    found all duts. Time to get host_history.
    usage stats for host: chromeos2-row5-rack1-host6
      2014-07-24 10:24:07 - 2014-07-25 10:24:07
        Verifying: 0.00 %
        Running: 0.00 %
        Ready: 100.00 %
        Repairing: 0.00 %
        Repair Failed: 0.00 %
        Cleaning: 0.00 %
        Pending: 0.00 %
        Resetting: 0.00 %
        Provisioning: 0.00 %
        Locked: 0.00 %
    - -- --- ---- ----- ---- --- -- -

Example usage2: more than one host:
    python host_history.py --index=cautotest  -n 1000 -l 2 \
    --hosts chromeos2-row5-rack4-host6 chromeos4-row12-rack11-host2

    ['chromeos2-row5-rack4-host6', 'chromeos4-row12-rack11-host2']
    found all duts. Time to get host_history.
    usage stats for host: chromeos2-row5-rack4-host6
     2014-07-25 13:02:22 - 2014-07-25 15:02:22
     Num entries found in this interval: 0
        Verifying:        0.00 %
        Running:          0.00 %
        Ready:            100.00 %
        Repairing:        0.00 %
        Repair Failed:    0.00 %
        Cleaning:         0.00 %
        Pending:          0.00 %
        Resetting:        0.00 %
        Provisioning:     0.00 %
        Locked:           0.00 %
    - -- --- ---- ----- ---- --- -- -

    usage stats for host: chromeos4-row12-rack11-host2
     2014-07-25 13:02:22 - 2014-07-25 15:02:22
     Num entries found in this interval: 138
        Verifying:        0.00 %
        Running:          70.45 %
        Ready:            17.79 %
        Repairing:        0.00 %
        Repair Failed:    0.00 %
        Cleaning:         0.00 %
        Pending:          1.24 %
        Resetting:        10.78 %
        Provisioning:     0.00 %
        Locked:           0.00 %
    - -- --- ---- ----- ---- --- -- -
"""

import multiprocessing
import multiprocessing.pool
import argparse
import time

import common
import host_history_utils
from autotest_lib.server import frontend


def should_care(board, pool, dut):
    """Whether we should care to print stats for this dut out

    @param board: board we want, i.e. 'daisy'
    @param pool: pool we want, i.e. 'bvt'
    @param dut: Host object representing DUT.
    @returns: True if the dut's stats should be counted.
    """
    if not board and not pool:
        return True
    found_board = False if board else True
    found_pool = False if pool else True
    for label in dut.labels:
        if label.startswith('pool:%s' % (pool)):
            found_pool = True
        if label.startswith('board:%s' % (board)):
            found_board = True
    return found_board and found_pool


def main():
    """main script. """
    parser = argparse.ArgumentParser()
    parser.add_argument('--index', type=str, dest='index')
    parser.add_argument('-v', action='store_true', dest='verbose',
                        default=False,
                        help='--show to print out ALL entries.')
    parser.add_argument('-n', type=int, dest='size',
                        help='Maximum number of entries to return.',
                        default=10000)
    parser.add_argument('-l', type=float, dest='last',
                        help='last hours to search results across',
                        default=24)
    parser.add_argument('--board', type=str, dest='board',
                        help='restrict query by board, not implemented yet',
                        default=None)
    parser.add_argument('--pool', type=str, dest='pool',
                        help='restrict query by pool, not implemented yet',
                        default=None)
    parser.add_argument('--hosts', nargs='+', dest='hosts',
                        help='Enter space deliminated hostnames',
                        default=[])
    options = parser.parse_args()


    time_now = time.time()
    if options.hosts:
        hosts = options.hosts
    else:
        hosts = []
        print 'trying to get all duts...'
        afe = frontend.AFE()
        print 'making the query...'
        duts = afe.get_hosts()
        for dut in duts:
            if should_care(options.board, options.pool, dut):
                hosts.append(dut.hostname)
    print 'found all duts. Time to get host_history.'

    args = []
    for hostname in hosts:
        args.append({'t_start': time_now - 3600*options.last,
             't_end': time_now,
             'hostname': hostname,
             'size': options.size,
             'print_each_interval': options.verbose})

    # Parallizing this process.
    pool = multiprocessing.pool.ThreadPool()
    results = pool.imap_unordered(get_host_history, args)
    time.sleep(5)
    for result in results:
        print result


def get_host_history(input):
    """Gets the host history.

    @param input: A dictionary of input arguments to
                  host_history_utils.host_history_stats.
                  Must contain these keys:
                    't_start',
                    't_end',
                    'hostname',
                    'size,'
                    'print_each_interval'
    @returns: result which is a ordered dictionary with
        key being (ti, tf) and value being (status, dbg_str)
        status = status of the host. e.g. 'Repair Failed'
        ti is the beginning of the interval where the DUT's has that status
        tf is the end of the interval where the DUT has that status
        dbg_str is the self.dbg_str from the host. An example would be:
            'Special Task 18858263 (host 172.22.169.106,
                                    task Repair,
                                    time 2014-07-27 20:01:15)'
    """
    result = host_history_utils.host_history_stats_report(
            t_start=input['t_start'],
            t_end=input['t_end'],
            hostname=input['hostname'],
            size=input['size'],
            print_each_interval=input['print_each_interval'])
    return result


if __name__ == '__main__':
    main()
