# Copyright (c) 2012 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
import urlparse

import ap_configurator
import selenium.common.exceptions


class LinksysAPConfigurator(ap_configurator.APConfigurator):

    def __init__(self, router_dict):
        super(LinksysAPConfigurator, self).__init__(router_dict)
        # Overrides
        self.security_disabled = 'Disabled'
        self.security_wep = 'WEP'
        self.security_wpapsk = 'WPA Personal'
        self.security_wpa2psk = 'WPA2 Personal'
        self.security_wpa8021x = 'WPA Enterprise'
        self.security_wpa28021x = 'WPA2 Enterprise'
        self.security_wpapskmixed = 'WPA2/WPA Mixed Mode'
        self.security_wpa8021xmixed = 'WPA2/WPA Enterprise Mixed Mode'
        self.current_band = self.band_2ghz

    def _alert_handler(self, alert):
        """Checks for any modal dialogs which popup to alert the user and
        either raises a RuntimeError or ignores the alert.

        Args:
          alert: The modal dialog's contents.
        """
        text = alert.text
        #  We ignore warnings that we get when we disable visibility or security
        #  changed to WEP, WPA Personal or WPA Enterprise.
        if 'Security Mode is disabled.' in text:
           alert.accept()
        elif 'Setting the Security Mode to WEP, WPA Personal' in text:
           alert.accept()
        elif 'Turning off SSID Broadcast  will disable WPS' in text:
           alert.accept()
        elif 'Security modes are not compatible' in text:
           alert.accept()
           raise RuntimeError('Security modes are not compatible. %s' % text)
        else:
           alert.accept()
           raise RuntimeError('We have an unhandled alert: %s' % text)

    def get_number_of_pages(self):
        return 1

    def get_supported_bands(self):
        return [{'band': self.band_2ghz,
                 'channels': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]},
                {'band': self.band_5ghz,
                 'channels': [36, 40, 44, 48, 149, 153, 157, 161]}]

    def get_supported_modes(self):
        return [{'band': self.band_5ghz,
                 'modes': [self.mode_a, self.mode_n]},
                {'band': self.band_2ghz,
                 'modes': [self.mode_b, self.mode_n, self.mode_b |
                           self.mode_g, self.mode_g]}]

    def is_security_mode_supported(self, security_mode):
        return security_mode in (self.security_disabled,
                                 self.security_wpapsk,
                                 self.security_wep)

    def navigate_to_page(self, page_number):
        if page_number == 1:
           url = urlparse.urljoin(self.admin_interface_url,
                                  'Wireless_Basic.asp')
           self.driver.get(url)
        else:
           raise RuntimeError('Invalid page number passed.  Number of pages '
                              '%d, page value sent was %d' %
                              (self.get_number_of_pages(), page_number))

    def save_page(self, page_number):
        self.click_button_by_xpath('//a[text()="Save Settings"]',
                                    alert_handler=self._alert_handler)
        continue_xpath = '//input[@value="Continue" and @type="button"]'
        self.wait_for_object_by_xpath(continue_xpath)
        self.click_button_by_xpath(continue_xpath)

    def set_mode(self, mode, band=None):
        self.add_item_to_command_list(self._set_mode, (mode, band), 1, 900)

    def _set_mode(self, mode, band=None):
        mode_mapping = {self.mode_b: 'Wireless-B Only',
                        self.mode_g: 'Wireless-G Only',
                        self.mode_b | self.mode_g: 'Wireless-B/G Only',
                        self.mode_n: 'Wireless-N Only',
                        self.mode_a: 'Wireless-A Only'}
        xpath = '//select[@name="wl0_net_mode"]'
        if self.current_band == self.band_5ghz or band == self.band_5ghz:
            self.current_band = self.band_5ghz
            xpath = '//select[@name="wl1_net_mode"]'
        mode_name = ''
        if mode in mode_mapping.keys():
            mode_name = mode_mapping[mode]
            if (mode & self.mode_a) and (self.current_band != self.band_5ghz):
                #  a mode only in 5Ghz
                logging.info('Mode \'a\' is not available for 2.4Ghz band.')
                return
            elif ((mode & (self.mode_b | self.mode_g) ==
                  (self.mode_b | self.mode_g)) or
                 (mode & self.mode_b == self.mode_b) or
                 (mode & self.mode_g == self.mode_g)) and \
                 (self.current_band != self.band_2ghz):
                #  b/g, b, g mode only in 2.4Ghz
                logging.info('Mode \'%s\' is not available for 5Ghz band.'
                             % mode_name)
                return
        else:
            raise RuntimeError('The mode selected %d is not supported by router'
                               ' %s.', hex(mode), self.get_router_name())
        self.select_item_from_popup_by_xpath(mode_name, xpath)

    def set_radio(self, enabled=True):
        #  If we are enabling we are activating all other UI components, do it
        #  first.  Otherwise we are turning everything off so do it last.
        weight = 1 if enabled else 1000
        self.add_item_to_command_list(self._set_radio, (enabled,), 1, weight)

    def _set_radio(self, enabled=True):
        xpath = '//select[@name="wl0_net_mode"]'
        pref_security = 'Wireless-B Only'
        if self.current_band == self.band_5ghz:
            xpath = '//select[@name="wl1_net_mode"]'
            pref_security = 'Wireless-A Only'
        #  To turn off we pick disabled
        if not enabled:
            pref_security = self.security_disabled
        self.select_item_from_popup_by_xpath(pref_security, xpath)

    def set_ssid(self, ssid):
        self.add_item_to_command_list(self._set_ssid, (ssid,), 1, 900)

    def _set_ssid(self, ssid):
        self._set_radio(enabled=True)
        xpath = '//input[@maxlength="32" and @name="wl0_ssid"]'
        if self.current_band == self.band_5ghz:
           xpath = '//input[@maxlength="32" and @name="wl1_ssid"]'
        self.set_content_of_text_field_by_xpath(ssid, xpath)

    def set_channel(self, channel):
        self.add_item_to_command_list(self._set_channel, (channel,), 1, 900)

    def _set_channel(self, channel):
        self._set_radio(enabled=True)
        channel_choices = ['1 - 2.412 GHz', '2 - 2.417 GHz', '3 - 2.422 GHz',
                           '4 - 2.427 GHz', '5 - 2.432 GHz', '6 - 2.437 GHz',
                           '7 - 2.442 GHz', '8 - 2.447 GHz', '9 - 2.452 GHz',
                           '10 - 2.457 GHz', '11 - 2.462 GHz']
        xpath = '//select[@name="_wl0_channel"]'
        if self.current_band == self.band_5ghz:
           xpath = '//select[@name="_wl1_channel"]'
           channel_choices = ['36 - 5.180 GHz', '40 - 5.200 GHz',
                              '44 - 5.220 GHz', '48 - 5.240 GHz',
                              '149 - 5.745 GHz', '153 - 5.765 GHz',
                              '157 - 5.785 GHz', '161 - 5.805 GHz']
        self.select_item_from_popup_by_xpath(channel_choices[channel - 1],
                                             xpath)

    def set_band(self, band):
        self.add_item_to_command_list(self._set_band, (band,), 1, 900)

    def _set_band(self, band):
        if band == self.band_5ghz:
           self.current_band = self.band_5ghz
        elif band == self.band_2ghz:
           self.current_band = self.band_2ghz
        else:
           raise RuntimeError('Invalid band sent %s' % band)

    def set_security_disabled(self):
        self.add_item_to_command_list(self._set_security_disabled, (), 1, 900)

    def _set_security_disabled(self):
        xpath = '//select[@name="wl0_security_mode"]'
        if self.current_band == self.band_5ghz:
           xpath = '//select[@name="wl1_security_mode"]'
        self.select_item_from_popup_by_xpath(self.security_disabled, xpath)

    def set_security_wep(self, key_value, authentication):
        self.add_item_to_command_list(self._set_security_wep,
                                      (key_value, authentication), 1, 900)

    def _set_security_wep(self, key_value, authentication):
        popup = '//select[@name="wl0_security_mode"]'
        text_field = '//input[@name="wl0_passphrase"]'
        xpath = '//input[@name="wepGenerate0" and @type="button"]'
        if self.current_band == self.band_5ghz:
            popup = '//select[@name="wl1_security_mode"]'
            text_field = '//input[@name="wl1_passphrase"]'
            xpath = '//input[@name="wepGenerate1" and @type="button"]'
        self.wait_for_object_by_xpath(popup)
        self.select_item_from_popup_by_xpath(self.security_wep, popup,
                                             wait_for_xpath=text_field,
                                             alert_handler=self._alert_handler)
        self.set_content_of_text_field_by_xpath(key_value, text_field,
                                                abort_check=True)
        self.click_button_by_xpath(xpath)

    def set_security_wpapsk(self, shared_key, update_interval=1800):
        self.add_item_to_command_list(self._set_security_wpapsk,
                                      (shared_key, update_interval), 1, 900)

    def _set_security_wpapsk(self, shared_key, update_interval=1800):
        popup = '//select[@name="wl0_security_mode"]'
        key_field = '//input[@name="wl0_wpa_psk"]'
        if self.current_band == self.band_5ghz:
           popup = '//select[@name="wl1_security_mode"]'
           key_field = '//input[@name="wl1_wpa_psk"]'
        self.wait_for_object_by_xpath(popup)
        self.select_item_from_popup_by_xpath(self.security_wpapsk, popup,
                                             wait_for_xpath=key_field,
                                             alert_handler=self._alert_handler)
        self.set_content_of_text_field_by_xpath(shared_key, key_field,
                                                abort_check=True)

    def set_visibility(self, visible=True):
        self.add_item_to_command_list(self._set_visibility, (visible,), 1, 900)

    def _set_visibility(self, visible=True):
        self._set_radio(enabled=True)
        value = 0 if visible else 1
        xpath = '//input[@name="wl0_closed" and @value="%s"]' % value
        if self.current_band == self.band_5ghz:
           xpath = '//input[@name="wl1_closed" and @value="%s"]' % value
        self.click_button_by_xpath(xpath, alert_handler=self._alert_handler)
