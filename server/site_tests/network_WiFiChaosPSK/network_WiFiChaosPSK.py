# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
import pprint
import subprocess

from autotest_lib.client.common_lib import error
from autotest_lib.server import autotest, test
from autotest_lib.server.cros.chaos_ap_configurators import ap_cartridge, \
    ap_configurator, ap_configurator_factory, download_chromium_prebuilt
from autotest_lib.server.cros.chaos_config import ChaosAP
from autotest_lib.server.cros.wlan import connector, disconnector

class network_WiFiChaosPSK(test.test):
    """Tests connecting to APs using PSK security setting."""

    version = 1


    def initialize(self, host, capturer=None):
        self.host = host
        self.client_at = autotest.Autotest(self.host)
        self.c = connector.TracingConnector(self.host, capturer)
        self.d = disconnector.Disconnector(self.host)
        self.generic_ap = ap_configurator.APConfigurator()
        self.factory = ap_configurator_factory.APConfiguratorFactory()
        self.psk_password = 'chromeos'
        self.error_list = []


    def get_line_count(self, logs, key):
        """
        Returns a logging dictionary updated with a line count.

        @param logs: the log dictionary to update
        @param key: the name of the key to add.

        @returns and updated dictionary with the key and line count.
        """
        for log in logs:
            command = "wc -l %s | awk '{print $1}'" % log['file']
            log[key] = int(self.host.run(command).stdout.strip())
        return logs


    def run_connect_disconnect_test(self, ap, iteration):
        """
        Connects and disconnects to the AP.

        @param ap: the ap object.
        @param iteration: the current iteration.

        @returns none if there are no errors; otherwise the error message.
        """
        error = None

        logs = ({'file': '/var/log/messages'}, {'file': '/var/log/net.log'})
        logs = self.get_line_count(logs, 'start')

        self.d.disconnect(ap['ssid'])
        self.c.set_frequency(ap['frequency'])
        log_folder = os.path.join(self.outputdir, '%s' % ap['bss'])
        if not os.path.exists(log_folder):
            os.mkdir(log_folder)
        self.c.set_filename(os.path.join(log_folder, 'connect_try_%d'
                                         % (iteration+1)))
        error = None
        try:
            self.c.connect(ap['ssid'], security=ap['security'],
                           psk=ap['psk'], frequency=ap['frequency'])
        except (connector.ConnectException,
                connector.ConnectFailed,
                connector.ConnectTimeout) as e:
            error = str(e)
            logging.info('Connection failed, error: %s', error)
        finally:
            self.d.disconnect(ap['ssid'])

        logs = self.get_line_count(logs, 'end')
        for log in logs:
            line_count = log['end'] - log['start']
            output = self.host.run('tail -n %d %s' %
                                   (line_count, log['file'])).stdout
            file_path = os.path.join(log_folder, os.path.basename(log['file']))
            file_path += '_%d' % (iteration+1)
            f = open(file_path, 'w')
            f.write(output)
            f.close()

        return error


    def loop_ap_configs_and_test(self, all_aps, tries):
        """
        Configures AP to psk security for one channel on each supported band.

        @param all_aps: list of APs to test.
        @param tries: number of times to connect/disconnect.
        """
        bands_and_channels = self.factory.get_supported_bands_and_channels(
                             ap_list=all_aps)

        bands = [self.generic_ap.band_2ghz, self.generic_ap.band_5ghz]
        channels = [5, 48]
        cartridge = ap_cartridge.APCartridge()
        for band, channel in zip(bands, channels):
            logging.info('Testing band %s and channel %s', band, channel)
            configured_aps = []
            for ap in all_aps:
                if ap.is_band_and_channel_supported(band, channel):
                    for mode in  ap.get_supported_modes():
                        if mode['band'] == band:
                            for mode_type in mode['modes']:
                                if (mode_type & self.generic_ap.mode_n !=
                                    self.generic_ap.mode_n):
                                    break
                    # Setting the band gets you the bss
                    ap.set_band(band)
                    ap_info = {
                        'bss': ap.get_bss(),
                        'band': band,
                        'channel': channel,
                        'frequency': ChaosAP.FREQUENCY_TABLE[channel],
                        'radio': True,
                        'ssid': '_'.join([ap.get_router_short_name(),
                                          str(channel),
                                          str(band).replace('.', '_')]),
                        'visibility': True,
                        'security': 'psk',
                        'psk': self.psk_password,
                        'brand': ap.config_data.get_brand(),
                        'model': ap.get_router_short_name(),
                    }

                    logging.info('Using ssid %s', ap_info['ssid'])
                    ap.power_up_router()
                    ap.set_channel(ap_info['channel'])
                    ap.set_radio(enabled=ap_info['radio'])
                    ap.set_ssid(ap_info['ssid'])
                    ap.set_visibility(visible=ap_info['visibility'])
                    ap.set_mode(mode_type)
                    ap.set_security_wpapsk(self.psk_password)
                    configured_aps.append(ap_info)
                    cartridge.push_configurator(ap)
            cartridge.run_configurators()

            for ap in configured_aps:
                logging.info('Client connecting to ssid %s (bss: %s)',
                             ap['ssid'], ap['bss'])
                ap['failed_iterations'] = []
                failure = False
                for iteration in range(tries):
                    logging.info('Connection try %d', (iteration + 1))
                    resp = self.run_connect_disconnect_test(ap, iteration)
                    if resp:
                        failure = True
                        error_dict = {'error': resp, 'try': (iteration + 1)}
                        ap['failed_iterations'].append(error_dict)
                if failure:
                    self.error_list.append(ap)


    def power_down(self, aps):
        """
        Power down APs

        @param aps: list of aps to power down
        """
        cartridge = ap_cartridge.APCartridge()
        for ap in aps:
            ap.power_down_router()
            cartridge.push_configurator(ap)
        cartridge.run_configurators()


    def run_once(self, tries=1):
        """
        Main entry function for autotest.

        @param tries: number of connection attempts.
        """
        if download_chromium_prebuilt.download_chromium_prebuilt_binaries():
            raise error.TestError('The binaries were just downloaded.  Please '
                                  'run: (outside-chroot) <path to chroot tmp '
                                  'directory>/ %s./ chromedriver'
                                  % download_chromium_prebuilt.DOWNLOAD_PATH)
        # Install all of the autotest libriaries on the client
        self.client_at.install()

        # Check the times on the server and DUT
        date = subprocess.Popen(['date'],
                                stdout=subprocess.PIPE).communicate()[0]
        logging.info('Server time: %s', date.strip())
        logging.info('DUT time: %s', self.host.run('date').stdout.strip())
        all_aps = self.factory.get_aps_with_security_mode(
                  self.generic_ap.security_type_wpapsk)
        self.power_down(all_aps)
        self.loop_ap_configs_and_test(all_aps, tries)
        logging.info('Client test complete, powering down router')
        self.power_down(all_aps)


        # Test failed if any of the intermediate tests failed.
        if self.error_list:
            msg = 'Failed with the following AP\'s:\n'
            msg += pprint.pformat(self.error_list)
            raise error.TestFail(msg)
