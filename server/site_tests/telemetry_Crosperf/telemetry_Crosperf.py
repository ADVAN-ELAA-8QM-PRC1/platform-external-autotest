# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import logging
import re
import os
import pprint
import StringIO

import common
from autotest_lib.client.common_lib import error
from autotest_lib.server import test
from autotest_lib.server import utils


TELEMETRY_TIMEOUT_MINS = 60
CHROME_SRC_ROOT = '/var/cache/chromeos-cache/distfiles/target/'
CLIENT_CHROME_ROOT = '/usr/local/telemetry/src'
RUN_BENCHMARK  = 'tools/perf/run_benchmark'

# Result Statuses
SUCCESS_STATUS = 'SUCCESS'
WARNING_STATUS = 'WARNING'
FAILED_STATUS = 'FAILED'

# Regex for the RESULT output lines understood by chrome buildbot.
# Keep in sync with
# chromium/tools/build/scripts/slave/performance_log_processor.py.
RESULTS_REGEX = re.compile(r'(?P<IMPORTANT>\*)?RESULT '
                           r'(?P<GRAPH>[^:]*): (?P<TRACE>[^=]*)= '
                           r'(?P<VALUE>[\{\[]?[-\d\., ]+[\}\]]?)('
                           r' ?(?P<UNITS>.+))?')
HISTOGRAM_REGEX = re.compile(r'(?P<IMPORTANT>\*)?HISTOGRAM '
                             r'(?P<GRAPH>[^:]*): (?P<TRACE>[^=]*)= '
                             r'(?P<VALUE_JSON>{.*})(?P<UNITS>.+)?')


def _find_chrome_root_dir():
    # Look for chrome source root, either externally mounted, or inside
    # the chroot.  Prefer chrome-src-internal source tree to chrome-src.
    sources_list = ('chrome-src-internal', 'chrome-src')

    dir_list = [os.path.join(CHROME_SRC_ROOT, x) for x in sources_list]
    if 'CHROME_ROOT' in os.environ:
        dir_list.insert(0, os.environ['CHROME_ROOT'])

    for dir in dir_list:
        if os.path.exists(dir):
            chrome_root_dir = dir
            break
    else:
        raise error.TestError('Chrome source directory not found.')

    logging.info('Using Chrome source tree at %s', chrome_root_dir)
    return os.path.join(chrome_root_dir, 'src')


def _ensure_deps(dut, test_name):
    """
    Ensure the dependencies are locally available on DUT.

    @param dut: The autotest host object representing DUT.
    @param test_name: Name of the telemetry test.
    """
    # Get DEPs using host's telemetry.
    chrome_root_dir = _find_chrome_root_dir()
    format_string = ('python %s/tools/perf/fetch_benchmark_deps.py %s')
    command = format_string % (chrome_root_dir, test_name)
    logging.info('Getting DEPs: %s', command)
    stdout = StringIO.StringIO()
    stderr = StringIO.StringIO()
    try:
        result = utils.run(command, stdout_tee=stdout,
                           stderr_tee=stderr)
    except error.CmdError as e:
        logging.debug('Error occurred getting DEPs: %s\n %s\n',
                      stdout.getvalue(), stderr.getvalue())
        raise error.TestFail('Error occurred while getting DEPs.')

    # Download DEPs to DUT.
    # send_file() relies on rsync over ssh. Couldn't be better.
    stdout_str = stdout.getvalue()
    stdout.close()
    stderr.close()
    for dep in stdout_str.split():
        src = os.path.join(chrome_root_dir, dep)
        dst = os.path.join(CLIENT_CHROME_ROOT, dep)
        if not os.path.isfile(src):
            raise error.TestFail('Error occurred while saving DEPs.')
        logging.info('Copying: %s -> %s', src, dst)
        try:
            dut.send_file(src, dst)
        except:
            raise error.TestFail('Error occurred while sending DEPs to dut.\n')


