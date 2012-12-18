# Copyright (c) 2012 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import netgear_WNDR_dual_band_configurator


class NetgearR6200APConfigurator(netgear_WNDR_dual_band_configurator.
                                NetgearDualBandAPConfigurator):
    """Derived class to control Netgear R6200 router."""


    def __init__(self, router_dict):
        super(NetgearR6200APConfigurator, self).__init__(router_dict)
        self.mode_173 = 'Up to 173 Mbps'
        self.mode_400 = 'Up to 400 Mbps'
        self.mode_867 = 'Up to 867 Mbps'
        self.security_wpa2psk = 'WPA2-PSK [AES]'


    def get_supported_modes(self):
        return [{'band': self.band_5ghz,
                 'modes': [self.mode_173, self.mode_400, self.mode_867]},
                {'band': self.band_2ghz,
                 'modes': [self.mode_54, self.mode_217, self.mode_450]}]


    def get_supported_bands(self):
        return [{'band': self.band_2ghz,
                 'channels': ['Auto', 1, 2, 3, 4, 5, 6, 7, 8, 9 , 10, 11]},
                {'band': self.band_5ghz,
                 'channels': [36, 40, 44, 48, 149, 153, 157, 161]}]


    def is_security_mode_supported(self, security_mode):
        return security_mode in (self.security_disabled,
                                 self.security_wpa2psk,
                                 self.security_wep)


    def _set_channel(self, channel):
        position = self._get_channel_popup_position(channel)
        channel_choices = ['Auto', '01', '02', '03', '04', '05', '06', '07',
                           '08', '09', '10', '11']
        xpath = '//select[@name="w_channel"]'
        if self.current_band == self.band_5ghz:
           xpath = '//select[@name="w_channel_an"]'
           channel_choices = ['36', '40', '44', '48', '149', '153',
                              '157', '161']
        self.select_item_from_popup_by_xpath(channel_choices[position],
                                             xpath)


    def set_security_wep(self, key_value, authentication):
        if self.current_band == self.band_5ghz:
            logging.info('Cannot set WEP \
                          security for 5GHz band in Netgear R6200 router.')
            return None
        super(NetgearR6200APConfigurator, self).set_security_wep(
        key_value, authentication)


    def set_security_wpapsk(self, shared_key, update_interval=1800):
        self.add_item_to_command_list(self._set_security_wpa2psk,
                                      (shared_key, update_interval), 1, 900)
