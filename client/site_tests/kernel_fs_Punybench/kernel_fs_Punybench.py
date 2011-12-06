#!/usr/bin/python
#
# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import optparse
import os, shutil, re, string
from autotest_lib.client.bin import utils, test

class kernel_fs_Punybench(test.test):
    """Run a selected subset of the puny benchmarks
    """
    version = 1
    Bin = '/usr/local/opt/punybench/bin/'


    def initialize(self):
        self.results = []
        self.job.drop_caches_between_iterations = True


    def _run(self, cmd, args):
        """Run a puny benchmark

        Prepends the path to the puny benchmark bin.
        """
        result = utils.system_output(
            os.path.join(self.Bin, cmd) + ' ' + args)
        logging.debug(result)
        return result


    @staticmethod
    def _find_max(tag, text):
        """Find the max in a memcpy result.

        Args:
          tag: name of sub-test to select from text.
          text: output from memcpy test.
        Returns:
          Best result from that sub-test.
        """
        re_float = r"[+-]? *(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
        r1 = re.search(tag + ".*\n(\d.*\n)+", text)
        r2 = re.findall(r"\d+\. (" + re_float + r") M.*\n", r1.group(0))
        return max(float(result) for result in r2)


    def _memcpy(self):
        """Measure memory to memory copy.

        The size has to be large enough that it doesn't fit
        in the cache. We then take the best of serveral runs
        so we have a guarenteed not to exceed number.

        Several different ways are used to move memory.
        """
        size = '0x4000000'
        loops = '4'
        iterations = '10'
        args  = '-z' + size
        args += ' -i' + iterations
        args += ' -l' + loops
        result = self._run('memcpy', args)

        for tag in ['memcpy', '32bit', '64bit']:
            max = self._find_max(tag, result)
            self.write_perf_keyval({tag: max})


    def _memcpy_test(self):
        """Test the various caches and alignments

        WARNING: test will have to be changed if cache sizes change.
        """
        result = self._run('memcpy_test', "")
        r1 = re.search(r"L1 cache.*\n.*\n.*", result)
        r2 = re.search(r"[^\s]+ MiB/s$", r1.group(0))
        self.write_perf_keyval({'L1cache': r2.group()})

        r1 = re.search(r"L2 cache.*\n.*\n.*", result)
        r2 = re.search(r"[^\s]+ MiB/s$", r1.group(0))
        self.write_perf_keyval({'L2cache': r2.group()})

        r1 = re.search(r"SDRAM.*\n.*\n.*", result)
        r2 = re.search(r"[^\s]+ MiB/s$", r1.group(0))
        self.write_perf_keyval({'SDRAM': r2.group()})


    def _threadtree(self):
        """Create and manipulate directory trees.

        Threadtree creates a directory tree with files for each task.
        It then copies that tree then deletes it.
        """
        directory = '/usr/local/_Dir'
        iterations = '4'
        tasks = '2'
        width = '3'
        depth = '5'
        args  = '-d' + directory
        args += ' -i' + iterations
        args += ' -t' + tasks
        args += ' -w' + width
        args += ' -k' + depth
        result = self._run('threadtree', args)
        r1 = re.search(r"timer avg= *([^\s]*).*$", result)
        timer_avg = float(r1.groups()[0])
        p = int(tasks) * pow(int(width), int(depth) + 1) / timer_avg
        self.write_perf_keyval({'threadtree': p})


    def _uread(self):
        """Read a large file.

        The size should be picked so the file will
        not fit in memory.
        """
        file = '/usr/local/xyzzy'
        size = '0x200000000'
        loops = '4'
        iterations = '1'
        args = '-f' + file
        args += ' -z' + size
        args += ' -i' + iterations
        args += ' -l' + loops
        args += ' -b12'
        result = self._run('uread', args)
        r1 = re.search(r"([^\s]+ MiB/s).*$", result)
        value = r1.groups()[0]
        self.write_perf_keyval({'uread': value})


    def _ureadrand(self):
        """Read randomly a large file
        """
        file = '/usr/local/xyzzy'
        size = '0x200000000'
        loops = '4'
        iterations = '100000'
        args = '-f' + file
        args += ' -z' + size
        args += ' -i' + iterations
        args += ' -l' + loops
        args += ' -b12'
        result = self._run('ureadrand', args)
        r1 = re.search(r"([^\s]+ MiB/s).*$", result)
        value = r1.groups()[0]
        self.write_perf_keyval({'ureadrand': value})


    def _parse_args(self, args):
        """Parse input arguments to this autotest.

        Args:
          args: List of arguments to parse.
        Returns:
          opts: Options, as per optparse.
          args: Non-option arguments, as per optparse.
        """
        parser = optparse.OptionParser()
        parser.add_option('--nomem', dest='want_mem_tests',
                          action='store_false', default=True,
                          help='Skip memory tests.')
        parser.add_option('--nodisk', dest='want_disk_tests',
                          action='store_false', default=True,
                          help='Skip disk tests.')
        # Preprocess the args to remove quotes before/after each one if they
        # exist.  This is necessary because arguments passed via
        # run_remote_tests.sh may be individually quoted, and those quotes must
        # be stripped before they are parsed.
        return parser.parse_args(map(lambda arg: arg.strip('\'\"'), args))


    def run_once(self, args=[]):
        """Run the PyAuto performance tests.

        Args:
          args: Either space-separated arguments or a list of string arguments.
              If this is a space separated string, we'll just call split() on
              it to get a list.  The list will be sent to optparse for parsing.
        """
        if isinstance(args, str):
            args = args.split()
        options, test_args = self._parse_args(args)

        if test_args:
            raise error.TestFail("Unknown args: %s" % repr(test_args))

        utils.system_output('stop ui')
        if options.want_mem_tests:
            self._memcpy_test()
            self._memcpy()
        if options.want_disk_tests:
            self._threadtree()
            self._uread()
            self._ureadrand()
        utils.system_output('start ui')
