# Copyright (c) 2012 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
import random

import ap_configurator
import selenium.common.exceptions


class AsusAPConfigurator(ap_configurator.APConfigurator):

    def __init__(self, router_dict):
        super(AsusAPConfigurator, self).__init__(router_dict)
        #  Overrides
        self.security_wep_none = 'None'
        self.security_wep64 = 'WEP-64bits'
        self.security_wep128 = 'WEP-128bits'
        self.security_wpapsk = 'WPA-Personal'
        self.security_wpa2psk = 'WPA2-Personal'
        self.security_wpaautopsk = 'WPA-Auto-Personal'
        self.security_wpa8021x = 'WPA-Enterprise'
        self.security_wpa28021x = 'WPA2-Enterprise'
        self.security_wpaauto8021x = 'WPA-Auto-Enterprise'
        self.security_radius8021x = 'Radius with 802.1x'
        self.wep_authentication_open = 'Open System'
        self.wep_authentication_shared = 'Shared Key'
        self.current_band = self.band_2ghz

    def _set_authentication(self, authentication, wait_for_xpath=None):
        """Sets the authentication method in the popup.

        Args:
          authentication: The authentication method to select.
          wait_for_path: An item to wait for before returning.
        """
        auth = '//select[@name="rt_auth_mode"]'
        if self.current_band == self.band_5ghz:
            auth = '//select[@name="wl_auth_mode"]'
        self.select_item_from_popup_by_xpath(authentication, auth,
            wait_for_xpath, alert_handler=self._invalid_security_handler)

    def _invalid_security_handler(self, alert):
        text = alert.text
        # This tweaks encryption but is more of a warning, so we can dismiss.
        if text.find('RT-N56U will change WEP or TKIP encryption to AES') != -1:
            alert.accept()
            raise RuntimeError('You have entered an invalid configuration: '
                               '%s' % text)

    def get_number_of_pages(self):
        return 2

    def get_supported_bands(self):
        return [{'band': self.band_2ghz,
                 'channels': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]},
                {'band': self.band_5ghz,
                 'channels': [36, 40, 44, 48, 149, 153, 157, 161]}]

    def get_supported_modes(self):
        return [{'band': self.band_2ghz,
                 'modes': [self.mode_b, self.mode_n, self.mode_b |
                           self.mode_g, self.mode_b]},
                {'band': self.band_5ghz,
                 'modes': [self.mode_n, self.mode_a]}]

    def is_security_mode_supported(self, security_mode):
        return security_mode in (self.security_disabled,
                                 self.security_wpapsk,
                                 self.security_wep)

    def navigate_to_page(self, page_number):
        # The page is determined by what band we are using. We ignore the input.
        admin_url = self.admin_interface_url
        if self.current_band == self.band_2ghz:
            self.driver.get('%s/Advanced_Wireless2g_Content.asp' % admin_url)
        elif self.current_band == self.band_5ghz:
            self.driver.get('%s/Advanced_Wireless_Content.asp' % admin_url)
        else:
            raise RuntimeError('Invalid page number passed.  Number of pages '
                               '%d, page value sent was %d' %
                               (self.get_number_of_pages(), page_number))

    def save_page(self, page_number):
        button = self.driver.find_element_by_id('applyButton')
        button.click()
        menu_id = 'menu_body' #  id of the table with the main content
        try:
            self.wait_for_object_by_id(menu_id)
        except selenium.common.exceptions.TimeoutException, e:
            raise SeleniumTimeoutException('Unable to find the object by id:'
                                           '%s\n WebDriver exception: %s' %
                                           menu_id, str(e))
        self.navigate_to_page(page_number)

    def set_mode(self, mode, band=None):
        self.set_security_disabled() #  To avoid the modal dialog.
        self.add_item_to_command_list(self._set_mode, (mode, band), 1, 900)

    def _set_mode(self, mode, band=None):
        xpath = '//select[@name="rt_gmode"]'
        #  Create the mode to popup item mapping
        mode_mapping = {self.mode_b: 'b Only', self.mode_g: 'g Only',
                        self.mode_b | self.mode_g: 'b/g Only',
                        self.mode_n: 'n Only', self.mode_a: 'a Only'}
        mode_name = ''
        if self.current_band == self.band_5ghz or band == self.band_5ghz:
            xpath = '//select[@name="wl_gmode"]'
        if mode in mode_mapping.keys():
            mode_name = mode_mapping[mode]
            if (mode & self.mode_a) and (self.current_band == self.band_2ghz):
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
            raise RuntimeError('The mode selected \'%s\' is not supported by '
                               'router %s.' % mode_name, self.get_router_name())
        self.select_item_from_popup_by_xpath(mode_name, xpath,
            alert_handler=self._invalid_security_handler)

    def set_radio(self, enabled):
        #  We cannot turn off radio on ASUS.
        return None

    def set_ssid(self, ssid):
        self.add_item_to_command_list(self._set_ssid, (ssid,), 1, 900)

    def _set_ssid(self, ssid):
        xpath = '//input[@maxlength="32" and @name="rt_ssid"]'
        if self.current_band == self.band_5ghz:
            xpath = '//input[@maxlength="32" and @name="wl_ssid"]'
        self.set_content_of_text_field_by_xpath(ssid, xpath)

    def set_channel(self, channel):
        self.add_item_to_command_list(self._set_channel, (channel,), 1, 900)

    def _set_channel(self, channel):
        position = self._get_channel_popup_position(channel)
        channel_choices = range(1, 11)
        xpath = '//select[@name="rt_channel"]'
        if self.current_band == self.band_5ghz:
            xpath = '//select[@name="wl_channel"]'
            channel_choices = ['36', '40', '44', '48', '149', '153',
                               '157', '161']
        self.select_item_from_popup_by_xpath(str(channel_choices[position]),
                                             xpath)

    def set_band(self, band):
        if band == self.band_2ghz:
            self.current_band = self.band_2ghz
        elif band == self.band_5ghz:
            self.current_band = self.band_5ghz
        else:
            raise RuntimeError('Invalid band sent %s' % band)
        # Band determines page so it is the most important setting.
        # self.add_item_to_command_list(self._set_band, (band,), 1, 1001)

    def _set_band(self, band):
        if band == self.band_2ghz:
            self.current_band = self.band_2ghz
        elif band == self.band_5ghz:
            self.current_band = self.band_5ghz
        else:
            raise RuntimeError('Invalid band sent %s' % band)

    def set_security_disabled(self):
        self.add_item_to_command_list(self._set_security_disabled, (), 1, 1000)

    def _set_security_disabled(self):
        popup = '//select[@name="rt_wep_x"]'
        if self.current_band == self.band_5ghz:
            popup = '//select[@name="wl_wep_x"]'
        self._set_authentication(self.wep_authentication_open,
                                 wait_for_xpath=popup)
        self.select_item_from_popup_by_xpath(self.security_wep_none, popup)

    def set_security_wep(self, key_value, authentication):
        self.add_item_to_command_list(self._set_security_wep,
                                      (key_value, authentication), 1, 1000)

    def _set_security_wep(self, key_value, authentication):
        popup = '//select[@name="rt_wep_x"]'
        text_field = '//input[@name="rt_phrase_x"]'
        if self.current_band == self.band_5ghz:
            popup = '//select[@name="wl_wep_x"]'
            text_field = '//input[@name="wl_phrase_x"]'
        self._set_authentication(self.wep_authentication_open,
                                 wait_for_xpath=popup)
        self.select_item_from_popup_by_xpath(self.security_wep64, popup,
            wait_for_xpath=text_field,
            alert_handler=self._invalid_security_handler)
        field = self.driver.find_element_by_xpath(text_field)
        field.clear()
        field.send_keys(key_value)

    def set_security_wpapsk(self, shared_key, update_interval=1800):
        #  Asus does not support TKIP (wpapsk) encryption in 'n' mode.
        #  So we will use AES (wpa2psk) to avoid conflicts and modal dialogs.
        self.add_item_to_command_list(self._set_security_wpa2psk,
                                      (shared_key, update_interval), 1, 900)

    def _set_security_wpa2psk(self, shared_key, update_interval):
        key_field = '//input[@name="rt_wpa_psk"]'
        interval_field = '//input[@name="rt_wpa_gtk_rekey"]'
        if self.current_band == self.band_5ghz:
            key_field = '//input[@name="wl_wpa_psk"]'
            interval_field = '//input[@name="wl_wpa_gtk_rekey"]'
        self._set_authentication(self.security_wpa2psk,
                                 wait_for_xpath=key_field)
        self.set_content_of_text_field_by_xpath(shared_key, key_field)
        self.set_content_of_text_field_by_xpath(str(update_interval),
                                                interval_field)

    def set_visibility(self, visible=True):
        self.add_item_to_command_list(self._set_visibility,(visible,), 1, 900)

    def _set_visibility(self, visible=True):
        #  value=0 is visible; value=1 is invisible
        value = 0 if visible else 1
        xpath = '//input[@name="rt_closed" and @value="%s"]' % value
        if self.current_band == self.band_5ghz:
            xpath = '//input[@name="wl_closed" and @value="%s"]' % value
        ssid = self.driver.find_element_by_xpath(xpath)
        ssid.click()
