# Copyright (c) 2012 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""File containing class to build all available ap_configurators."""

import logging

from autotest_lib.server.cros.chaos_ap_configurators import ap_cartridge
from autotest_lib.server.cros.chaos_ap_configurators import ap_configurator
from autotest_lib.server.cros.chaos_config import ChaosAPList

import asus_ap_configurator
import asus_ac66r_ap_configurator
import asus_qis_ap_configurator
import belkin_ap_configurator
import belkinF9K_ap_configurator
import buffalo_ap_configurator
import buffalo_wzr_d1800h_ap_configurator
import dlink_ap_configurator
import dlink_dir655_ap_configurator
import dlinkwbr1310_ap_configurator
import linksys_ap_configurator
import linksys_ap_15_configurator
import linksyse_dual_band_configurator
import linksyse_single_band_configurator
import linksyse1000_ap_configurator
import linksyse2000_ap_configurator
import linksyse2100_ap_configurator
import linksyse2500_ap_configurator
import linksyswrt160_ap_configurator
import medialink_ap_configurator
import netgear3700_ap_configurator
import netgear4300_ap_configurator
import netgearR6200_ap_configurator
import netgear1000_ap_configurator
import netgear2000_ap_configurator
import netgear_WNDR_dual_band_configurator
import netgear_single_band_configurator
import trendnet_ap_configurator
import trendnet691gr_ap_configurator
import trendnet731br_ap_configurator
import westerndigitaln600_ap_configurator


