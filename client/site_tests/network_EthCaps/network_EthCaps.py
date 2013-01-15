# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections, logging, os

from autotest_lib.client.bin import test, utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros import rtc, sys_power

# TODO(tbroch) General:
# - What other Ethernet Capabilities should we check

# TODO(tbroch) WOL:
# - Should we test any of the other modes?  I chose magic as it meant that only
#   the target device should be awaken.
class network_EthCaps(test.test):
    version = 1

    # If WOL setting changed during test then restore to original during cleanup
    _restore_wol = False


    def _parse_ethtool_caps(self):
        """Retrieve ethernet capabilities.

        Executes ethtool command and parses various capabilities into a
        dictionary.
        """
        caps = collections.defaultdict(list)

        cmd = "ethtool %s" % self._ethname
        prev_keyname = None
        for ln in utils.system_output(cmd).splitlines():
            cap_str = ln.strip()
            try:
                (keyname, value) = cap_str.split(': ')
                caps[keyname].extend(value.split())
                prev_keyname = keyname
            except ValueError:
                # keyname from previous line, add there
                if prev_keyname:
                    caps[prev_keyname].extend(cap_str.split())

        for keyname in caps:
            logging.debug("cap['%s'] = %s", keyname, caps[keyname])

        self._caps = caps


    def _check_eth_caps(self):
        """Check necessary LAN capabilities are present.

        Hardware and driver should support the following functionality:
          1000baseT, 100baseT, 10baseT, half-duplex, full-duplex, auto-neg, WOL

        Raises:
          error.TestError if above LAN capabilities are NOT supported.
        """
        default_eth_caps = {
            'Supported link modes': ['10baseT/Half', '100baseT/Half',
                                      '1000baseT/Half', '10baseT/Full',
                                      '100baseT/Full', '1000baseT/Full'],
            'Supports auto-negotiation': ['Yes'],
            # TODO(tbroch): Will this order, 'pumbg' remain across other h/w +
            # drivers
            # TODO(tbroch): Other WOL caps: 'a': arp and 's': magicsecure are
            # they important?  Are any of these undesirable/security holes?
            'Supports Wake-on': ['pumbg']
            }
        errors = 0

        for keyname in default_eth_caps:
            if keyname not in self._caps:
                logging.error("\'%s\' not a capability of %s", keyname,
                              self._ethname)
                errors += 1
                continue

            for value in default_eth_caps[keyname]:
                if value not in self._caps[keyname]:
                    logging.error("\'%s\' not a supported mode in \'%s\' of %s",
                                  value, keyname, self._ethname)
                    errors += 1

        if errors:
            raise error.TestError("Eth capability checks.  See errors")


    def _test_wol_magic_packet(self):
        """Check the Wake-on-LAN (WOL) magic packet capabilities of a device.

        Raises:
          error.TestError if WOL functionality fails
        """
        # Magic number WOL supported
        capname = 'Supports Wake-on'
        if self._caps[capname][0].find('g') != -1:
            logging.info("%s support magic number WOL", self._ethname)
        else:
            raise error.TestError('%s should support magic number WOL' %
                            self._ethname)

        # Check that WOL works
        if self._caps['Wake-on'][0] != 'g':
            utils.system_output("ethtool -s %s wol g" % self._ethname)
            self._restore_wol = True

        # Set RTC as backup to WOL
        before_suspend_secs = rtc.get_seconds()
        alarm_secs =  before_suspend_secs + self._threshold_secs * 2
        rtc.set_wake_alarm(alarm_secs)

        sys_power.do_suspend()

        after_suspend_secs = rtc.get_seconds()
        # flush RTC as it may not work subsequently if wake was not RTC
        rtc.set_wake_alarm(0)

        suspend_secs = after_suspend_secs - before_suspend_secs
        if suspend_secs > self._threshold_secs:
            raise error.TestError("Device woke due to RTC not WOL")


    def _verify_wol_magic(self):
        """If possible identify wake source was caused by WOL.

        The bits identifying this may be cleared by the time kernel/userspace
        gets a change to query.  However if the firmware has a log it may expose
        the wake source.  This method attempts to interrogate the wake source
        details if they are present on the system.

        Returns:
          True if verified or unable to verify due to system limitations
          False otherwise
        """
        cmd = "mosys smbios info bios"
        bios_info = utils.system_output(cmd).replace(' ', '').split('|')
        logging.debug("bios_info = %s", bios_info)
        if 'coreboot' not in bios_info:
            logging.warn("Unable to verify wake in s/w due to firmware type")
            if 'INSYDE' not in bios_info:
                raise error.TestError("Unrecognized firmware found")
            return True

        fw_log = "/sys/firmware/log"
        if not os.path.isfile(fw_log):
            logging.warn("Unable to verify wake in s/w due to missing log %s",
                         fw_log)
            return True

        log_info_str = utils.system_output("egrep '(SMI|PM1|GPE0)_STS:' %s" %
                                           fw_log)
        status_dict = {}
        for ln in log_info_str.splitlines():
            logging.debug("f/w line = %s", ln)
            try:
                (status_reg, status_values) = ln.strip().split(":")
                status_dict[status_reg] = status_values.split()
            except ValueError:
                # no bits asserted ... empty list
                status_dict[status_reg] = list()

        for status_reg in status_dict:
            logging.debug("status_dict[%s] = %s", status_reg,
                          status_dict[status_reg])

        return ('PM1' in status_dict['SMI_STS']) and \
            ('WAK' in status_dict['PM1_STS']) and \
            ('PCIEXPWAK' in status_dict['PM1_STS']) and \
            len(status_dict['GPE0_STS']) == 0


    def cleanup(self):
        if self._restore_wol:
            utils.system_output("ethtool -s %s wol %s" %
                                (self._ethname, self._caps['Wake-on'][0]))


    def run_once(self, ethname=None, threshold_secs=None):
        """Run the test.

        Args:
          ethname: string of ethernet device under test
          threshold_secs: integer of seconds to determine whether wake occurred
            due to WOL versus RTC
        """
        if not ethname:
            raise error.TestError("Name of ethernet device must be declared")

        self._ethname = ethname
        self._threshold_secs = threshold_secs

        self._parse_ethtool_caps()
        self._check_eth_caps()
        self._test_wol_magic_packet()
        # TODO(tbroch) There is evidence in the filesystem of the wake source
        # for coreboot but its still being flushed out.  For now only produce a
        # warning for this check.
        if not self._verify_wol_magic():
            logging.warning("Unable to see evidence of WOL wake in filesystem")
