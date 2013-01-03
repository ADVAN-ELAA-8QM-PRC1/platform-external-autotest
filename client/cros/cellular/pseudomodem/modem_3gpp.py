# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import connect_machine
import dbus
import dbus.types
import disconnect_machine
import gobject
import logging
import mm1
import modem
import pseudomodem

class Modem3gpp(modem.Modem):
    """
    Pseudomodem implementation of the
    org.freedesktop.ModemManager1.Modem.Modem3gpp and
    org.freedesktop.ModemManager1.Modem.Simple interfaces. This class provides
    access to specific actions that may be performed in modems with 3GPP
    capabilities.

    """

    class GsmNetwork(object):
        def __init__(self,
                     operator_long,
                     operator_short,
                     operator_code,
                     status,
                     access_technology):
            self.status = status
            self.operator_long = operator_long
            self.operator_short = operator_short
            self.operator_code = operator_code
            self.access_technology = access_technology

    def _InitializeProperties(self):
        ip = modem.Modem._InitializeProperties(self)
        ip[mm1.I_MODEM_3GPP] = {
            'Imei' : '00112342342',
            'RegistrationState' : (
                dbus.types.UInt32(mm1.MM_MODEM_3GPP_REGISTRATION_STATE_IDLE)),
            'OperatorCode' : '',
            'OperatorName' : '',
            'EnabledFacilityLocks' : (
                dbus.types.UInt32(mm1.MM_MODEM_3GPP_FACILITY_NONE))
        }

        props = ip[mm1.I_MODEM]
        props['ModemCapabilities'] = dbus.types.UInt32(
            mm1.MM_MODEM_CAPABILITY_GSM_UMTS | mm1.MM_MODEM_CAPABILITY_LTE)
        props['CurrentCapabilities'] = dbus.types.UInt32(
            mm1.MM_MODEM_CAPABILITY_GSM_UMTS | mm1.MM_MODEM_CAPABILITY_LTE)
        props['MaxBearers'] = dbus.types.UInt32(3)
        props['MaxActiveBearers'] = dbus.types.UInt32(2)
        props['EquipmentIdentifier'] = ip[mm1.I_MODEM_3GPP]['Imei']
        props['AccessTechnologies'] = dbus.types.UInt32((
                mm1.MM_MODEM_ACCESS_TECHNOLOGY_GSM |
                mm1.MM_MODEM_ACCESS_TECHNOLOGY_UMTS))
        props['SupportedModes'] = dbus.types.UInt32(mm1.MM_MODEM_MODE_ANY)
        props['AllowedModes'] = props['SupportedModes']
        props['PreferredMode'] = dbus.types.UInt32(mm1.MM_MODEM_MODE_NONE)
        props['SupportedBands'] = [
            dbus.types.UInt32(mm1.MM_MODEM_BAND_EGSM),
            dbus.types.UInt32(mm1.MM_MODEM_BAND_DCS),
            dbus.types.UInt32(mm1.MM_MODEM_BAND_PCS),
            dbus.types.UInt32(mm1.MM_MODEM_BAND_G850),
            dbus.types.UInt32(mm1.MM_MODEM_BAND_U2100),
            dbus.types.UInt32(mm1.MM_MODEM_BAND_U1800),
            dbus.types.UInt32(mm1.MM_MODEM_BAND_U17IV),
            dbus.types.UInt32(mm1.MM_MODEM_BAND_U800),
            dbus.types.UInt32(mm1.MM_MODEM_BAND_U850)
        ]
        props['Bands'] = [
            dbus.types.UInt32(mm1.MM_MODEM_BAND_EGSM),
            dbus.types.UInt32(mm1.MM_MODEM_BAND_DCS),
            dbus.types.UInt32(mm1.MM_MODEM_BAND_PCS),
            dbus.types.UInt32(mm1.MM_MODEM_BAND_G850),
            dbus.types.UInt32(mm1.MM_MODEM_BAND_U2100),
            dbus.types.UInt32(mm1.MM_MODEM_BAND_U800),
            dbus.types.UInt32(mm1.MM_MODEM_BAND_U850)
        ]
        return ip

    def SetRegistrationState(self, state):
        self.SetUInt32(
            mm1.I_MODEM_3GPP, 'RegistrationState', dbus.types.UInt32(state))

    class RegisterStep(modem.Modem.StateMachine):
        def Step(self, *args):
            if self.cancelled:
                self.modem.register_step = None
                return

            state = self.modem.Get(mm1.I_MODEM, 'State')
            if self.modem.register_step and self.modem.register_step != self:
                logging.info('There is an ongoing Register operation.')
                raise mm1.MMCoreError(mm1.MMCoreError.IN_PROGRESS,
                        'Register operation already in progress.')
            elif not self.modem.register_step:
                if state == mm1.MM_MODEM_STATE_ENABLED:
                    logging.info('Starting Register.')
                    self.modem.register_step = self
                else:
                    message = ('Cannot initiate register while in state %d, '
                               'state needs to be ENABLED.') % state
                    raise mm1.MMCoreError(mm1.MMCoreError.WRONG_STATE, message)

            reason = mm1.MM_MODEM_STATE_CHANGE_REASON_USER_REQUESTED

            if state == mm1.MM_MODEM_STATE_ENABLED:
                logging.info('RegisterStep: Modem is ENABLED.')
                logging.info('RegisterStep: Setting registration state '
                             'to SEARCHING.')
                self.modem.SetRegistrationState(
                    mm1.MM_MODEM_3GPP_REGISTRATION_STATE_SEARCHING)
                logging.info('RegisterStep: Setting state to SEARCHING.')
                self.modem.ChangeState(mm1.MM_MODEM_STATE_SEARCHING, reason)
                logging.info('RegisterStep: Starting network scan.')
                try:
                    networks = self.modem.Scan()
                except:
                    self.modem.register_step = None
                    logging.info('An error occurred during Scan.')
                    self.modem.ChangeState(mm1.MM_MODEM_STATE_ENABLED,
                        mm1.MODEM_STATE_CHANGE_REASON_UNKNOWN)
                    raise
                logging.info('RegisterStep: Found networks: ' + str(networks))
                gobject.idle_add(Modem3gpp.RegisterStep.Step, self, networks)
            elif state == mm1.MM_MODEM_STATE_SEARCHING:
                logging.info('RegisterStep: Modem is SEARCHING.')
                assert len(args) == 1
                networks = args[0]
                if not networks:
                    logging.info('RegisterStep: Scan returned no networks.')
                    logging.info('RegisterStep: Setting state to ENABLED.')
                    self.modem.ChangeState(mm1.MM_MODEM_STATE_ENABLED,
                        mm1.MM_MODEM_STATE_CHANGE_REASON_UNKNOWN)
                    # TODO(armansito): Figure out the correct registration
                    # state to transition to when no network is present.
                    logging.info(('RegisterStep: Setting registration state '
                                  'to IDLE.'))
                    self.modem.SetRegistrationState(
                        mm1.MM_MODEM_3GPP_REGISTRATION_STATE_IDLE)
                    self.modem.register_step = None
                    raise mm1.MMMobileEquipmentError(
                        mm1.MMMobileEquipmentError.NO_NETWORK,
                        'No networks were found to register.')
                else:
                    # For now pick the first network in the list.
                    # Roaming networks will come before the home
                    # network, so if the test provided any roaming
                    # networks, we will register with the first one.
                    # TODO(armansito): Could the operator-code not be
                    # present or unknown?
                    logging.info(('RegisterStep: Registering to network: ' +
                        str(networks[0])))
                    self.modem.Register(networks[0]['operator-code'],
                        networks[0]['operator-long'])

                    # Modem3gpp.Register() should have set the state to
                    # REGISTERED.
                    self.modem.register_step = None

    @dbus.service.method(mm1.I_MODEM_3GPP, in_signature='s')
    def Register(self, operator_id, *args):
        """
        Request registration with a given modem network.

        Args:
            operator_id -- The operator ID to register. An empty string can be
                           used to register to the home network.
            *args -- Args can optionally contain an operator name.

        """
        logging.info('Modem3gpp.Register: %s', operator_id)
        if operator_id:
            assert self.sim
            assert self.Get(mm1.I_MODEM, 'Sim') != mm1.ROOT_PATH
            if operator_id == self.sim.Get(mm1.I_SIM, 'OperatorIdentifier'):
                state = mm1.MM_MODEM_3GPP_REGISTRATION_STATE_HOME
            else:
                state = mm1.MM_MODEM_3GPP_REGISTRATION_STATE_ROAMING
        else:
            state = mm1.MM_MODEM_3GPP_REGISTRATION_STATE_HOME

        logging.info('Modem3gpp.Register: Setting registration state to %s.',
            mm1.RegistrationStateToString(state))
        self.SetRegistrationState(state)
        logging.info('Modem3gpp.Register: Setting state to REGISTERED.')
        self.ChangeState(mm1.MM_MODEM_STATE_REGISTERED,
            mm1.MM_MODEM_STATE_CHANGE_REASON_USER_REQUESTED)
        self.Set(mm1.I_MODEM_3GPP, 'OperatorCode', operator_id)
        if args:
            self.Set(mm1.I_MODEM_3GPP, 'OperatorName', args[0])

    @dbus.service.method(mm1.I_MODEM_3GPP, out_signature='aa{sv}')
    def Scan(self):
        """
        Scan for available networks.

        Returns:
            An array of dictionaries with each array element describing a
            mobile network found in the scan. See the ModemManager reference
            manual for the list of keys that may be included in the returned
            dictionary.

        """
        state = self.Get(mm1.I_MODEM, 'State')
        if state < mm1.MM_MODEM_STATE_ENABLED:
            raise mm1.MMCoreError(mm1.MMCoreError.WRONG_STATE,
                    'Modem not enabled, cannot scan for networks.')

        sim_path = self.Get(mm1.I_MODEM, 'Sim')
        if not self.sim:
            assert sim_path == mm1.ROOT_PATH
            raise mm1.MMMobileEquipmentError(
                mm1.MMMobileEquipmentError.SIM_NOT_INSERTED,
                'Cannot scan for networks because no SIM is inserted.')
        assert sim_path != mm1.ROOT_PATH

        # TODO(armansito): check here for SIM lock?

        scanned = [network.__dict__ for network in self.roaming_networks]

        # get home network
        sim_props = self.sim.GetAll(mm1.I_SIM)
        scanned.append({
            'status': mm1.MM_MODEM_3GPP_NETWORK_AVAILABILITY_AVAILABLE,
            'operator-long': sim_props['OperatorName'],
            'operator-short': sim_props['OperatorName'],
            'operator-code': sim_props['OperatorIdentifier'],
            'access-technology': self.sim.access_technology
        })
        return scanned

    def RegisterWithNetwork(self):
        Modem3gpp.RegisterStep(self).Step()

    def UnregisterWithNetwork(self):
        logging.info('Modem3gpp.UnregisterWithHomeNetwork')
        logging.info('Setting registration state to IDLE.')
        self.SetRegistrationState(mm1.MM_MODEM_3GPP_REGISTRATION_STATE_IDLE)
        logging.info('Setting state to ENABLED.')
        self.ChangeState(mm1.MM_MODEM_STATE_ENABLED,
            mm1.MM_MODEM_STATE_CHANGE_REASON_USER_REQUESTED)
        self.Set(mm1.I_MODEM_3GPP, 'OperatorName', '')
        self.Set(mm1.I_MODEM_3GPP, 'OperatorCode', '')

    def Connect(self, properties, return_cb, raise_cb):
        logging.info('Connect')
        connect_machine.ConnectMachine(
            self, properties, return_cb, raise_cb).Step()

    def Disconnect(self, bearer_path, return_cb, raise_cb, *return_cb_args):
        logging.info('Disconnect: %s' % bearer_path)
        disconnect_machine.DisconnectMachine(
            self, bearer_path, return_cb, raise_cb, return_cb_args).Step()

    def GetStatus(self):
        modem_props = self.GetAll(mm1.I_MODEM)
        m3gpp_props = self.GetAll(mm1.I_MODEM_3GPP)
        retval = {}
        retval['state'] = modem_props['State']
        if retval['state'] == mm1.MM_MODEM_STATE_REGISTERED:
            retval['signal-quality'] = modem_props['SignalQuality'][0]
            retval['bands'] = modem_props['Bands']
            retval['access-technology'] = self.sim.access_technology
            retval['m3gpp-registration-state'] = \
                m3gpp_props['RegistrationState']
            retval['m3gpp-operator-code'] = m3gpp_props['OperatorCode']
            retval['m3gpp-operator-name'] = m3gpp_props['OperatorName']
        return retval
    # TODO(armansito): implement
    # org.freedesktop.ModemManager1.Modem.Modem3gpp.Ussd, if needed
    # (in a separate class?)