class TelemetryResult(object):
    """Class to represent the results of a telemetry run.

    This class represents the results of a telemetry run, whether it ran
    successful, failed or had warnings. -- Copied from the old
    autotest/files/server/cros/telemetry_runner.py.
    """


    def __init__(self, exit_code=0, stdout='', stderr=''):
        """Initializes this TelemetryResultObject instance.

        @param status: Status of the telemtry run.
        @param stdout: Stdout of the telemetry run.
        @param stderr: Stderr of the telemetry run.
        """
        if exit_code == 0:
            self.status = SUCCESS_STATUS
        else:
            self.status = FAILED_STATUS

        # A list of perf values, e.g.
        # [{'graph': 'graphA', 'trace': 'page_load_time',
        #   'units': 'secs', 'value':0.5}, ...]
        self.perf_data = []
        self._stdout = stdout
        self._stderr = stderr
        self.output = '\n'.join([stdout, stderr])


    def _cleanup_perf_string(self, str):
        """Clean up a perf-related string by removing illegal characters.

        Perf keys stored in the chromeOS database may contain only letters,
        numbers, underscores, periods, and dashes.  Transform an inputted
        string so that any illegal characters are replaced by underscores.

        @param str: The perf string to clean up.

        @return The cleaned-up perf string.
        """
        return re.sub(r'[^\w.-]', '_', str)


    def _cleanup_units_string(self, units):
        """Cleanup a units string.

        Given a string representing units for a perf measurement, clean it up
        by replacing certain illegal characters with meaningful alternatives.
        Any other illegal characters should then be replaced with underscores.

        Examples:
            count/time -> count_per_time
            % -> percent
            units! --> units_
            score (bigger is better) -> score__bigger_is_better_
            score (runs/s) -> score__runs_per_s_

        @param units: The units string to clean up.

        @return The cleaned-up units string.
        """
        if '%' in units:
            units = units.replace('%', 'percent')
        if '/' in units:
            units = units.replace('/','_per_')
        return self._cleanup_perf_string(units)


    def parse_benchmark_results(self):
        """Parse the results of a telemetry benchmark run.

        Stdout has the output in RESULT block format below.

        The lines of interest start with the substring "RESULT".  These are
        specially-formatted perf data lines that are interpreted by chrome
        builbot (when the Telemetry tests run for chrome desktop) and are
        parsed to extract perf data that can then be displayed on a perf
        dashboard.  This format is documented in the docstring of class
        GraphingLogProcessor in this file in the chrome tree:

        chromium/tools/build/scripts/slave/process_log_utils.py

        Example RESULT output lines:
        RESULT average_commit_time_by_url: http___www.ebay.com= 8.86528 ms
        RESULT CodeLoad: CodeLoad= 6343 score (bigger is better)
        RESULT ai-astar: ai-astar= [614,527,523,471,530,523,577,625,614,538] ms

        Currently for chromeOS, we can only associate a single perf key (string)
        with a perf value.  That string can only contain letters, numbers,
        dashes, periods, and underscores, as defined by write_keyval() in:

        chromeos/src/third_party/autotest/files/client/common_lib/
        base_utils.py

        We therefore parse each RESULT line, clean up the strings to remove any
        illegal characters not accepted by chromeOS, and construct a perf key
        string based on the parsed components of the RESULT line (with each
        component separated by a special delimiter).  We prefix the perf key
        with the substring "TELEMETRY" to identify it as a telemetry-formatted
        perf key.

        Stderr has the format of Warnings/Tracebacks. There is always a default
        warning of the display enviornment setting, followed by warnings of
        page timeouts or a traceback.

        If there are any other warnings we flag the test as warning. If there
        is a traceback we consider this test a failure.
        """
        if not self._stdout:
            # Nothing in stdout implies a test failure.
            logging.error('No stdout, test failed.')
            self.status = FAILED_STATUS
            return

        stdout_lines = self._stdout.splitlines()
        num_lines = len(stdout_lines)
        for line in stdout_lines:
            results_match = RESULTS_REGEX.search(line)
            histogram_match = HISTOGRAM_REGEX.search(line)
            if results_match:
                self._process_results_line(results_match)
            elif histogram_match:
                self._process_histogram_line(histogram_match)

        pp = pprint.PrettyPrinter(indent=2)
        logging.debug('Perf values: %s', pp.pformat(self.perf_data))

        if self.status is SUCCESS_STATUS:
            return

        # Otherwise check if simply a Warning occurred or a Failure,
        # i.e. a Traceback is listed.
        self.status = WARNING_STATUS
        for line in self._stderr.splitlines():
            if line.startswith('Traceback'):
                self.status = FAILED_STATUS

    def _process_results_line(self, line_match):
        """Processes a line that matches the standard RESULT line format.

        Args:
          line_match: A MatchObject as returned by re.search.
        """
        match_dict = line_match.groupdict()
        graph_name = self._cleanup_perf_string(match_dict['GRAPH'].strip())
        trace_name = self._cleanup_perf_string(match_dict['TRACE'].strip())
        units = self._cleanup_units_string(
                (match_dict['UNITS'] or 'units').strip())
        value = match_dict['VALUE'].strip()
        unused_important = match_dict['IMPORTANT'] or False  # Unused now.

        if value.startswith('['):
            # A list of values, e.g., "[12,15,8,7,16]".  Extract just the
            # numbers, compute the average and use that.  In this example,
            # we'd get 12+15+8+7+16 / 5 --> 11.6.
            value_list = [float(x) for x in value.strip('[],').split(',')]
            value = float(sum(value_list)) / len(value_list)
        elif value.startswith('{'):
            # A single value along with a standard deviation, e.g.,
            # "{34.2,2.15}".  Extract just the value itself and use that.
            # In this example, we'd get 34.2.
            value_list = [float(x) for x in value.strip('{},').split(',')]
            value = value_list[0]  # Position 0 is the value.
        elif re.search('^\d+$', value):
            value = int(value)
        else:
            value = float(value)

        self.perf_data.append({'graph':graph_name, 'trace': trace_name,
                               'units': units, 'value': value})

    def _process_histogram_line(self, line_match):
        """Processes a line that matches the HISTOGRAM line format.

        Args:
          line_match: A MatchObject as returned by re.search.
        """
        match_dict = line_match.groupdict()
        graph_name = self._cleanup_perf_string(match_dict['GRAPH'].strip())
        trace_name = self._cleanup_perf_string(match_dict['TRACE'].strip())
        units = self._cleanup_units_string(
                (match_dict['UNITS'] or 'units').strip())
        histogram_json = match_dict['VALUE_JSON'].strip()
        unused_important = match_dict['IMPORTANT'] or False  # Unused now.
        histogram_data = json.loads(histogram_json)

        # Compute geometric mean
        count = 0
        sum_of_logs = 0
        for bucket in histogram_data['buckets']:
            mean = (bucket['low'] + bucket['high']) / 2.0
            if mean > 0:
                sum_of_logs += math.log(mean) * bucket['count']
                count += bucket['count']

        value = math.exp(sum_of_logs / count) if count > 0 else 0.0

        self.perf_data.append({'graph':graph_name, 'trace': trace_name,
                               'units': units, 'value': value})


