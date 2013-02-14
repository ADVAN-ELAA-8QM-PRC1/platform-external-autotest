# Copyright (c) 2012 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import urlparse

import ap_configurator

class Linksyse2000APConfigurator(ap_configurator.APConfigurator):


    def _sec_alert(self, alert):
        text = alert.text
        if 'Your wireless security mode is not compatible with' in text:
           alert.accept()
        elif 'WARNING: Your Wireless-N devices will only operate' in text:
           alert.accept()
        else:
           raise RuntimeError('Invalid handler')


    def get_number_of_pages(self):
        return 2


    def get_supported_modes(self):
        return [{'band': self.band_2ghz,
                 'modes': [self.mode_m, self.mode_b | self.mode_g,self.mode_g,
                           self.mode_b, self.mode_n, self.mode_d]},
                {'band': self.band_5ghz,
                 'modes': [self.mode_m, self.mode_a, self.mode_n,
                           self.mode_d]}]


    def get_supported_bands(self):
        return [{'band': self.band_2ghz,
                 'channels': ['Auto', 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]},
                {'band': self.band_5ghz,
                 'channels': ['Auto', 36, 40, 44, 48, 149, 153, 157, 161]}]


    def is_security_mode_supported(self, security_mode):
        return security_mode in (self.security_type_disabled,
                                 self.security_type_wpapsk,
                                 self.security_type_wpa2psk,
                                 self.security_type_wep)


    def navigate_to_page(self, page_number):
        if page_number == 1:
            page_url = urlparse.urljoin(self.admin_interface_url,
                                        'Wireless_Basic.asp')
            self.get_url(page_url, page_title='Settings')
        elif page_number == 2:
            page_url = urlparse.urljoin(self.admin_interface_url,
                                        'WL_WPATable.asp')
            self.get_url(page_url, page_title='Security')
        else:
            raise RuntimeError('Invalid page number passed. Number of pages '
                               '%d, page value sent was %d' %
                               (self.get_number_of_pages(), page_number))


    def save_page(self, page_number):
        xpath = '//a[text()="Save Settings"]'
        button = self.driver.find_element_by_xpath(xpath)
        button.click()
        button_xpath = '//input[@name="btaction"]'
        if self.wait_for_object_by_xpath(button_xpath):
            button = self.driver.find_element_by_xpath(button_xpath)
            button.click()


    def set_mode(self, mode, band=None):
        if band:
            self.add_item_to_command_list(self._set_band, (band,), 1, 700)
        self.add_item_to_command_list(self._set_mode, (mode, band), 1, 800)


    def _set_mode(self, mode, band=None):
        xpath = '//select[@name="wl_net_mode_24g"]'
        mode_mapping = {self.mode_m:'Mixed',
                        self.mode_b | self.mode_g:'BG-Mixed',
                        self.mode_g:'Wireless-G Only',
                        self.mode_b:'Wireless-B Only',
                        self.mode_n:'Wireless-N Only',
                        self.mode_d:'Disabled',
                        self.mode_a:'Wireless-A Only'}
        if self.current_band == self.band_5ghz or band == self.band_5ghz:
            xpath = '//select[@name="wl_net_mode_5g"]'
        mode_name = ''
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
            raise RuntimeError("The mode %s is not supported" % mode_name)
        self.select_item_from_popup_by_xpath(mode_name, xpath,
                                             alert_handler=self._sec_alert)


    def set_ssid(self, ssid):
        self.add_item_to_command_list(self._set_ssid, (ssid,), 1, 900)


    def _set_ssid(self, ssid):
        xpath = '//input[@maxlength="32" and @name="wl_ssid_24g"]'
        mode = '//select[@name="wl_net_mode_24g"]'
        if self.current_band == self.band_5ghz:
            xpath = '//input[@maxlength="32" and @name="wl_ssid_5g"]'
            mode = '//select[@name="wl_net_mode_5g"]'
        ssid_field = self.driver.find_element_by_xpath(xpath)
        if ssid_field.get_attribute('disabled') == 'true':
            # This means the mode is disabled, so we have to set it to something
            # so we can fill in the SSID
            self.select_item_from_popup_by_xpath('Mixed', mode,
                                                 alert_handler=self._sec_alert)
        self.set_content_of_text_field_by_xpath(ssid, xpath)


    def set_channel(self, channel):
        self.add_item_to_command_list(self._set_channel, (channel,), 1, 900)


    def _set_channel(self, channel):
        position = self._get_channel_popup_position(channel)
        xpath = '//select[@name="wl_schannel"]'
        channels=['Auto', '1', '2', '3', '4', '5', '6', '7', '8', '9',
                  '10', '11']
        if self.current_band == self.band_5ghz:
            xpath = '//select[@name="wl_schannel"]'
            channels = ['Auto', '36', '40', '44', '48', '149', '153',
                        '157', '161']
        self.select_item_from_popup_by_xpath(channels[position], xpath)


    def set_ch_width(self, channel_wid):
        self.add_item_to_command_list(self._set_ch_width,(channel_wid,),
                                      1, 900)


    def _set_ch_width(self, channel_wid):
        channel_width_choice=['Auto (20MHz or 40MHz)', '20MHz only']
        xpath = '//select[@name="_wl_nbw"]'
        if self.current_band == self.band_5ghz:
            channel_width_choice=['Auto (20MHz or 40MHz)', '20MHz only',
                                  '40MHz only']
            xpath = '//select[@name="_wl_nbw"]'
        self.select_item_from_popup_by_xpath(channel_width_choice[channel_wid],
                                             xpath)


    def set_band(self, band):
        self.add_item_to_command_list(self._set_band, (band,), 1, 800)


    def _set_band(self, band):
        if band == self.band_2ghz:
            self.current_band = self.band_2ghz
            xpath = '//input[@name="wl_sband" and @value="24g"]'
            element = self.driver.find_element_by_xpath(xpath)
            element.click()
        elif band == self.band_5ghz:
            self.current_band = self.band_5ghz
            xpath = '//input[@name="wl_sband" and @value="5g"]'
            element = self.driver.find_element_by_xpath(xpath)
            element.click()
        else:
            raise RuntimeError('Invalid band %s' % band)


    def set_radio(self, enabled=True):
        return None


    def set_security_disabled(self):
        self.add_item_to_command_list(self._set_security_disabled, (), 2, 1000)


    def _set_security_disabled(self):
        xpath = '//select[@name="security_mode2"]'
        self.select_item_from_popup_by_xpath('Disabled', xpath)


    def set_security_wep(self, key_value, authentication):
        self.add_item_to_command_list(self._set_security_wep,
                                      (key_value, authentication), 2, 1000)


    def _set_security_wep(self, key_value, authentication):
        # WEP and WPA-Personal are not supported for Wireless-N only mode
        # and Mixed mode.
        # WEP and WPA-Personal do not show up in the list, no alert is thrown.
        popup = '//select[@name="security_mode2"]'
        if not self.item_in_popup_by_xpath_exist('WEP', popup):
            raise RuntimeError ('Unable to find wep security item in popup.  '
                                'Is the mode set to N?')
        self.select_item_from_popup_by_xpath(self.security_wep, popup,
                                             alert_handler=self._sec_alert)
        text = '//input[@name="wl_passphrase"]'
        self.set_content_of_text_field_by_xpath(key_value, text,
                                                abort_check=False)
        xpath = '//input[@value="Generate"]'
        self.click_button_by_xpath(xpath, alert_handler=self._sec_alert)


    def set_security_wpapsk(self, shared_key, update_interval=None):
        # WEP and WPA-Personal are not supported for Wireless-N only mode,
        # so use WPA2-Personal to avoid conflicts.
        self.add_item_to_command_list(self._set_security_wpa2psk,
                                      (shared_key,), 2, 900)


    def _set_security_wpa2psk(self, shared_key):
        logging.info('update_interval is not supported')
        popup = '//select[@name="security_mode2"]'
        self.select_item_from_popup_by_xpath('WPA Personal', popup,
                                             alert_handler=self._sec_alert)
        text = '//input[@name="wl_wpa_psk"]'
        self.set_content_of_text_field_by_xpath(shared_key, text,
                                                abort_check=False)


    def set_visibility(self, visible=True):
        self.add_item_to_command_list(self._set_visibility, (visible,), 1, 900)


    def _set_visibility(self, visible=True):
        value = 0 if visible else 1
        xpath = '//input[@name="wl_closed_24g" and @value="%s"]' %value
        if self.current_band == self.band_5ghz:
            xpath = '//input[@name="wl_closed_5g" and @value="%s"]' %value
        self.click_button_by_xpath(xpath)
