# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging, os, re, shutil, time

import common
from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros import cros_logging, sys_power
from autotest_lib.client.cros import flimflam_test_path
import flimflam


class Suspender(object):
    """Class for suspend/resume measurements.

    Public attributes:
        disconnect_3G_time: Amount of seconds it took to disable 3G.
        successes[]: List of timing measurement dicts from successful suspends.
        failures[]: List of SuspendFailure exceptions from failed suspends.
        device_times[]: List of individual device suspend/resume time dicts.

    Public methods:
        suspend: Do a suspend/resume cycle. Return timing measurement dict.

    Private attributes:
        _logs: Array of /var/log/messages lines since start of suspend cycle.
        _log_file: Open file descriptor at the end of /var/log/messages.
        _logdir: Directory to store firmware logs in case of errors.
        _suspend: Set to the sys_power suspend function to use.
        _throw: Set to have SuspendFailure exceptions raised to the caller.
        _reset_pm_print_times: Set to deactivate pm_print_times after the test.
        _restart_tlsdated: Set to restart tlsdated after the test.

    Private methods:
        __init__: Shuts off tlsdated for duration of test, disables 3G
        __del__: Restore tlsdated (must run eventually, but GC delay no problem)
        _set_pm_print_times: Enable/disable kernel device suspend timing output.
        _check_failure_log: Check /sys/.../suspend_stats for new failures.
        _ts: Returns a timestamp from /var/run/power_manager/last_resume_timings
        _hwclock_ts: Read RTC timestamp left on resume in hwclock-on-resume
        _device_resume_time: Read seconds overall device resume took from logs.
        _individual_device_times: Reads individual device suspend/resume times.
    """

    # board-specific "time to suspend" values determined empirically
    # TODO: migrate to separate file with http://crosbug.com/38148
    _SUSPEND_DELAY = {
        # TODO: Reevaluate this when http://crosbug.com/38460 is fixed
        'daisy': 5,

        # TODO: Reevaluate this when http://crosbug.com/36766 is fixed
        'x86-zgb': 4,

        # TODO: Reevaluate these when http://crosbug.com/38225 is fixed
        'x86-mario': 9,
        'x86-alex': 8,

        # TODO: Reevaluate this when http://crosbug.com/38239 is fixed
        # edit: bumping this even more to make it work for now...
        # TODO(jwerner): figure out how to deal with the UMH/firmware delays
        # once crosbug/p 16981 and 17115 are solved.
        'stout': 10,

        # Lumpy and Stumpy need high values, because it seems to mitigate their
        # RTC interrupt problem. See http://crosbug.com/36004

        # TODO: Reevaluate these when http://crbug.com/223313 is fixed
        'lumpy': 7,
        'stumpy': 7,
        'butterfly': 7,

        # Hard disk sync and overall just slow
        'parrot': 8,
        'kiev': 9,
    }

    # alarm/not_before value guaranteed to raise EarlyWakeup in _hwclock_ts
    _EARLY_WAKEUP = 2147483647

    # File written by send_metrics_on_resume containing timing information about
    # the last resume.
    _TIMINGS_FILE = '/var/run/power_manager/root/last_resume_timings'

    # Amount of lines to dump from the eventlog on an EarlyWakeup. Should be
    # enough to include ACPI Wake Reason... 10 should be far on the safe side.
    _RELEVANT_EVENTLOG_LINES = 10

    # Sanity check value to catch overlong resume times (from missed RTC wakes)
    _MAX_RESUME_TIME = 10

    # File written by powerd_suspend containing the hwclock time at resume.
    HWCLOCK_FILE = '/var/run/power_manager/root/hwclock-on-resume'

    def __init__(self, logdir, method=sys_power.do_suspend,
                 throw=False, device_times=False):
        """Prepare environment for suspending."""
        self.disconnect_3G_time = 0
        self.successes = []
        self.failures = []
        self._logdir = logdir
        self._suspend = method
        self._throw = throw
        self._reset_pm_print_times = False
        self._restart_tlsdated = False
        self._log_file = None
        if device_times:
            self.device_times = []

        # stop tlsdated, make sure we/hwclock have /dev/rtc for ourselves
        if utils.system_output('initctl status tlsdated').find('start') != -1:
            utils.system('initctl stop tlsdated')
            self._restart_tlsdated = True
            # give process's file descriptors time to asynchronously tear down
            time.sleep(0.1)

        # prime powerd_suspend RTC timestamp saving and make sure hwclock works
        utils.open_write_close(self.HWCLOCK_FILE, '')
        hwclock_output = utils.system_output('hwclock -r --debug --utc',
                                             ignore_status=True)
        if hwclock_output.find('Using /dev interface') == -1:
            raise error.TestError('hwclock cannot find rtc: ' + hwclock_output)

        # activate device suspend timing debug output
        if hasattr(self, 'device_times'):
            if not int(utils.read_one_line('/sys/power/pm_print_times')):
                self._set_pm_print_times(True)
                self._reset_pm_print_times = True

        # Shut down 3G to remove its variability from suspend time measurements
        flim = flimflam.FlimFlam()
        service = flim.FindCellularService(0)
        if service:
            logging.info('Found 3G interface, disconnecting.')
            start_time = time.time()
            (success, status) = flim.DisconnectService(
                    service=service, wait_timeout=60)
            if success:
                logging.info('3G disconnected successfully.')
                self.disconnect_3G_time = time.time() - start_time
            else:
                logging.error('Could not disconnect: %s.' % status)
                self.disconnect_3G_time = -1


    def _set_pm_print_times(self, on):
        """Enable/disable extra suspend timing output from powerd to syslog."""
        if utils.system('echo %s > /sys/power/pm_print_times' % int(bool(on)),
                ignore_status=True):
            logging.warn('Failed to set pm_print_times to %s' % bool(on))
            del self.device_times
            self._reset_pm_print_times = False
        else:
            logging.info('Device resume times set to %s' % bool(on))


    def _reset_logs(self):
        """Throw away cached log lines and reset log pointer to current end."""
        if self._log_file:
            self._log_file.close()
        self._log_file = open('/var/log/messages')
        self._log_file.seek(0, os.SEEK_END)
        self._logs = []


    def _update_logs(self):
        """Read all lines logged since last reset into log cache."""
        self._logs += self._log_file.readlines()


    def _ts(self, name, retries=50, sleep_seconds=0.2):
        """Searches logs for last timestamp with a given suspend message."""
        # Occasionally need to retry due to races from process wakeup order
        for retry in xrange(retries + 1):
            try:
                f = open(self._TIMINGS_FILE)
                for line in f:
                    words = line.split('=')
                    if name == words[0]:
                        return float(words[1])
            except IOError:
                pass
            time.sleep(sleep_seconds)

        raise error.TestError('Could not find %s entry.' % name)


    def _hwclock_ts(self, not_before, retries=10):
        """Read the RTC resume timestamp saved by powerd_suspend."""
        for _ in xrange(retries + 1):
            early_wakeup = False
            if os.path.exists(self.HWCLOCK_FILE):
                match = re.search(r'([0-9]+) seconds since .+ (-?[0-9.]+) sec',
                                  utils.read_file(self.HWCLOCK_FILE),
                                  re.DOTALL)
                if match:
                    seconds = int(match.group(1)) + float(match.group(2))
                    logging.debug('RTC resume timestamp read: %f' % seconds)
                    if seconds >= not_before:
                        return seconds
                    early_wakeup = True
            time.sleep(0.2)
        if early_wakeup:
            logging.debug('Early wakeup, dumping eventlog if it exists:\n' +
                    utils.system_output('mosys eventlog list | tail -n %d' %
                    self._RELEVANT_EVENTLOG_LINES, ignore_status=True))
            raise sys_power.EarlyWakeupError('Woke up at %f' % seconds)
        if utils.get_board() in ['lumpy', 'stumpy', 'kiev']:
            logging.debug('RTC read failure (crosbug/36004), dumping nvram:\n' +
                    utils.system_output('mosys nvram dump', ignore_status=True))
            return None
        raise error.TestError('Broken RTC timestamp: ' +
                              utils.read_file(self.HWCLOCK_FILE))


    def _firmware_resume_time(self):
        """Calculate seconds for firmware resume from logged TSC. (x86 only)"""
        if utils.get_arch() not in ['i686', 'x86_64']:
            # TODO: support this on ARM somehow
            return 0
        regex = re.compile(r'TSC at resume: (\d+)$')
        freq = 1000 * int(utils.read_one_line(
                '/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq'))
        for line in reversed(self._logs):
            match = regex.search(line)
            if match:
                return float(match.group(1)) / freq

        raise error.TestError('Failed to find TSC resume value in syslog.')


    def _device_resume_time(self):
        """Read amount of seconds for overall device resume from syslog."""
        regex = re.compile(r'PM: resume of devices complete after ([0-9.]+)')
        for line in reversed(self._logs):
            match = regex.search(line)
            if match:
                return float(match.group(1)) / 1000

        raise error.TestError('Failed to find device resume time in syslog.')


    def _individual_device_times(self, start_resume):
        """Return dict of individual device suspend and resume times."""
        self.device_times.append(dict())
        regex = re.compile(r'call ([^ ]+)\+ returned 0 after ([0-9]+) usecs')
        for line in self._logs:
            match = regex.search(line)
            if match:
                key = 'seconds_dev_' + match.group(1).replace(':', '-')
                secs = float(match.group(2)) / 1e6
                if cros_logging.extract_kernel_timestamp(line) > start_resume:
                    key += '_resume'
                else:
                    key += '_suspend'
                if key in self.device_times[-1]:
                    logging.warn('Duplicate entry for %s: +%f' % (key, secs))
                    self.device_times[-1][key] += secs
                else:
                    logging.debug('%s: %f' % (key, secs))
                    self.device_times[-1][key] = secs


    def suspend(self, duration=10):
        """
        Do a single suspend for 'duration' seconds. Estimates the amount of time
        it takes to suspend for a board (see _SUSPEND_DELAY), so the actual RTC
        wakeup delay will be longer. Returns None on errors, or raises the
        exception when _throw is set. Returns a dict of general measurements,
        or a tuple (general_measurements, individual_device_times) when
        _device_times is set.
        """
        try:
            iteration = len(self.failures) + len(self.successes) + 1

            # Retry suspend until we get clear HwClock reading on buggy boards
            for _ in xrange(10):
                self._reset_logs()
                utils.system('sync')
                board_delay = self._SUSPEND_DELAY.get(utils.get_board(), 3)
                try:
                    alarm = self._suspend(duration + board_delay)
                except sys_power.EarlyWakeupError:
                    # might be a SuspendAbort... we check for it ourselves below
                    alarm = self._EARLY_WAKEUP

                # look for errors
                if os.path.exists('/sys/firmware/log'):
                    for msg in re.findall(r'^.*ERROR.*$',
                            utils.read_file('/sys/firmware/log'), re.M):
                        for pattern in sys_power.FirmwareError.WHITELIST:
                            if re.search(pattern, msg):
                                logging.info('Whitelisted FW error: ' + msg)
                                break
                        else:
                            firmware_log = os.path.join(self._logdir,
                                    'firmware.log.' + str(iteration))
                            shutil.copy('/sys/firmware/log', firmware_log)
                            logging.info('Saved firmware log: ' + firmware_log)
                            raise sys_power.FirmwareError(msg.strip('\r\n '))

                warning_regex = re.compile(r' kernel: \[.*WARNING:')
                abort_regex = re.compile(r' kernel: \[.*Freezing of tasks abort'
                        r'|powerd_suspend\[.*Cancel suspend at kernel')
                unknown_regex = re.compile(r'powerd_suspend\[\d+\]: Error')
                start_regex = re.compile(r'powerd_suspend\[\d+\]: Going to sus')
                start_found = False
                # TODO(scottz): warning_monitor crosbug.com/38092
                self._update_logs()
                for i in xrange(len(self._logs)):
                    line = self._logs[i]
                    if warning_regex.search(line):
                        # match the source file from the WARNING line, and the
                        # actual error text by peeking two lines below that
                        src = cros_logging.strip_timestamp(line)
                        text = cros_logging.strip_timestamp(self._logs[i + 2])
                        for p1, p2 in sys_power.KernelError.WHITELIST:
                            if re.search(p1, src) and re.search(p2, text):
                                logging.info('Whitelisted KernelError: %s', src)
                                break
                        else:
                            raise sys_power.KernelError("%s\n%s" % (src, text))
                    if abort_regex.search(line):
                        raise sys_power.SuspendAbort(
                                cros_logging.strip_timestamp(line))
                    if unknown_regex.search(line):
                        raise sys_power.SuspendFailure('Unidentified problem.')
                    if not start_found and start_regex.search(line):
                        start_found = True
                if not start_found:
                    raise error.TestError('Sanity check failed: system did not '
                            'actually try to suspend.')

                hwclock_ts = self._hwclock_ts(alarm)
                if hwclock_ts:
                    break
            else:
                raise error.TestError('Could not read RTC after 10 retries.')

            # calculate general measurements
            start_resume = self._ts('start_resume_time')
            kernel_down = (self._ts('end_suspend_time') -
                           self._ts('start_suspend_time'))
            kernel_up = self._ts('end_resume_time') - start_resume
            self._update_logs()
            devices_up = self._device_resume_time()
            total_up = hwclock_ts - alarm
            firmware_up = self._firmware_resume_time()
            board_up = total_up - kernel_up - firmware_up
            try:
                cpu_up = self._ts('cpu_ready_time', 0) - start_resume
            except error.TestError:
                # can be missing on non-SMP machines
                cpu_up = None
            if total_up > self._MAX_RESUME_TIME:
                raise error.TestError('Sanity check failed: missed RTC wakeup.')

            logging.info('Success(%d): %g down, %g up, %g board, %g firmware, '
                         '%g kernel, %g cpu, %g devices',
                         iteration, kernel_down, total_up, board_up,
                         firmware_up, kernel_up, cpu_up, devices_up)
            self.successes.append({
                'seconds_system_suspend': kernel_down,
                'seconds_system_resume': total_up,
                'seconds_system_resume_firmware': firmware_up + board_up,
                'seconds_system_resume_firmware_cpu': firmware_up,
                'seconds_system_resume_firmware_ec': board_up,
                'seconds_system_resume_kernel': kernel_up,
                'seconds_system_resume_kernel_cpu': cpu_up,
                'seconds_system_resume_kernel_dev': devices_up,
                })

            if hasattr(self, 'device_times'):
                self._individual_device_times(start_resume)
                return (self.successes[-1], self.device_times[-1])
            else:
                return self.successes[-1]

        except sys_power.SuspendFailure as ex:
            message = '%s(%d): %s' % (type(ex).__name__, iteration, ex)
            logging.error(message)
            self.failures.append(ex)
            if self._throw:
                raise error.TestFail(message)
            return None


    def finalize(self):
        """Restore normal environment (not turning 3G back on for now...)"""
        if os.path.exists(self.HWCLOCK_FILE):
            os.remove(self.HWCLOCK_FILE)
            if self._restart_tlsdated:
                utils.system('initctl start tlsdated')
            if self._reset_pm_print_times:
                self._set_pm_print_times(False)


    def __del__(self):
        self.finalize()