class APConfiguratorFactory(object):
    """Class that instantiates all available APConfigurators.

    @attribute CONFIGURATOR_MAP: a dict of strings, mapping to model-specific
                                 APConfigurator objects.
    @attribute BANDS: a string, bands supported by an AP.
    @attribute MODES: a string, 802.11 modes supported by an AP.
    @attribute SECURITIES: a string, security methods supported by an AP.
    @attribute ap_list: a list of APConfigurator objects.
    @attribute generic_ap: a generic APConfigurator object.
    @attribute valid_modes: a set of hex numbers.
    @attribute valid_securities: a set of strings.
    @attribute valid_bands: a set of strings.
    """

    CONFIGURATOR_MAP = {
        'LinksysAPConfigurator':
            linksys_ap_configurator.LinksysAPConfigurator,
        'LinksysAP15Configurator':
            linksys_ap_15_configurator.LinksysAP15Configurator,
        'DLinkAPConfigurator':
            dlink_ap_configurator.DLinkAPConfigurator,
        'TrendnetAPConfigurator':
            trendnet_ap_configurator.TrendnetAPConfigurator,
        'Trendnet691grAPConfigurator':
            trendnet691gr_ap_configurator.Trendnet691grAPConfigurator,
        'Trendnet731brAPConfigurator':
            trendnet731br_ap_configurator.Trendnet731brAPConfigurator,
        'DLinkDIR655APConfigurator':
            dlink_dir655_ap_configurator.DLinkDIR655APConfigurator,
        'BuffaloAPConfigurator':
            buffalo_ap_configurator.BuffaloAPConfigurator,
        'BuffalowzrAPConfigurator':
            buffalo_wzr_d1800h_ap_configurator.BuffalowzrAPConfigurator,
        'AsusAPConfigurator':
            asus_ap_configurator.AsusAPConfigurator,
        'AsusQISAPConfigurator':
            asus_qis_ap_configurator.AsusQISAPConfigurator,
        'Asus66RAPConfigurator':
            asus_ac66r_ap_configurator.Asus66RAPConfigurator,
        'Netgear3700APConfigurator':
            netgear3700_ap_configurator.Netgear3700APConfigurator,
        'NetgearR6200APConfigurator':
            netgearR6200_ap_configurator.NetgearR6200APConfigurator,
        'Netgear1000APConfigurator':
            netgear1000_ap_configurator.Netgear1000APConfigurator,
        'Netgear2000APConfigurator':
            netgear2000_ap_configurator.Netgear2000APConfigurator,
        'Netgear4300APConfigurator':
            netgear4300_ap_configurator.Netgear4300APConfigurator,
        'LinksyseDualBandAPConfigurator':
            linksyse_dual_band_configurator.LinksyseDualBandAPConfigurator,
        'Linksyse2000APConfigurator':
            linksyse2000_ap_configurator.Linksyse2000APConfigurator,
        'NetgearDualBandAPConfigurator':
            netgear_WNDR_dual_band_configurator.NetgearDualBandAPConfigurator,
        'BelkinAPConfigurator':
            belkin_ap_configurator.BelkinAPConfigurator,
        'BelkinF9KAPConfigurator':
            belkinF9K_ap_configurator.BelkinF9KAPConfigurator,
        'MediaLinkAPConfigurator':
            medialink_ap_configurator.MediaLinkAPConfigurator,
        'NetgearSingleBandAPConfigurator':
            netgear_single_band_configurator.NetgearSingleBandAPConfigurator,
        'DLinkwbr1310APConfigurator':
            dlinkwbr1310_ap_configurator.DLinkwbr1310APConfigurator,
        'Linksyse2100APConfigurator':
            linksyse2100_ap_configurator.Linksyse2100APConfigurator,
        'LinksyseSingleBandAPConfigurator':
            linksyse_single_band_configurator.LinksyseSingleBandAPConfigurator,
        'Linksyse2500APConfigurator':
            linksyse2500_ap_configurator.Linksyse2500APConfigurator,
        'WesternDigitalN600APConfigurator':
            westerndigitaln600_ap_configurator.WesternDigitalN600APConfigurator,
        'Linksyse1000APConfigurator':
            linksyse1000_ap_configurator.Linksyse1000APConfigurator,
        'LinksysWRT160APConfigurator':
            linksyswrt160_ap_configurator.LinksysWRT160APConfigurator,
    }

    BANDS = 'bands'
    MODES = 'modes'
    SECURITIES = 'securities'


    def __init__(self):
        chaos_config = ChaosAPList(static_config=False)

        self.ap_list = []
        for ap in chaos_config:
            configurator = self.CONFIGURATOR_MAP[ap.get_class()]
            self.ap_list.append(configurator(ap_config=ap))

        # Used to fetch AP attributes such as bands, modes, securities
        self.generic_ap = ap_configurator.APConfigurator()
        # All possible values for 802.11 mode
        self.valid_modes = set([
            self.generic_ap.mode_a,
            self.generic_ap.mode_auto,
            self.generic_ap.mode_b,
            self.generic_ap.mode_d,
            self.generic_ap.mode_g,
            self.generic_ap.mode_m,
            self.generic_ap.mode_n,
            ])
        # All possible values for security method
        self.valid_securities = set([
            self.generic_ap.security_type_disabled,
            self.generic_ap.security_type_wep,
            self.generic_ap.security_type_wpapsk,
            self.generic_ap.security_type_wpa2psk,
            ])
        # All possible values for bands
        self.valid_bands = set([
            self.generic_ap.band_2ghz,
            self.generic_ap.band_5ghz,
            ])


    def get_ap_configurators(self, spec=None):
        """Returns available configurators meeting spec.

        Caller may request APs based on the following attributes:
         - BANDS, a list of strings, bands supported.
         - MODES, a list of hex numbers, 802.11 modes supported.
         - SECURITIES, a list of strings, security methods supported.

        Interpretation rules:
         - if an attribute is not present in spec, it's not used to select APs.
         - caller should only specify an attribute s/he cares about testing.
         - in case of a list of (>1) strings, logical AND is applied, e.g.
           dual-band (2.4GHz AND 5GHz).
         - if multiple attributes are specified, logical AND is applied.
           Evaluation order is securities, then bands, then modes (which could
           depend on bands as input).

        Sample spec values and expected returns:
        1. spec = None or empty dict
           Return all APs
        2. spec = dict(bands=['2.4GHz', '5GHz'])
           Return all dual-band APs
        3. spec = dict(modes=[0x00010, 0x00100], securities=[2])
           Return all APs which support both 802.11b AND 802.11g modes AND
           PSK security

        @param spec: a dict of AP attributes, see explanation above.
        @returns aps: a list of APConfigurator objects. Or None.
        """
        aps = self.ap_list
        if not spec:
            logging.info('No spec included, return all APs')
            return aps

        securities = spec.get(self.SECURITIES, None)
        bands = spec.get(self.BANDS, None)
        modes = spec.get(self.MODES, None)

        if securities:
            logging.info('Select APs by securities: %r', securities)
            aps = self._get_aps_with_securities(securities, aps)
        if aps and bands:
            logging.info('Select APs by bands: %r', bands)
            aps = self._get_aps_with_bands(bands, aps)
        if aps and modes:
            logging.info('Select APs by modes: %r', modes)
            aps = self._get_aps_with_modes(modes, aps)

        return aps


    def _cleanup_ap_spec(self, key, value):
        """Validates AP attribute.

        @param key: a string, one of BANDS, SECURITIES or MODES.
        @param value: a list of strings, values of key.

        @returns a list of strings, valid values for key. Or None.
        """
        attr_dict = {
            self.BANDS: self.valid_bands,
            self.MODES: self.valid_modes,
            self.SECURITIES: self.valid_securities,
            }

        invalid_value = set(value).difference(attr_dict[key])
        if invalid_value:
            logging.warning('Ignored invalid %s: %r', key, invalid_value)
            value = list(set(value) - invalid_value)
            logging.info('Remaining valid value for %s = %r', key, value)

        return value


    def _get_aps_with_modes(self, modes, ap_list):
        """Returns all configurators that support a given 802.11 mode.

        @param mode: a list of hex numbers, 802.11 modes. Valid values in
                     self.valid_modes.
        @param ap_list: a list of APConfigurator objects.

        @returns aps: a list of APs. Or None.
        """
        modes = self._cleanup_ap_spec(self.MODES, modes)
        if not modes:
            logging.warning('No valid modes found.')
            return None

        aps = []
        for ap in ap_list:
            bands_and_modes = ap.get_supported_modes()
            # FIXME(tgao): would mixing modes across bands cause any issue?
            ap_modes = set()
            for d in bands_and_modes:
                if self.MODES in d:
                    ap_modes = ap_modes.union(set(d[self.MODES]))
            if set(modes).issubset(ap_modes):
                logging.debug('Found ap by mode = %r', ap.host_name)
                aps.append(ap)
        return aps


    def _get_aps_with_securities(self, securities, ap_list):
        """Returns all configurators that support a given security mode.

        @param securities: a list of integers, security mode. Valid values in
                           self.valid_securities.
        @param ap_list: a list of APConfigurator objects.

        @returns aps: a list of APs. Or None.
        """
        securities = self._cleanup_ap_spec(self.SECURITIES, securities)
        if not securities:
            logging.warning('No valid security found.')
            return None

        aps = []
        for ap in ap_list:
            for security in securities:
                if not ap.is_security_mode_supported(security):
                    break
            else:  # ap supports all securities
                logging.debug('Found ap by security = %r', ap.host_name)
                aps.append(ap)
        return aps


    def _get_aps_with_bands(self, bands, ap_list):
        """Returns all APs that support bands.

        @param bands: a list of strings, bands supported. Valid values in
                      self.valid_bands.
        @param ap_list: a list of APConfigurator objects.

        @returns aps: a list of APs. Or None.
        """
        bands = self._cleanup_ap_spec(self.BANDS, bands)
        if not bands:
            logging.warning('No valid bands found.')
            return None

        aps = []
        for ap in ap_list:
            bands_and_channels = ap.get_supported_bands()
            ap_bands = [d['band'] for d in bands_and_channels if 'band' in d]
            if set(bands).issubset(set(ap_bands)):
                logging.debug('Found ap by band = %r', ap.host_name)
                aps.append(ap)
        return aps


    def turn_off_all_routers(self):
        """Powers down all of the routers."""
        ap_power_cartridge = ap_cartridge.APCartridge()
        for ap in self.ap_list:
            ap.power_down_router()
            ap_power_cartridge.push_configurator(ap)
        ap_power_cartridge.run_configurators()