class telemetry_Crosperf(test.test):
    """Run one or more telemetry benchmarks under the crosperf script."""
    version = 1

    def run_once(self, args, client_ip='', dut=None):
        """
        Run a single telemetry test.

        @param args: A dictionary of the arguments that were passed
                to this test.
        @param client_ip: The ip address of the DUT
        @param dut: The autotest host object representing DUT.

        @returns A TelemetryResult instance with the results of this execution.
        """
        test_name = args['test']
        test_args = ''
        if 'test_args' in args:
            test_args = args['test_args']

        # Decide whether the test will run locally or by a remote server.
        if 'run_local' in args and args['run_local'].lower() == 'true':
            # The telemetry scripts will run on DUT.
            _ensure_deps(dut, test_name)
            format_string = ('python %s --browser=system %s %s')
            command = format_string % (os.path.join(CLIENT_CHROME_ROOT,
                                                    RUN_BENCHMARK),
                                       test_args, test_name)
            runner = dut
        else:
            # The telemetry scripts will run on server.
            format_string = ('python %s --browser=cros-chrome --remote=%s '
                             '%s %s')
            command = format_string % (os.path.join(_find_chrome_root_dir(),
                                                    RUN_BENCHMARK),
                                       client_ip, test_args, test_name)
            runner = utils

        # Run the test.
        stdout = StringIO.StringIO()
        stderr = StringIO.StringIO()
        try:
            logging.info('CMD: %s', command)
            result = runner.run(command, stdout_tee=stdout, stderr_tee=stderr,
                                timeout=TELEMETRY_TIMEOUT_MINS*60)
            exit_code = result.exit_status
        except error.CmdError as e:
            logging.debug('Error occurred executing telemetry.')
            exit_code = e.result_obj.exit_status
            raise error.TestFail('An error occurred while executing '
                                 'telemetry test.')
        finally:
            stdout_str = stdout.getvalue()
            stderr_str = stderr.getvalue()
            stdout.close()
            stderr.close()


        # Parse the result.
        logging.debug('Telemetry completed with exit code: %d.'
                      '\nstdout:%s\nstderr:%s', exit_code,
                      stdout_str, stderr_str)
        logging.info('Telemetry completed with exit code: %d.'
                     '\nstdout:%s\nstderr:%s', exit_code,
                     stdout_str, stderr_str)

        result = TelemetryResult(exit_code=exit_code,
                                 stdout=stdout_str,
                                 stderr=stderr_str)

        result.parse_benchmark_results()
        for data in result.perf_data:
            self.output_perf_value(description=data['trace'],
                                   value=data['value'],
                                   units=data['units'],
                                   graph=data['graph'])

        return result
