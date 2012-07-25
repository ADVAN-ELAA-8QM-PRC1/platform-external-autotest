# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

class FAFTClientAttribute(object):
    """Class that tests platform name and gives client machine attributes."""
    version = 1

    DEFAULT_SETTING = {'keyboard_dev': True,
                       'chrome_ec': False,
                       'ec_capability': list()}

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

        if platform in ['Aebl', 'Alex', 'Kaen', 'Lumpy', 'Mario', 'Seaboard',
                        'Stumpy', 'ZGB']:
            setting['keyboard_dev'] = False

        if platform in ['Link', 'Snow']:
            setting['chrome_ec'] = True

        if platform == 'Link':
            setting['ec_capability'] = ['adc_ectemp', 'battery', 'charging',
                                        'keyboard', 'lid', 'x86', 'thermal',
                                        'usb', 'peci']
        elif platform == 'Snow':
            setting['ec_capability'] = ['battery', 'charging', 'keyboard',
                                        'lid', 'arm']

        return setting
