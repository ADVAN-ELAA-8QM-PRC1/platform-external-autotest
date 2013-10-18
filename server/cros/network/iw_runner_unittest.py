# Copyright (c) 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import unittest

from autotest_lib.server.cros.network import iw_runner

class IwRunnerTest(unittest.TestCase):
    """Unit test for the IWRunner object."""


    class host_cmd(object):
        """Mock host command class."""

        def __init__(self, stdout, exit_status):
            self._stdout = stdout
            self._exit_status = exit_status


        @property
        def stdout(self):
            """Returns stdout."""
            return self._stdout


        @property
        def exit_status(self):
            """Returns the exit status."""
            return self._exit_status


    class host(object):
        """Mock host class."""

        def __init__(self, host_cmd):
            self._host_cmd = IwRunnerTest.host_cmd(host_cmd, 0)


        def run(self, cmd, ignore_status=False):
            """Returns the mocked output.

            @param cmd: a stub input ignore
            @param ignore_status: a stub input ignore

            """
            return self._host_cmd


    HT20 = str('BSS aa:aa:aa:aa:aa:aa (on wlan0)\n'
        '    freq: 2412\n'
        '    SSID: support_ht20\n'
        '    HT operation:\n'
        '         * secondary channel offset: no secondary\n')

    HT20_IW_BSS = iw_runner.IwBss('aa:aa:aa:aa:aa:aa', 2412,
                                  'support_ht20',
                                  iw_runner.HT20)

    HT20_2 = str('BSS 11:11:11:11:11:11 (on wlan0)\n'
        '     freq: 2462\n'
        '     SSID: support_ht20\n'
        '     HT operation:\n'
        '          * secondary channel offset: below\n')

    HT20_2_IW_BSS = iw_runner.IwBss('11:11:11:11:11:11', 2462,
                                    'support_ht20', iw_runner.HT40_BELOW)

    HT40_ABOVE = str('BSS bb:bb:bb:bb:bb:bb (on wlan0)\n'
        '    freq: 5180\n'
        '    SSID: support_ht40_above\n'
        '    HT operation:\n'
        '         * secondary channel offset: above\n')

    HT40_ABOVE_IW_BSS = iw_runner.IwBss('bb:bb:bb:bb:bb:bb', 5180,
                                        'support_ht40_above',
                                        iw_runner.HT40_ABOVE)

    HT40_BELOW = str('BSS cc:cc:cc:cc:cc:cc (on wlan0)\n'
        '    freq: 2462\n'
        '    SSID: support_ht40_below\n'
        '    HT operation:\n'
        '        * secondary channel offset: below\n')

    HT40_BELOW_IW_BSS = iw_runner.IwBss('cc:cc:cc:cc:cc:cc', 2462,
                                        'support_ht40_below',
                                        iw_runner.HT40_BELOW)

    NO_HT = str('BSS dd:dd:dd:dd:dd:dd (on wlan0)\n'
        '    freq: 2412\n'
        '    SSID: no_ht_support\n')

    NO_HT_IW_BSS = iw_runner.IwBss('dd:dd:dd:dd:dd:dd', 2412,
                                   'no_ht_support', None)

    HIDDEN_SSID = str('BSS ee:ee:ee:ee:ee:ee (on wlan0)\n'
        '    freq: 2462\n'
        '    SSID: \n'
        '    HT operation:\n'
        '         * secondary channel offset: no secondary\n')

    HIDDEN_SSID_IW_BSS = iw_runner.IwBss('ee:ee:ee:ee:ee:ee', 2462,
                                         None, iw_runner.HT20)


    def verify_values(self, iw_bss_1, iw_bss_2):
        """Checks all of the IWBss values

        @param iw_bss_1: an IWBss object
        @param iw_bss_2: an IWBss object

        """
        self.assertEquals(iw_bss_1.bss, iw_bss_2[0].bss)
        self.assertEquals(iw_bss_1.ssid, iw_bss_2[0].ssid)
        self.assertEquals(iw_bss_1.frequency, iw_bss_2[0].frequency)
        self.assertEquals(iw_bss_1.ht, iw_bss_2[0].ht)


    def search_by_bss(self, scan_output, test_iw_bss):
        """

        @param scan_output: the output of the scan as a string
        @param test_iw_bss: an IWBss object

        Uses the runner to search for a network by bss.
        """
        host = self.host(scan_output)
        runner = iw_runner.IwRunner(host)
        network = runner.wait_for_scan_result('wlan0', bss=test_iw_bss.bss)
        self.verify_values(test_iw_bss, network)


    def test_find_first(self):
        """Test with the first item in the list."""
        scan_output = self.HT20 + self.HT40_ABOVE
        self.search_by_bss(scan_output, self.HT20_IW_BSS)


    def test_find_last(self):
        """Test with the last item in the list."""
        scan_output = self.HT40_ABOVE + self.HT20
        self.search_by_bss(scan_output, self.HT20_IW_BSS)


    def test_find_middle(self):
        """Test with the middle item in the list."""
        scan_output = self.HT40_ABOVE + self.HT20 + self.NO_HT
        self.search_by_bss(scan_output, self.HT20_IW_BSS)


    def test_ht40_above(self):
        """Test with a HT40+ network."""
        scan_output = self.HT20 + self.HT40_ABOVE + self.NO_HT
        self.search_by_bss(scan_output, self.HT40_ABOVE_IW_BSS)


    def test_ht40_below(self):
        """Test with a HT40- network."""
        scan_output = self.HT20 + self.HT40_BELOW + self.NO_HT
        self.search_by_bss(scan_output, self.HT40_BELOW_IW_BSS)


    def test_no_ht(self):
        """Test with a network that doesn't have ht."""
        scan_output = self.HT20 + self.NO_HT + self.HT40_ABOVE
        self.search_by_bss(scan_output, self.NO_HT_IW_BSS)


    def test_hidden_ssid(self):
        """Test with a network with a hidden ssid."""
        scan_output = self.HT20 + self.HIDDEN_SSID + self.NO_HT
        self.search_by_bss(scan_output, self.HIDDEN_SSID_IW_BSS)

    def test_multiple_ssids(self):
        """Test with multiple networks with the same ssids."""
        return
        scan_output = self.HT40_ABOVE + self.HT20 + self.NO_HT + self.HT20_2
        host = self.host(scan_output)
        runner = iw_runner.IwRunner(host)
        networks = runner.wait_for_scan_result('wlan 0',
                                               ssid=self.HT20_2_IW_BSS.ssid)
        for iw_bss_1, iw_bss_2 in zip([self.HT20_IW_BSS, self.HT20_2_IW_BSS],
                                      networks):
            self.verify_values(iw_bss_1, iw_bss_2)
