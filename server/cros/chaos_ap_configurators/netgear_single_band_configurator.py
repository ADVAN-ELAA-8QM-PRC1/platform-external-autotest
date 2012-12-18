# Copyright (c) 2012 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
import urlparse
import ap_configurator

from selenium.common.exceptions import TimeoutException as \
    SeleniumTimeoutException
from selenium.common.exceptions import WebDriverException

class NetgearSingleBandAPConfigurator(ap_configurator.APConfigurator):
    """Derived class to control Netgear single band routers."""

    security_disabled = 'Disabled'
    security_wep = 'WEP'
    security_wpapsk = 'WPA-PSK[TKIP]'
    security_wpa2psk = 'WPA2-PSK[AES]'
    security_wpa8021x = 'WPA-PSK[TKIP]+WPA2-PSK[AES]'


    def get_number_of_pages(self):
        return 1


    def get_supported_bands(self):
        return [{'band': self.band_2ghz,
                 'channels': ['Auto', 1, 2, 3, 4, 5, 6, 7, 8, 9 , 10, 11]}]


    def get_supported_modes(self):
        return [{'band': self.band_2ghz,
                 'modes': ['g only', 'b and g']}]


    def is_security_mode_supported(self, security_mode):
        return security_mode in (self.security_disabled,
                                 self.security_wpapsk,
                                 self.security_wep)


    def navigate_to_page(self, page_number):
        self.driver.get(urlparse.urljoin(self.admin_interface_url,
                        'WLG_wireless.htm'))
        try:
            self.wait_for_object_by_xpath('//input[@name="ssid"]')
        except SeleniumTimeoutException, e:
            raise SeleniumTimeoutException('Unable to navigate to settings '
                                           'page. WebDriver exception:%s', e)


    def save_page(self, page_number):
        self.click_button_by_xpath('//input[@name="Apply"]')


    def set_radio(self, enabled=True):
        logging.info('set_radio is not supported in netgear614 router.')
        return None


    def set_ssid(self, ssid):
        self.add_item_to_command_list(self._set_ssid, (ssid,), 1, 900)


    def _set_ssid(self, ssid):
        xpath = '//input[@maxlength="32" and @name="ssid"]'
        self.set_content_of_text_field_by_xpath(ssid, xpath, abort_check=True)


    def set_channel(self, channel):
        self.add_item_to_command_list(self._set_channel, (channel,), 1, 900)


    def _set_channel(self, channel):
        position = self._get_channel_popup_position(channel)
        channel_choices = ['Auto', '01', '02', '03', '04', '05', '06',
                           '07', '08', '09', '10', '11']
        xpath = '//select[@name="w_channel"]'
        self.select_item_from_popup_by_xpath(channel_choices[position], xpath)


    def set_mode(self, mode):
        self.add_item_to_command_list(self._set_mode, (mode,), 1, 900)


    def _set_mode(self, mode):
        xpath = '//select[@name="opmode"]'
        self.select_item_from_popup_by_xpath(mode, xpath)


    def set_band(self, band):
        logging.info('set_band is not supported in netgear614 router.')
        return None


    def set_security_disabled(self):
        self.add_item_to_command_list(self._set_security_disabled, (), 1, 900)


    def _set_security_disabled(self):
        xpath = '//input[@name="security_type" and @value="Disable"]'
        self.click_button_by_xpath(xpath)


    def set_security_wep(self, value, authentication):
        self.add_item_to_command_list(self._set_security_wep,
                                     (value, authentication), 1, 900)


    def _set_security_wep(self, value, authentication):
        xpath = '//input[@name="security_type" and @value="WEP"]'
        self.click_button_by_xpath(xpath)
        xpath = '//input[@name="passphraseStr"]'
        self.set_content_of_text_field_by_xpath(value, xpath, abort_check=True)
        xpath = '//input[@value="Generate"]'
        self.click_button_by_xpath(xpath)


    def set_security_wpapsk(self, key):
        self.add_item_to_command_list(self._set_security_wpapsk, (key,), 1, 900)


    def _set_security_wpapsk(self, key):
        xpath = '//input[@name="security_type" and @value="WPA-PSK"]'
        self.click_button_by_xpath(xpath)
        xpath = '//input[@name="passphrase"]'
        self.set_content_of_text_field_by_xpath(key, xpath, abort_check=True)


    def set_visibility(self, visible=True):
        logging.info('set_visibility is not supported in netgear614 router.')
        return None
