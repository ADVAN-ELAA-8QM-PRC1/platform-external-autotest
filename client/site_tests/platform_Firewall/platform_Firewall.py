# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import dbus
import logging
import os
import time

from autotest_lib.client.bin import test, utils
from autotest_lib.client.common_lib import error


class platform_Firewall(test.test):
    """Ensure the firewall service is working correctly."""

    version = 1

    _PORT = 1234
    _TCP_RULE = "-A INPUT -p tcp -m tcp --dport %d -j ACCEPT" % _PORT
    _UDP_RULE = "-A INPUT -p udp -m udp --dport %d -j ACCEPT" % _PORT

    _POLL_INTERVAL = 5

    _IPTABLES_DEL_CMD = "iptables -D INPUT -p %s -m %s --dport %d -j ACCEPT"

    @staticmethod
    def _iptables_rules():
        rule_output = utils.system_output("iptables -S")
        logging.debug(rule_output)
        return [line.strip() for line in rule_output.splitlines()]


    def run_once(self):
        bus = dbus.SystemBus()
        pb_proxy = bus.get_object('org.chromium.PermissionBroker',
                                  '/org/chromium/PermissionBroker')
        pb = dbus.Interface(pb_proxy, 'org.chromium.PermissionBroker')

        self.tcp_r, self.tcp_w = os.pipe()
        self.udp_r, self.udp_w = os.pipe()

        try:
            tcp_lifeline = dbus.types.UnixFd(self.tcp_r)
            ret = pb.RequestTcpPortAccess(dbus.UInt16(self._PORT), tcp_lifeline)
            # |ret| is a dbus.Boolean, but compares as int.
            if ret == 0:
                raise error.TestFail(
                        "RequestTcpPortAccess returned false.")

            udp_lifeline = dbus.types.UnixFd(self.udp_r)
            ret = pb.RequestUdpPortAccess(dbus.UInt16(self._PORT), udp_lifeline)
            # |ret| is a dbus.Boolean, but compares as int.
            if (ret == 0):
                raise error.TestFail(
                        "RequestUdpPortAccess returned false.")

            rules = self._iptables_rules()
            if self._TCP_RULE not in rules:
                raise error.TestFail(
                        "RequestTcpPortAccess did not add iptables rule.")
            if self._UDP_RULE not in rules:
                raise error.TestFail(
                        "RequestUdpPortAccess did not add iptables rule.")

            # permission_broker should plug the firewall hole
            # when the requesting process exits.
            # Simulate the process exiting by closing both write ends.
            os.close(self.tcp_w)
            os.close(self.udp_w)

            # permission_broker checks every |_POLL_INTERVAL| seconds
            # for processes that have exited.
            # This is ugly, but it's either this or polling /var/log/messages.
            time.sleep(self._POLL_INTERVAL + 1)
            rules = self._iptables_rules()
            if self._TCP_RULE in rules or self._UDP_RULE in rules:
                raise error.TestFail(
                        "permission_broker did not remove iptables rule.")

        except dbus.DBusException as e:
            raise error.TestFail("D-Bus error: " + e.get_dbus_message())


    def cleanup(self):
        # File descriptors could already be closed.
        try:
            os.close(self.tcp_w)
            os.close(self.udp_w)
        except OSError:
            pass

        # We don't want the cleanup() method to fail, so we ignore exit codes.
        # This also allows us to clean up iptables rules unconditionally.
        # The command will fail if the rule has already been deleted,
        # but it won't fail the test.
        cmd = self._IPTABLES_DEL_CMD % ("tcp", "tcp", self._PORT)
        utils.system(cmd, ignore_status=True)
        cmd = self._IPTABLES_DEL_CMD % ("udp", "udp", self._PORT)
        utils.system(cmd, ignore_status=True)
