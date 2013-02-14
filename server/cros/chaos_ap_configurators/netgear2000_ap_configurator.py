# Copyright (c) 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import netgear_single_band_configurator
from netgear_single_band_configurator import *


class Netgear2000APConfigurator(netgear_single_band_configurator.
                                NetgearSingleBandAPConfigurator):
    """Derived class to control Netgear WNR2000v3 router."""

    def _alert_handler(self, alert):
        """Checks for any modal dialogs which popup to alert the user and
        either raises a RuntimeError or ignores the alert.

        Args:
          alert: The modal dialog's contents.
        """
        text = alert.text
        if 'The WEP security can only be supported on one SSID' in text:
            logging.info(text)
            alert.accept()
        elif 'WPA-PSK [TKIP] only operates at "Up to 54Mbps"' in text:
            raise RuntimeError('Security and mode do not match:', text)
        elif '40 Mhz and 20 Mhz coexistence' in text:
            logging.info(text)
            alert.accept()
        elif 'Are you sure that you do not want any wireless security' in text:
            logging.info(text)
            alert.accept()
        elif 'WPS requires SSID broadcasting in order to work' in text:
            logging.info(text)
            alert.accept()
        elif 'WPS is going to become inaccessible' in text:
            logging.info(text)
            alert.accept()
        else:
            super(Netgear2000APConfigurator, self)._alert_handler(alert)


    def logout_from_previous_netgear(self):
        """Some netgear routers dislike you being logged into another
           one of their kind. So make sure that you are not."""
        print 'Logging out of older router'
        self.click_button_by_id('yes', alert_handler=self._alert_handler)
        self.navigate_to_page(page_number)


    def navigate_to_page(self, page_number):
        try:
            self.get_url(urlparse.urljoin(self.admin_interface_url,
                         'adv_index.htm'), page_title='WNR2000v3')
            self.click_button_by_id('setup_bt')
            self.wait_for_object_by_id('wireless')
            self.click_button_by_id('wireless')
        except Exception as e:
            if os.path.basename(self.driver.current_url) != 'adv_index.htm':
                raise RuntimeError('Invalid url %s' % self.driver.current_url)
            elif os.path.basename(
                 self.driver.current_url) == 'multi_login.html':
                self.logout_from_previous_netgear()
        setframe = self.driver.find_element_by_xpath(
                   '//iframe[@name="formframe"]')
        settings = self.driver.switch_to_frame(setframe)
        self.wait_for_object_by_xpath('//input[@name="ssid"]')


    def get_supported_modes(self):
        return [{'band': self.band_2ghz,
                 'modes': ['Up to 300 Mbps', 'Up to 150 Mbps',
                           'Up to 54 Mbps']}]


    def set_visibility(self, visible=True):
        self.add_item_to_command_list(self._set_visibility, (visible,), 1, 900)


    def _set_visibility(self, visible=True):
        xpath = '//input[@name="ssid_bc" and @type="checkbox"]'
        self.set_check_box_selected_by_xpath(xpath, selected=visible,
                                             wait_for_xpath=None,
                                             alert_handler=self._alert_handler)
