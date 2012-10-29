# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging, os, shutil, time
from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros import backchannel, cros_ui, cros_ui_test
from autotest_lib.client.cros import httpd, login, power_status
from autotest_lib.client.cros import flimflam_test_path
import flimflam

params_dict = {
    'test_time_ms': '_mseconds',
    'should_scroll': '_should_scroll',
    'should_scroll_up': '_should_scroll_up',
    'scroll_loop': '_scroll_loop',
    'scroll_interval_ms': '_scroll_interval_ms',
    'scroll_by_pixels': '_scroll_by_pixels',
    'tasks': '_tasks',
}


class power_LoadTest(cros_ui_test.UITest):
    version = 2


    def start_authserver(self):
        """
        Override cros_ui_test.UITest's start_authserver.
        Do not use auth server and local dns for our test. We need to be
        able to reach the web.
        """
        pass


    def ensure_login_complete(self):
        """
        Override cros_ui_test.UITest's ensure_login_complete.
        Do not use auth server and local dns for our test. We need to be
        able to reach the web.
        """
        pass


    def initialize(self, creds='$default', percent_initial_charge_min=None,
                 check_network=True, loop_time=3600, loop_count=1,
                 should_scroll='true', should_scroll_up='true',
                 scroll_loop='false', scroll_interval_ms='10000',
                 scroll_by_pixels='600', low_battery_threshold=3,
                 verbose=True, force_wifi=False, wifi_ap='', wifi_sec='none',
                 wifi_pw='', tasks=""):

        """
        percent_initial_charge_min: min battery charge at start of test
        check_network: check that Ethernet interface is not running
        loop_count: number of times to loop the test for
        loop_time: length of time to run the test for in each loop
        should_scroll: should the extension scroll pages
        should_scroll_up: should scroll in up direction
        scroll_loop: continue scrolling indefinitely
        scroll_interval_ms: how often to scoll
        scroll_by_pixels: number of pixels to scroll each time
        """
        self._loop_time = loop_time
        self._loop_count = loop_count
        self._mseconds = self._loop_time * 1000
        self._verbose = verbose
        self._low_battery_threshold = low_battery_threshold
        self._should_scroll = should_scroll
        self._should_scroll_up = should_scroll_up
        self._scroll_loop = scroll_loop
        self._scroll_interval_ms = scroll_interval_ms
        self._scroll_by_pixels = scroll_by_pixels
        self._tmp_keyvals = {}
        self._power_status = power_status.get_status()
        self._force_wifi = force_wifi
        self._testServer = None
        self._tasks = '\'' + tasks.replace(' ','') + '\''
        self._backchannel = None

        self._power_status.assert_battery_state(percent_initial_charge_min)
        # If force wifi enabled, convert eth0 to backchannel and connect to the
        # specified WiFi AP.
        if self._force_wifi:
            # If backchannel is already running, don't run it again.
            self._backchannel = backchannel.Backchannel()
            if not self._backchannel.setup():
                raise error.TestError('Could not setup Backchannel network.')

            if not flimflam.FlimFlam().ConnectService(retries=3,
                                                      retry=True,
                                                      service_type='wifi',
                                                      ssid=wifi_ap,
                                                      security=wifi_sec,
                                                      passphrase=wifi_pw,
                                                      mode='managed')[0]:
                raise error.TestError('Could not connect to WiFi network.')
        else:
            # Find all wired ethernet interfaces.
            # TODO: combine this with code in network_DisableInterface, in a
            # common library somewhere.
            ifaces = [ nic.strip() for nic in os.listdir('/sys/class/net/')
                if ((not os.path.exists('/sys/class/net/' + nic + '/phy80211'))
                    and nic.find('eth') != -1) ]
            logging.debug(str(ifaces))
            for iface in ifaces:
              if check_network and backchannel.is_network_iface_running(iface):
                  raise error.TestError('Ethernet interface is active. ' + \
                                                'Please remove Ethernet cable')

        # record the max backlight level
        cmd = 'backlight-tool --get_max_brightness'
        self._max_backlight = int(utils.system_output(cmd).rstrip())
        self._tmp_keyvals['level_backlight_max'] = self._max_backlight

        # fix up file perms for the power test extension so that chrome
        # can access it
        os.system('chmod -R 755 %s' % self.bindir)

        # write test parameters to the params.js file to be read by the test
        # extension.
        self._write_ext_params()

        # setup a HTTP Server to listen for status updates from the power
        # test extension
        self._testServer = httpd.HTTPListener(8001, docroot=self.bindir)
        self._testServer.run()

        # initialize various interesting power related stats
        self._usb_stats = power_status.USBSuspendStats()
        self._cpufreq_stats = power_status.CPUFreqStats()
        self._cpuidle_stats = power_status.CPUIdleStats()
        self._disk_logger = power_status.DiskStateLogger()
        if os.path.exists('/dev/sda'):
            self._disk_logger.start()

        self._power_status.refresh()

        self._ah_charge_start = self._power_status.battery[0].charge_now
        self._wh_energy_start = self._power_status.battery[0].energy

        # from cros_ui_test.UITest.initialize, sans authserver & local dns.
        cros_ui_test.UITest.initialize(self, creds)

    def run_once(self):

        t0 = time.time()
        ext_path = os.path.join(os.path.dirname(__file__), 'extension.crx')

        for i in range(self._loop_count):
            # the power test extension will report its status here
            latch = self._testServer.add_wait_url('/status')

            # Installing the extension will also fire it up.
            ext_id = self.pyauto.InstallExtension(ext_path)

            # stop powerd
            os.system('stop powerd')

            # reset X settings since X gets restarted upon login
            self._do_xset()

            # reset backlight level since powerd might've modified it
            # based on ambient light
            self._set_backlight_level()

            low_battery = self._do_wait(self._verbose, self._loop_time,
                                        latch)

            if self._verbose:
                logging.debug('loop %d completed' % i)

            if low_battery:
                logging.info('Exiting due to low battery')
                break

            if not self.pyauto.GetBrowserWindowCount():
                self.pyauto.OpenNewBrowserWindow(True)
            self.pyauto.UninstallExtensionById(ext_id)

        t1 = time.time()
        self._tmp_keyvals['minutes_battery_life'] = (t1 - t0) / 60


    def postprocess_iteration(self):
        def _format_stats(keyvals, stats, name):
            for state in stats:
                keyvals['percent_%s_%s_time' % (name, state)] = stats[state]

        keyvals = {}

        _format_stats(keyvals, self._usb_stats.refresh(), 'usb')
        _format_stats(keyvals, self._cpufreq_stats.refresh(), 'cpufreq')
        _format_stats(keyvals, self._cpuidle_stats.refresh(), 'cpuidle')
        if (self._disk_logger.get_error()):
            keyvals['disk_logging_error'] = str(self._disk_logger.get_error())
        else:
            _format_stats(keyvals, self._disk_logger.result(), 'disk')

        # record battery stats
        keyvals['a_current_now'] = self._power_status.battery[0].current_now
        keyvals['ah_charge_full'] = self._power_status.battery[0].charge_full
        keyvals['ah_charge_full_design'] = \
                             self._power_status.battery[0].charge_full_design
        keyvals['ah_charge_start'] = self._ah_charge_start
        keyvals['ah_charge_now'] = self._power_status.battery[0].charge_now
        keyvals['ah_charge_used'] = keyvals['ah_charge_start'] - \
                                    keyvals['ah_charge_now']
        keyvals['wh_energy_start'] = self._wh_energy_start
        keyvals['wh_energy_now'] = self._power_status.battery[0].energy
        keyvals['wh_energy_used'] = keyvals['wh_energy_start'] - \
                                    keyvals['wh_energy_now']
        keyvals['v_voltage_min_design'] = \
                             self._power_status.battery[0].voltage_min_design
        keyvals['v_voltage_now'] = self._power_status.battery[0].voltage_now

        keyvals.update(self._tmp_keyvals)

        keyvals['a_current_rate'] = keyvals['ah_charge_used'] * 60 / \
                                    keyvals['minutes_battery_life']
        keyvals['w_energy_rate'] = keyvals['wh_energy_used'] * 60 / \
                                   keyvals['minutes_battery_life']
        keyvals['mc_min_temp'] = self._power_status.min_temp
        keyvals['mc_max_temp'] = self._power_status.max_temp

        self.write_perf_keyval(keyvals)


    def cleanup(self):
        # re-enable powerd
        os.system('start powerd')
        # cleanup backchannel interface
        if self._backchannel:
            self._backchannel.teardown()
        if self._testServer:
            self._testServer.stop()
        super(power_LoadTest, self).cleanup()


    def _write_ext_params(self):
        data = ''
        template= 'var %s = %s;\n'
        for k in params_dict:
            data += template % (k, getattr(self, params_dict[k]))

        filename = os.path.join(self.bindir, 'params.js')
        utils.open_write_close(filename, data)

        logging.debug('filename ' + filename)
        logging.debug(data)


    def _do_wait(self, verbose, seconds, latch):
        latched = False
        low_battery = False
        total_time = seconds + 60
        elapsed_time = 0
        wait_time = 60

        while elapsed_time < total_time:
            time.sleep(wait_time)
            elapsed_time += wait_time

            self._power_status.refresh()
            if verbose:
                logging.debug('ah_charge_now %f' \
                    % self._power_status.battery[0].charge_now)
                logging.debug('w_energy_rate %f' \
                    % self._power_status.battery[0].energy_rate)
                logging.debug('v_voltage_now %f' \
                    % self._power_status.battery[0].voltage_now)

            low_battery = (self._power_status.percent_current_charge() <
                           self._low_battery_threshold)

            latched = latch.is_set()

            if latched or low_battery:
                break

        if latched:
            # record chrome power extension stats
            form_data = self._testServer.get_form_entries()
            logging.debug(form_data)
            for e in form_data:
                key = 'ext_' + e
                if key in self._tmp_keyvals:
                    self._tmp_keyvals[key] += form_data[e]
                else:
                    self._tmp_keyvals[key] = form_data[e]
        else:
            logging.debug("Didn't get status back from power extension")

        return low_battery


    def _do_xset(self):
        XSET = 'LD_LIBRARY_PATH=/usr/local/lib xset'
        # Disable X screen saver
        cros_ui.xsystem('%s s 0 0' % XSET)
        # Disable DPMS Standby/Suspend/Off
        cros_ui.xsystem('%s dpms 0 0 0' % XSET)
        # Force monitor on
        cros_ui.xsystem('%s dpms force on' % XSET)
        # Save off X settings
        cros_ui.xsystem('%s q' % XSET)


    def _set_backlight_level(self):
        # set backlight level to 40% of max
        cmd = 'backlight-tool --set_brightness %d ' % (
              int(self._max_backlight * 0.4))
        os.system(cmd)

        # record brightness level
        cmd = 'backlight-tool --get_brightness'
        level = int(utils.system_output(cmd).rstrip())
        logging.info('backlight level is %d' % level)
        self._tmp_keyvals['level_backlight_current'] = level
