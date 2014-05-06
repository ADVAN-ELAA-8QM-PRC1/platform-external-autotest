# Copyright (c) 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse
import csv
import logging
import os
import re
import shutil

CONNECT_FAIL = object()
CONFIG_FAIL = object()
RESULTS_DIR = '/tmp/chaos'


class ChaosParser(object):
    """Defines a parser for chaos test results"""

    def __init__(self, results_dir):
        """ Constructs a parser interface.

        @param results_dir: The results directory from a chaos test.

        """
        self.test_results_dir = results_dir
        self.tests = list()
        self.status_log = list()
        self.keyval = None


    def create_csv(self, filename, data):
        """Creates a file in .csv format.

        @param filename: Name for the csv file
        @param data: All the information to write to the file

        """
        if not os.path.exists(RESULTS_DIR):
            os.mkdir(RESULTS_DIR)
        try:
            path = os.path.join(RESULTS_DIR, filename + '.csv')
            with open(path, 'wb') as f:
                writer = csv.writer(f)
                writer.writerows(data)
                logging.info('Created CSV files for chaos failures in %s',
                              RESULTS_DIR)
        except IOError as e:
            logging.error('File operation failed with %s: %s', e.errno,
                           e.strerror)
            return


    def get_ap_name(self, line):
        """Gets the router name from the string passed.

        @param line: Test ERROR string from chaos status.log

        @return Returns the router name, brand.

        """
        router_info = re.search('Router name: ([\w\s]+)', line)
        return router_info.group(1)


    def get_ap_mode_chan_freq(self, ssid):
        """Gets the AP frequency from ssid using channel.

        @param ssid: A valid chaos test SSID

        @return Returns the AP frequency.

        """
        channel_security_info = ssid.split('_')
        channel_info = channel_security_info[-2]
        mode = channel_security_info[-3]
        channel = int(re.split('(\d+)', channel_info)[1])
        if channel in range(1, 15):
            frequency = '2.4GHz'
        else:
            frequency = '5GHz'
        return {'mode': mode.upper(), 'channel': channel,
                'frequency': frequency}


    def get_ap_security(self, ssid):
        """Gets the AP security from ssid.

        @param ssid: A valid chaos test SSID

        @return Returns the AP's security.

        """
        channel_security_info = ssid.split('_')
        security = channel_security_info[-1].upper()
        return security


    def parse_keyval(self):
        """Parses the 'keyvalue' file to get device details.

        @return Returns a dict with device name and OS version.

        """
        f = open(self.keyval, 'r')
        for line in f:
            line = line.split('=')
            if 'RELEASE_BOARD' in line[0]:
                lsb_dict = {'board':line[1].rstrip()}
            elif 'RELEASE_VERSION' in line[0]:
                lsb_dict['version'] = line[1].rstrip()
            else:
                continue
        return lsb_dict


    def insert_into_tuple(self, item, value):
        """Insert the value(pass percentage) information to the AP fail tuple.

        @param item: The old tuple consisting of (board, version, mode, channel,
                     security, AP)
        @param value: The value to be inserted into the tuple

        @return Returns a new tuple with percentage (board, version, mode,
                channel, security, percentage, AP).

        """
        item = list(item)
        item.insert(-1, value)
        return tuple(item)


    def get_pass_percentage(self, total_tests, config_fail, connect_fail):
        """Calculate the actual pass percentages.

        @total_tests: Total number of tests run
        @config_fail: Total number of configuration failures
        @connect_fail: Total number of connection failures

        @return: Returns a dict with pass percentages for configuration and
                 connection failures.

        """
        config_pass = total_tests - config_fail
        connect_pass = config_pass - connect_fail
        config_pass_percent = float(config_pass)/float(total_tests) * 100
        config_pass_percent = str(int(round(config_pass_percent))) + '%'
        connect_pass_percent = float(connect_pass)/float(config_pass) * 100
        connect_pass_percent = str(int(round(connect_pass_percent))) + '%'
        return {'config_pass_percent': config_pass_percent,
                'connect_pass_percent':connect_pass_percent}


    def parse_status_log(self):
        """Parses the entire status.log file from chaos test for test failures.
           and creates two CSV files for connect fail and configuration fail
           respectively.

        """
        for test_type, status_log in zip(self.tests, self.status_log):
            connect_fail_list = list()
            config_fail_list = list()
            f = open(status_log, 'r')
            total = 0
            for line in f:
                line = line.strip()
                if line.startswith('START\tnetwork_WiFi'):
                   # TODO: @bmahadev, Add exception for PDU failure and do not
                   # include that in the total tests.
                   total += 1
                elif 'END ERROR' in line or 'END FAIL' in line:
                    if failure_type == CONNECT_FAIL:
                        lsb_dict = self.parse_keyval()
                        connect_fail_list.append((lsb_dict['board'],
                                               lsb_dict['version'],
                                               mode_chan_freq_dict['mode'],
                                               mode_chan_freq_dict['channel'],
                                               mode_chan_freq_dict['frequency'],
                                               security, name))
                    else:
                        config_fail_list.append((security, hostname))
                    failure_type = None
                elif line.startswith('ERROR') or line.startswith('FAIL'):
                    if 'Router name' in line:
                        name = self.get_ap_name(line)
                    title_info = line.split()
                    ssid_or_host_info = title_info[1]
                    # Get the hostname for the AP that failed configuration.
                    if 'chromeos' in ssid_or_host_info:
                        failure_type = CONFIG_FAIL
                        host_info = title_info[1].split('.')
                        hostname = host_info[1].split('_')[0]
                    else:
                        # Get the router name, frequency for the AP that failed
                        # connect.
                        ssid_info = title_info[1].split('.')
                        ssid = ssid_info[1]
                        if 'ch' not in ssid:
                            ssid = ssid_info[2]
                        security = self.get_ap_security(ssid)
                        mode_chan_freq_dict = self.get_ap_mode_chan_freq(ssid)
                        # Security mismatches and Ping failures are not connect
                        # failures.
                        if 'Ping command' in line or 'correct security' in line:
                            failure_type = CONFIG_FAIL
                            hostname = ssid
                        else:
                            failure_type = CONNECT_FAIL
                elif line.startswith('Debug info'):
                    name = self.get_ap_name(line)
                else:
                    continue
            percent_dict = self.get_pass_percentage(total,
                                                    len(config_fail_list),
                                                    len(connect_fail_list))
            if not config_fail_list:
                config_fail_list.append((security, 'NONE'))
            if not connect_fail_list:
                connect_fail_list.append((lsb_dict['board'],
                                          lsb_dict['version'],
                                          mode_chan_freq_dict['mode'],
                                          mode_chan_freq_dict['channel'],
                                          mode_chan_freq_dict['frequency'],
                                          security, 'NONE'))
            connect_fail_csv_data = list()
            config_fail_csv_data = list()

            for item1 in connect_fail_list:
                item1 = self.insert_into_tuple(item1,
                                           percent_dict['connect_pass_percent'])
                connect_fail_csv_data.append(item1)
            for item2 in config_fail_list:
                item2 = self.insert_into_tuple(item2,
                                           percent_dict['config_pass_percent'])
                config_fail_csv_data.append(item2)
            self.create_csv('chaos_WiFi_connect_fail' + '.' + test_type, sorted(
                             connect_fail_csv_data))
            self.create_csv('chaos_WiFi_config_fail' + '.' + test_type, sorted(
                             config_fail_csv_data))


    def traverse_results_dir(self, path):
        """Walks through the results directory and get the pathnames for the
           status.log and the keyval files.

        @param path: Path for a specific test result directory.

        @return Returns a dict with absolute pathnames for the 'status.log' and
                'keyfile' files.

        """
        status = None
        keyval = None

        for root, dir_name, file_name in os.walk(path):
            for name in file_name:
                if name == 'status.log':
                    path = os.path.join(root, name)
                    if not status:
                       status = path
                elif name == 'keyval' and 'CHROMEOS_BUILD' in open(os.path.join(
                                                            root, name)).read():
                    path = os.path.join(root, name)
                    keyval = path
                    break
                else:
                    continue
        return {'status_file': status, 'keyval_file': keyval}


    def parse_results_dir(self):
        """For each results directory created by test_that, parse it and
           create summary files.

        """
        for results_dir in os.listdir(self.test_results_dir):
            if 'results' in results_dir:
                path = os.path.join(self.test_results_dir, results_dir)
                test_info = results_dir.split('.')
                self.tests.append(test_info[1])
                status_key_dict = self.traverse_results_dir(path)
                self.status_log.append(status_key_dict['status_file'])
                self.keyval = status_key_dict['keyval_file']
        if not self.tests:
            raise RuntimeError('chaos_parse: Did not find any results directory'
                               'to process')
        if os.path.exists(RESULTS_DIR):
            shutil.rmtree(RESULTS_DIR)
        self.parse_status_log()


def main():
    """Main function to call the parser."""
    logging.basicConfig(level=logging.INFO)
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('-d', '--directory', dest='dir_name',
                            help='Pathname to results generated by test_that')
    arguments = arg_parser.parse_args()
    if not arguments.dir_name:
        raise RuntimeError('chaos_parser: No directory name supplied. Use -h'
                           ' for help')
    if not os.path.exists(arguments.dir_name):
        raise RuntimeError('chaos_parser: Invalid directory name supplied.')
    parser = ChaosParser(arguments.dir_name)
    parser.parse_results_dir()


if __name__ == '__main__':
    main()
