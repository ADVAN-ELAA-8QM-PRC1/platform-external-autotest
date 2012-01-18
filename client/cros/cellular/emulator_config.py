# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Configure cellular data emulation setup."""
import logging, time

from autotest_lib.client.cros.cellular import base_station_8960, cellular
from autotest_lib.client.cros.cellular import ether_io_rf_switch
from autotest_lib.client.cros.cellular import prologix_scpi_driver, scpi

class Error(Exception):
    pass

def _CreateBaseStation(c):
    """Create a base station from a base station labconfig dictionary."""
    if c['type'] != '8960-prologix':
        raise KeyError('Could not configure basestation of type %s' % c['type'])

    adapter = c['gpib_adapter']
    s = scpi.Scpi(
        prologix_scpi_driver.PrologixScpiDriver(
            hostname=adapter['address'],
            port=adapter['ip_port'],
            gpib_address=adapter['gpib_address']))
    return base_station_8960.BaseStation8960(s)


def _CreateRfSwitch(config):
    if 'rf_switch' not in config.cell:
        return None
    switch_config = config.cell['rf_switch']
    if switch_config['type'] != 'ether_io':
        raise KeyError('Could not configure switch of type %s' %
                       switch_config['type'])
    return ether_io_rf_switch.RfSwitch(switch_config['address'])


def StartDefault(config, technology):
    """Set up a base station and turn it on.  Return BS and verifier."""
    if len(config.cell['basestations']) > 1:
        raise Error('Cannot (yet) handle >1 base station')

    c = config.cell['basestations'][0]
    bs = _CreateBaseStation(c)

    rf_switch = _CreateRfSwitch(config)
    if rf_switch:
        port = config.get_rf_switch_port()
        logging.info(
            'Changing switch port from %s to %s' % (rf_switch.Query(), port))
        rf_switch.SelectPort(port)

    with bs.checker_context:
        bs.SetBsNetmaskV4(c['bs_netmask'])
        bs.SetBsIpV4(*c['bs_addresses'])

        bs.SetUeIpV4(*c['ue_rf_addresses'])
        bs.SetUeDnsV4(*c['ue_dns_addresses'])

        bs.SetTechnology(technology)
        bs.SetPower(-40)
        verifier = bs.GetAirStateVerifier()
        bs.Start()

    # TODO(rochberg):  Why does this seem to be necessary?
    time.sleep(5)

    return (bs, verifier)
