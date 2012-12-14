# Copyright (c) 2012 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
import time
import urlparse

import ap_configurator

class BuffaloAPConfigurator(ap_configurator.APConfigurator):

    def __init__(self, router_dict):
        super(BuffaloAPConfigurator, self).__init__(router_dict)
        self.security_disabled = 'Disabled'
        self.security_wep = 'WEP'
        self.security_wpapsk = 'WPA Personal'
        self.security_wpa2psk = 'WPA2 Personal'
        self.security_wpa8021x = 'WPA Enterprise'
        self.security_wpa28021x = 'WPA2 Enterprise'


    def get_number_of_pages(self):
        return 2


    def get_supported_modes(self):
        return [{'band':self.band_2ghz,
                 'modes':[self.mode_b, self.mode_g, self.mode_n,
                          self.mode_b | self.mode_g,
                          self.mode_n | self.mode_g]}]


    def get_supported_bands(self):
        return [{'band':self.band_2ghz,
                 'channels':[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]}]


    def is_security_mode_supported(self, security_mode):
        return security_mode in (self.security_disabled,
                                 self.security_wpapsk,
                                 self.security_wep)


    def navigate_to_page(self, page_number):
        if page_number == 1:
           page_url = urlparse.urljoin(self.admin_interface_url,
                                       'Wireless_Basic.asp')
           self.driver.get(page_url)
        elif page_number == 2:
           page_url = urlparse.urljoin(self.admin_interface_url,
                                       'WL_WPATable.asp')
           self.driver.get(page_url)
        else:
           raise RuntimeError('Invalid page number passed. Number of pages '
                              '%d, page value sent was %d' %
                              (self.get_number_of_pages(), page_number))


    def save_page(self, page_number):
        apply_set = '//input[@name="apply_button"]'
        self.click_button_by_xpath(apply_set)
        if self.driver.find_element_by_class_name("ddwrt_message"):
            time.sleep(5)
        else:
            raise RuntimeError('Processing dialog not found!')


    def set_mode(self, mode, band=None):
        self.add_item_to_command_list(self._set_mode, (mode,), 1, 900)


    def _set_mode(self, mode):
        # Bands are not supported, so ignore.
        # Create the mode to popup item mapping.
        mode_mapping = {self.mode_b:'B-Only', self.mode_g: 'G-Only',
                        self.mode_n:'N-Only (2.4 GHz)',
                        self.mode_b | self.mode_g:'BG-Mixed',
                        self.mode_n | self.mode_g:'NG-Mixed'}
        mode_name = ''
        if mode in mode_mapping:
            mode_name = mode_mapping[mode]
        else:
            raise RuntimeError('The mode %d not supported by router %s. ',
                               hex(mode), self.get_router_name())
        xpath = '//select[@name="ath0_net_mode"]'
        self.select_item_from_popup_by_xpath(mode_name, xpath)


    def set_radio(self, enabled):
        #  We cannot turn off radio on Buffalo.
        logging.info('This router (%s) does not support radio.' %
                     self.get_router_name())
        return None


    def set_ssid(self, ssid):
        self.add_item_to_command_list(self._set_ssid, (ssid,), 1, 900)


    def _set_ssid(self, ssid):
        xpath = '//input[@maxlength="32" and @name="ath0_ssid"]'
        self.set_content_of_text_field_by_xpath(ssid, xpath)


    def set_channel(self, channel):
        self.add_item_to_command_list(self._set_channel, (channel,), 1, 900)


    def _set_channel(self, channel):
        position = _get_channel_popup_position(channel)
        channel_choices = ['1 - 2412 MHz', '2 - 2417 MHz', '3 - 2422 MHz',
                           '4 - 2427 MHz', '5 - 2432 MHz', '6 - 2437 MHz',
                           '7 - 2442 MHz', '8 - 2447 MHz', '9 - 2452 MHz',
                           '10 - 2457 MHz', '11 - 2462 MHz']
        xpath = '//select[@name="ath0_channel"]'
        self.select_item_from_popup_by_xpath(channel_choices[position], xpath)


    def set_ch_width(self, channel_wid):
        self.add_item_to_command_list(self._set_ch_width,(channel_wid,), 1,
                                      900)


    def _set_ch_width(self, channel_wid):
        channel_width_choice=['Full (20 MHz)', 'Half (10 MHz)',
                              'Quarter (5 MHz)']
        xpath = '//select[@name="ath0_channelbw"]'
        self.select_item_from_popup_by_xpath(channel_width_choice[channel_wid],
                                             xpath)


    def set_wireless_mode(self, wireles_mo):
        self.add_item_to_command_list(self._set_wireless_mode,
                                      (wireles_mo,), 1, 900)


    def _set_wireless_mode(self, wireless_mo):
        wireless_mode_choices = ['AP', 'Client', 'Client Bridge',
                                 'Adhoc', 'WDS Station', 'WDS AP']
        xpath = '//select[@name="ath0_mode"]'
        self.select_item_from_popup_by_xpath(wireless_mode_choices[wireles_mo],
                                             xpath)


    def set_band(self, band):
        logging.info('This router (%s) does not support multiple bands.' %
                     self.get_router_name())
        return None


    def set_security_disabled(self):
        self.add_item_to_command_list(self._set_security_disabled, (), 2, 1000)


    def _set_security_disabled(self):
        xpath = '//select[@name="ath0_security_mode"]'
        self.select_item_from_popup_by_xpath(self.security_disabled, xpath)


    def set_security_wep(self, key_value, authentication):
        self.add_item_to_command_list(self._set_security_wep,
                                      (key_value, authentication), 2, 1000)


    def _set_security_wep(self, key_value, authentication):
        # Buffalo supports WEP with wireless network mode N.
        # No exception is thrown for N-mode with WEP security.
        popup = '//select[@name="ath0_security_mode"]'
        text_field = '//input[@name="ath0_passphrase"]'
        self.wait_for_object_by_xpath(popup)
        self.select_item_from_popup_by_xpath(self.security_wep, popup,
                                             wait_for_xpath=text_field)
        self.set_content_of_text_field_by_xpath(key_value, text_field,
                                                abort_check=True)
        self.click_button_by_xpath('//input[@value="Generate"]')


    def set_security_wpapsk(self, shared_key, update_interval=3600):
        self.add_item_to_command_list(self._set_security_wpapsk,
                                      (shared_key, update_interval), 2, 900)


    def _set_security_wpapsk(self, shared_key, update_interval=3600):
        popup = '//select[@name="ath0_security_mode"]'
        self.wait_for_object_by_xpath(popup)
        key_field = '//input[@name="ath0_wpa_psk"]'
        self.select_item_from_popup_by_xpath(self.security_wpapsk, popup,
                                             wait_for_xpath=key_field)
        self.set_content_of_text_field_by_xpath(shared_key, key_field)
        interval_field='//input[@name="ath0_wpa_gtk_rekey"]'
        self.set_content_of_text_field_by_xpath(str(update_interval),
                                                interval_field)


    def set_visibility(self, visible=True):
        self.add_item_to_command_list(self._set_visibility, (visible,), 1, 900)


    def _set_visibility(self, visible=True):
        int_value = 0 if visible else 1
        xpath = '//input[@value="%d" and @name="ath0_closed"]' % int_value
        self.click_button_by_xpath(xpath)
