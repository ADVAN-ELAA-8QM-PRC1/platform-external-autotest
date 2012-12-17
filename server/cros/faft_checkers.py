# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import re
import logging

from autotest_lib.client.common_lib import error
from autotest_lib.server.cros import vboot_constants as vboot

class FAFTCheckers(object):
    """Class that contains FAFT checkers."""
    version = 1

    def __init__(self, faftsequence, faft_client):
        self.faftsequence = faftsequence
        self.faft_client = faft_client


    def _parse_crossystem_output(self, lines):
        """Parse the crossystem output into a dict.

        Args:
          lines: The list of crossystem output strings.

        Returns:
          A dict which contains the crossystem keys/values.

        Raises:
          error.TestError: If wrong format in crossystem output.

        >>> seq = FAFTSequence()
        >>> seq._parse_crossystem_output([ \
                "arch          = x86    # Platform architecture", \
                "cros_debug    = 1      # OS should allow debug", \
            ])
        {'cros_debug': '1', 'arch': 'x86'}
        >>> seq._parse_crossystem_output([ \
                "arch=x86", \
            ])
        Traceback (most recent call last):
            ...
        TestError: Failed to parse crossystem output: arch=x86
        >>> seq._parse_crossystem_output([ \
                "arch          = x86    # Platform architecture", \
                "arch          = arm    # Platform architecture", \
            ])
        Traceback (most recent call last):
            ...
        TestError: Duplicated crossystem key: arch
        """
        pattern = "^([^ =]*) *= *(.*[^ ]) *# [^#]*$"
        parsed_list = {}
        for line in lines:
            matched = re.match(pattern, line.strip())
            if not matched:
                raise error.TestError("Failed to parse crossystem output: %s"
                                      % line)
            (name, value) = (matched.group(1), matched.group(2))
            if name in parsed_list:
                raise error.TestError("Duplicated crossystem key: %s" % name)
            parsed_list[name] = value
        return parsed_list


    def crossystem_checker(self, expected_dict):
        """Check the crossystem values matched.

        Given an expect_dict which describes the expected crossystem values,
        this function check the current crossystem values are matched or not.

        Args:
          expected_dict: A dict which contains the expected values.

        Returns:
          True if the crossystem value matched; otherwise, False.
        """
        succeed = True
        lines = self.faft_client.system.run_shell_command_get_output(
                'crossystem')
        got_dict = self._parse_crossystem_output(lines)
        for key in expected_dict:
            if key not in got_dict:
                logging.info('Expected key "%s" not in crossystem result', key)
                succeed = False
                continue
            if isinstance(expected_dict[key], str):
                if got_dict[key] != expected_dict[key]:
                    logging.info("Expected '%s' value '%s' but got '%s'",
                                 key, expected_dict[key], got_dict[key])
                    succeed = False
            elif isinstance(expected_dict[key], tuple):
                # Expected value is a tuple of possible actual values.
                if got_dict[key] not in expected_dict[key]:
                    logging.info("Expected '%s' values %s but got '%s'",
                                 key, str(expected_dict[key]), got_dict[key])
                    succeed = False
            else:
                logging.info("The expected value of %s is neither a str nor a "
                             "dict: %s", key, str(expected_dict[key]))
                succeed = False
        return succeed


    def vdat_flags_checker(self, mask, value):
        """Check the flags from VbSharedData matched.

        This function checks the masked flags from VbSharedData using crossystem
        are matched the given value.

        Args:
          mask: A bitmask of flags to be matched.
          value: An expected value.

        Returns:
          True if the flags matched; otherwise, False.
        """
        lines = self.faft_client.system.run_shell_command_get_output(
                    'crossystem vdat_flags')
        vdat_flags = int(lines[0], 16)
        if vdat_flags & mask != value:
            logging.info("Expected vdat_flags 0x%x mask 0x%x but got 0x%x",
                         value, mask, vdat_flags)
            return False
        return True


    def ro_normal_checker(self, expected_fw=None, twostop=False):
        """Check the current boot uses RO boot.

        Args:
          expected_fw: A string of expected firmware, 'A', 'B', or
                       None if don't care.
          twostop: True to expect a TwoStop boot; False to expect a RO boot.

        Returns:
          True if the currect boot firmware matched and used RO boot;
          otherwise, False.
        """
        crossystem_dict = {'tried_fwb': '0'}
        if expected_fw:
            crossystem_dict['mainfw_act'] = expected_fw.upper()
        if self.faftsequence.check_ec_capability(suppress_warning=True):
            crossystem_dict['ecfw_act'] = ('RW' if twostop else 'RO')

        succeed = True
        if not self.vdat_flags_checker(vboot.VDAT_FLAG_LF_USE_RO_NORMAL,
                0 if twostop else vboot.VDAT_FLAG_LF_USE_RO_NORMAL):
            succeed = False
        if not self.crossystem_checker(crossystem_dict):
            succeed = False
        return succeed


    def dev_boot_usb_checker(self, dev_boot_usb=True):
        """Check the current boot is from a developer USB (Ctrl-U trigger).

        Args:
          dev_boot_usb: True to expect an USB boot;
                        False to expect an internal device boot.

        Returns:
          True if the currect boot device matched; otherwise, False.
        """
        return (self.crossystem_checker({'mainfw_type': 'developer'}) and
            self.faft_client.system.is_removable_device_boot() == dev_boot_usb)


    def root_part_checker(self, expected_part):
        """Check the partition number of the root device matched.

        Args:
          expected_part: A string containing the number of the expected root
                         partition.

        Returns:
          True if the currect root  partition number matched; otherwise, False.
        """
        part = self.faft_client.system.get_root_part()[-1]
        if self.faftsequence.ROOTFS_MAP[expected_part] != part:
            logging.info("Expected root part %s but got %s",
                         self.faftsequence.ROOTFS_MAP[expected_part], part)
            return False
        return True


    def ec_act_copy_checker(self, expected_copy):
        """Check the EC running firmware copy matches.

        Args:
          expected_copy: A string containing 'RO', 'A', or 'B' indicating
                         the expected copy of EC running firmware.

        Returns:
          True if the current EC running copy matches; otherwise, False.
        """
        lines = self.faft_client.system.run_shell_command_get_output(
                    'ectool version')
        pattern = re.compile("Firmware copy: (.*)")
        for line in lines:
            matched = pattern.match(line)
            if matched and matched.group(1) == expected_copy:
                return True
        return False
