# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging, re, threading, time

from autotest_lib.client.cros.crash_test import CrashTest
from autotest_lib.server import autotest, test
from autotest_lib.client.common_lib import error

_WAIT_DELAY = 15
_LONG_TIMEOUT = 200
_SUSPEND_RESUME_BOARDS = ['daisy', 'panther']
_LOGIN_FAILED = 'DEVICE COULD NOT LOGIN!'
_SUSPEND_FAILED = 'Failed to SUSPEND within timeout'
_RESUME_FAILED = 'Failed to RESUME within timeout'
_CRASH_PATHS = [CrashTest._SYSTEM_CRASH_DIR.replace("/crash",""),
                CrashTest._FALLBACK_USER_CRASH_DIR.replace("/crash",""),
                CrashTest._USER_CRASH_DIRS.replace("/crash","")]

class platform_ExternalUsbPeripherals(test.test):
    """Uses servo to repeatedly connect/remove USB devices during boot."""
    version = 1


    def getPluggedUsbDevices(self):
        """Determines the external USB devices plugged

        @returns plugged_list: List of plugged usb devices names

        """
        lsusb_output = self.host.run('lsusb').stdout.strip()
        items = lsusb_output.split('\n')
        plugged_list = []
        unnamed_device_count = 1
        for item in items:
            columns = item.split(' ')
            if len(columns) == 6 or len(' '.join(columns[6:]).strip()) == 0:
                logging.debug('Unnamed device located, adding generic name.')
                name = 'Unnamed device %d' % unnamed_device_count
                unnamed_device_count += 1
            else:
                name = ' '.join(columns[6:]).strip()
            #Avoid servo components
            if not name.startswith('Standard Microsystems Corp'):
                plugged_list.append(name)
        return plugged_list


    def set_hub_power(self, on=True):
        """Setting USB hub power status

        @param on: To power on the servo-usb hub or not

        """
        reset = 'off'
        if not on:
            reset = 'on'
        self.host.servo.set('dut_hub1_rst1', reset)
        self.pluged_status = on


    def action_login(self):
        """Login i.e. runs running client test

        @exception TestFail failed to login within timeout.

        """
        self.autotest_client.run_test(self.client_autotest,
                                      exit_without_logout=True)


    def wait_to_disconnect(self, fail_msg,
                           suspend_timeout = _LONG_TIMEOUT):
        """Wait for DUT to suspend.

        @param fail_msg: Failure message
        @param suspend_timeout: Time in seconds to wait to disconnect

        @exception TestFail  if fail to disconnect in time
        @returns time took to disconnect
        """
        start_time = int(time.time())
        if not self.host.ping_wait_down(timeout=suspend_timeout):
            raise error.TestFail(fail_msg)
        return int(time.time()) - start_time


    def wait_to_come_up(self, fail_msg, resume_timeout):
        """Wait for DUT to resume.

        @param fail_msg: Failure message
        @param resume_timeout: Time in seconds to wait to come up

        @exception TestFail  if fail to come_up in time
        @returns time took to come up
        """
        start_time = int(time.time())
        if not self.host.wait_up(timeout=resume_timeout):
            raise error.TestFail(fail_msg)
        return int(time.time()) - start_time


    def wait_for_cmd_output(self, cmd, check, timeout, timeout_msg):
        """Waits till command output is meta

        @param cmd: executed command
        @param check: string to be checked for in cmd output
        @param timeout: max time in sec to wait for output
        @param timeout_msg: timeout failure message

        @returns True if check is found in command output; False otherwise
        """
        start_time = int(time.time())
        time_delta = 0
        while True:
            out = self.host.run(cmd, ignore_status=True).stdout.strip()
            if len(re.findall(check, out)) > 0:
                break
            time_delta = int(time.time()) - start_time
            if time_delta > timeout:
                 self.add_failure('%s - %d sec' % (timeout_msg, timeout))
                 return False
            time.sleep(0.5)
        return True


    def action_suspend(self):
        """Suspend i.e. close lid"""
        self.host.servo.lid_close()
        stime = self.wait_to_disconnect(_SUSPEND_FAILED)
        self.suspend_status = True
        logging.debug('--- Suspended in %d sec', stime)



    def action_resume(self):
        """Resume i.e. open lid"""
        self.host.servo.lid_open()
        rtime = self.wait_to_come_up(_RESUME_FAILED, _LONG_TIMEOUT)
        self.suspend_status = False
        logging.debug('--- Resumed in %d sec', rtime)


    def powerd_suspend_with_timeout(self, timeout):
        """Suspend the device with wakeup alarm

        @param timeout: Wait time for the suspend wakealarm

        """
        self.host.run('echo 0 > /sys/class/rtc/rtc0/wakealarm')
        self.host.run('echo +%d > /sys/class/rtc/rtc0/wakealarm' % timeout)
        self.host.run('powerd_dbus_suspend --delay=0 &')


    def suspend_action_resume(self, action):
        """suspends and resumes through powerd_dbus_suspend in thread.

        @param action: Action while suspended

        """

        # Suspend and wait to be suspended
        logging.info('--- SUSPENDING')
        thread = threading.Thread(target = self.powerd_suspend_with_timeout,
                                  args = (_LONG_TIMEOUT,))
        thread.start()
        self.wait_to_disconnect(_SUSPEND_FAILED)

        # Execute action after suspending
        do_while_suspended = re.findall(r'SUSPEND(\w*)RESUME', action)[0]
        logging.info('--- %s-ing', do_while_suspended)
        if do_while_suspended =='_UNPLUG_':
            self.set_hub_power(False)
        elif do_while_suspended =='_PLUG_':
            self.set_hub_power(True)

        # Press power key and resume ( and terminate thread)
        logging.info('--- RESUMING')
        self.host.servo.power_key(0.1)
        self.wait_to_come_up(_RESUME_FAILED, _LONG_TIMEOUT)
        if thread.is_alive():
            raise error.TestFail('SUSPEND thread did not terminate!')


    def crash_not_detected(self, crash_path):
        """Check for kernel, browser, process crashes

        @param crash_path: Crash files path

        @returns True if there were not crashes; False otherwise
        """
        result = True
        if str(self.host.run('ls %s' % crash_path,
                              ignore_status=True)).find('crash') != -1:
            crash_out = self.host.run('ls %s/crash/' % crash_path).stdout
            crash_files = crash_out.strip().split('\n')
            for crash_file in crash_files:
                if crash_file.find('.meta') != -1 and \
                    crash_file.find('kernel_warning') == -1:
                    self.add_failure('CRASH DETECTED in %s/crash: %s' %
                                     (crash_path, crash_file))
                    result = False
        return result


    def check_plugged_usb_devices(self):
        """Checks the plugged peripherals match device list.

        @returns True if expected USB peripherals are detected; False otherwise
        """
        result = True
        if self.pluged_status and self.usb_list != None:
            # Check for mandatory USb devices passed by usb_list flag
            for usb_name in self.usb_list:
                found = self.wait_for_cmd_output(
                    'lsusb', usb_name, _WAIT_DELAY * 4,
                    'Not detecting %s' % usb_name)
                result = result and found
        time.sleep(_WAIT_DELAY)
        on_now = self.getPluggedUsbDevices()
        if self.pluged_status:
            if not self.diff_list.issubset(on_now):
                missing = str(self.diff_list.difference(on_now))
                self.add_failure('Missing connected peripheral(s) '
                                 'when plugged: %s ' % missing)
                result = False
        else:
            present = self.diff_list.intersection(on_now)
            if len(present) > 0:
                self.add_failure('Still presented peripheral(s) '
                                 'when unplugged: %s ' % str(present))
                result = False
        return result


    def check_usb_peripherals_details(self):
        """Checks the effect from plugged in USB peripherals.

        @returns True if command line output is matched successfuly; Else False
        """
        usb_check_result = True
        for cmd in self.usb_checks.keys():
            out_match_list = self.usb_checks.get(cmd)
            if cmd.startswith('loggedin:'):
                if not self.login_status:
                    continue
                cmd = cmd.replace('loggedin:','')
            # Run the usb check command
            for out_match in out_match_list:
                match_result = self.wait_for_cmd_output(
                    cmd, out_match, _WAIT_DELAY * 4,
                    'USB CHECKS DETAILS failed at %s:' % cmd)
                usb_check_result = usb_check_result and match_result
        return usb_check_result


    def check_status(self):
        """Performs checks after each action:
            - for USB detected devices
            - for generated crash files
            - peripherals effect checks on cmd line

        @returns True if all of the iteration checks pass; False otherwise.
        """
        result = True
        if not self.suspend_status:
            # Detect the USB peripherals
            result = self.check_plugged_usb_devices()
            # Check for crash files
            if self.crash_check:
                for crash_path in _CRASH_PATHS:
                    result = result and self.crash_not_detected(crash_path)
            if self.pluged_status and (self.usb_checks != None):
                # Check for plugged USB devices details
                result = result and self.check_usb_peripherals_details()
        return result


    def change_suspend_resume(self, actions):
        """ Modifying actions to suspend and resume

        Changes suspend and resume actions done with lid_close
        to suspend_resume done with powerd_dbus_suspend

        @param actions: the sequence of accions to perform

        @returns The changed to suspend_resume action_sequence
        """
        susp_resumes = re.findall(r'(SUSPEND,\w*,*RESUME)',actions)
        for susp_resume in susp_resumes:
            replace_with = susp_resume.replace(',', '_')
            actions = actions.replace(susp_resume, replace_with, 1)
        return actions


    def crash_data_removed(self):
        """Delete crash meta files"""
        for crash_path in _CRASH_PATHS:
            if not self.crash_not_detected(crash_path):
                self.host.run('rm -rf %s/crash' % crash_path,
                              ignore_status=True)
                return True
        return False


    def add_failure(self, reason):
        """ Adds a failure reason to list of failures to be reported at end

        @param reason: failure reason to record

        """
        self.fail_reasons.append('%s FAILS - %s' %
                                 (self.action_step, reason))


    def run_once(self, host, client_autotest, action_sequence, repeat,
                 usb_list=None, usb_checks=None, crash_check=True):
        self.client_autotest = client_autotest
        self.host = host
        self.autotest_client = autotest.Autotest(self.host)
        self.usb_list = usb_list
        self.usb_checks = usb_checks
        self.crash_check = crash_check

        self.suspend_status = False
        self.login_status = False
        self.fail_reasons = list()
        self.action_step = None

        self.host.servo.switch_usbkey('dut')
        self.host.servo.set('usb_mux_sel3', 'dut_sees_usbkey')
        time.sleep(_WAIT_DELAY)

        # Collect USB peripherals when unplugged
        self.set_hub_power(False)
        time.sleep(_WAIT_DELAY)
        off_list = self.getPluggedUsbDevices()

        # Collect USB peripherals when plugged
        self.set_hub_power(True)
        time.sleep(_WAIT_DELAY * 2)
        on_list = self.getPluggedUsbDevices()

        self.diff_list = set(on_list).difference(set(off_list))
        if len(self.diff_list) == 0:
            # Fail if no devices detected after
            raise error.TestError('No connected devices were detected. Make '
                                  'sure the devices are connected to USB_KEY '
                                  'and DUT_HUB1_USB on the servo board.')
        logging.debug('Connected devices list: %s', self.diff_list)

        board = host.get_board().split(':')[1]
        action_sequence = action_sequence.upper()
        if board in _SUSPEND_RESUME_BOARDS:
            action_sequence = self.change_suspend_resume(action_sequence)
        actions = action_sequence.split(',')
        if self.crash_data_removed():
            self.fail_reasons = []

        for iteration in xrange(1, repeat + 1):
            step = 0
            for action in actions:
                step += 1
                action = action.strip()
                self.action_step = 'STEP %d.%d. %s' % (iteration, step, action)
                logging.info(self.action_step)

                if action == 'RESUME':
                    self.action_resume()
                elif action == 'UNPLUG':
                    self.set_hub_power(False)
                elif action == 'PLUG':
                    self.set_hub_power(True)
                elif self.suspend_status == False:
                    if action.startswith('LOGIN'):
                        if self.login_status:
                            logging.debug('Skipping login. Already logged in.')
                            continue
                        else:
                            self.action_login()
                            self.login_status = True
                    elif action == 'REBOOT':
                        self.host.reboot()
                        time.sleep(_WAIT_DELAY * 3)
                        self.login_status = False
                    elif action == 'SUSPEND':
                        self.action_suspend()
                    elif re.match(r'SUSPEND\w*RESUME',action) is not None:
                        self.suspend_action_resume(action)
                else:
                    logging.info('WRONG ACTION: %s .', self.action_step)

                self.check_status()

            if self.fail_reasons:
                raise error.TestFail('Failures reported: %s' %
                                     str(self.fail_reasons))
