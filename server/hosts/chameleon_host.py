# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#

"""This file provides core logic for connecting a Chameleon Daemon."""


from autotest_lib.client.bin import utils
from autotest_lib.client.cros.chameleon import chameleon
from autotest_lib.server.cros import dnsname_mangler
from autotest_lib.server.hosts import ssh_host


class ChameleonHost(ssh_host.SSHHost):
    """Host class for a host that controls a Chameleon."""

    # Chameleond process name.
    CHAMELEOND_PROCESS = 'chameleond'


    # TODO(waihong): Add verify and repair logic which are required while
    # deploying to Cros Lab.


    def _initialize(self, chameleon_host='localhost', chameleon_port=9992,
                    *args, **dargs):
        """Initialize a ChameleonHost instance.

        A ChameleonHost instance represents a host that controls a Chameleon.

        @param chameleon_host: Name of the host where the chameleond process
                               is running.
                               If this is passed in by IP address, it will be
                               treated as not in lab.
        @param chameleon_port: Port the chameleond process is listening on.

        """
        super(ChameleonHost, self)._initialize(hostname=chameleon_host,
                                               *args, **dargs)
        self._chameleon_connection = chameleon.ChameleonConnection(
                self.hostname, chameleon_port)

        self._is_in_lab = None
        self._check_if_is_in_lab()


    def _check_if_is_in_lab(self):
        """Checks if Chameleon host is in lab and set self._is_in_lab.

        If self.hostname is an IP address, we treat it as is not in lab zone.

        """
        self._is_in_lab = (False if dnsname_mangler.is_ip_address(self.hostname)
                           else utils.host_is_in_lab_zone(self.hostname))




    def is_in_lab(self):
        """Check whether the chameleon host is a lab device.

        @returns: True if the chameleon host is in Cros Lab, otherwise False.

        """
        return self._is_in_lab


    def get_wait_up_processes(self):
        """Get the list of local processes to wait for in wait_up.

        Override get_wait_up_processes in
        autotest_lib.client.common_lib.hosts.base_classes.Host.
        Wait for chameleond process to go up. Called by base class when
        rebooting the device.

        """
        processes = [self.CHAMELEOND_PROCESS]
        return processes


    def create_chameleon_board(self):
        """Create a ChameleonBoard object."""
        # TODO(waihong): Add verify and repair logic which are required while
        # deploying to Cros Lab.
        return chameleon.ChameleonBoard(self._chameleon_connection, self)


def create_chameleon_host(dut, chameleon_args):
    """Create a ChameleonHost object.

    There three possible cases:
    1) If the DUT is in Cros Lab and has a chameleon board, then create
       a ChameleonHost object pointing to the board. chameleon_args
       is ignored.
    2) If not case 1) and chameleon_args is neither None nor empty, then
       create a ChameleonHost object using chameleon_args.
    3) If neither case 1) or 2) applies, return None.

    @param dut: host name of the host that chameleon connects. It can be used
                to lookup the chameleon in test lab using naming convention.
                If dut is an IP address, it can not be used to lookup the
                chameleon in test lab.
    @param chameleon_args: A dictionary that contains args for creating
                           a ChameleonHost object,
                           e.g. {'chameleon_host': '172.11.11.112',
                                 'chameleon_port': 9992}.

    @returns: A ChameleonHost object or None.

    """
    dut_is_hostname = not dnsname_mangler.is_ip_address(dut)
    if dut_is_hostname:
        chameleon_hostname = chameleon.make_chameleon_hostname(dut)
        if utils.host_is_in_lab_zone(chameleon_hostname):
            return ChameleonHost(chameleon_host=chameleon_hostname)
    if chameleon_args:
        return ChameleonHost(**chameleon_args)
    else:
        return None
