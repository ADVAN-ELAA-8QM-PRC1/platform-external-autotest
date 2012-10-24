# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

class FAFTClientAttribute(object):
    """Class that tests platform name and gives client machine attributes."""
    version = 1

    DEFAULT_SETTING = {'broken_warm_reset': False,
                       'chrome_ec': False,
                       'has_lid': True,
                       'has_keyboard': True,
                       'keyboard_dev': True,
                       'ec_capability': list(),
                       'wp_voltage': 'pp1800',
                       'key_matrix_layout': 0}

    def __init__(self, platform):
        """Initialized.

        Args:
          platform: Platform name returned by FAFT client.
        """
        self.__dict__.update(self.DEFAULT_SETTING)
        self.__dict__.update(self._get_platform_setting(platform))


    def _get_platform_setting(self, platform):
        """Return platform-specific settings."""
        setting = dict()

        setting['platform'] = platform

        # Set 'broken_warm_reset'
        if platform in ['Parrot', 'Butterfly']:
            setting['broken_warm_reset'] = True

        # Set 'chrome_ec'
        if platform in ['Link', 'Snow']:
            setting['chrome_ec'] = True

        # Set 'has_lid'
        if platform in ['Stumpy', 'Kiev']:
            setting['has_lid'] = False

        # Set 'has_keyboard'
        if platform in ['Stumpy', 'Kiev']:
            setting['has_keyboard'] = False

        # Set 'keyboard_dev'
        if platform in ['Aebl', 'Alex', 'Kaen', 'Kiev', 'Lumpy', 'Mario',
                        'Seaboard', 'Stumpy', 'ZGB']:
            setting['keyboard_dev'] = False

        # Set 'ec_capability'
        if platform == 'Link':
            setting['ec_capability'] = ['adc_ectemp', 'battery', 'charging',
                                        'keyboard', 'lid', 'x86', 'thermal',
                                        'usb', 'peci']
        elif platform == 'Snow':
            setting['ec_capability'] = ['battery', 'keyboard', 'arm']

        # Set 'wp_voltage'
        if platform == 'Link':
            setting['wp_voltage'] = 'pp3300'

        # Set 'key_matrix_layout'
        if platform == 'Parrot':
            setting['key_matrix_layout'] = 1

        return setting
