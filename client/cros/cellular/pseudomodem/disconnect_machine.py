# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import mm1
import state_machine

class DisconnectMachine(state_machine.StateMachine):
    """
    DisconnectMachine handles the state transitions involved in bringing the
    modem to the DISCONNECTED state.

    """
    def __init__(self, modem, bearer_path, return_cb, raise_cb,
        return_cb_args=[]):
        super(DisconnectMachine, self).__init__(modem)
        self.bearer_path = bearer_path
        self.return_cb = return_cb
        self.raise_cb = raise_cb
        self.return_cb_args = return_cb_args

    def _HandleConnectedState(self):
        logging.info('DisconnectMachine: Modem state is CONNECTED.')
        logging.info('DisconnectMachine: Setting state to DISCONNECTING.')
        reason = mm1.MM_MODEM_STATE_CHANGE_REASON_USER_REQUESTED
        self._modem.ChangeState(mm1.MM_MODEM_STATE_DISCONNECTING, reason)
        return True

    def _HandleDisconnectingState(self):
        logging.info('DisconnectMachine: Modem state is DISCONNECTING.')
        assert not self._modem.IsPendingConnect()
        assert not self._modem.IsPendingEnable()
        assert not self._modem.IsPendingRegister()
        assert self._modem.active_bearers
        assert self._modem.bearers

        dc_reason = mm1.MM_MODEM_STATE_CHANGE_REASON_USER_REQUESTED
        try:
            if self.bearer_path == mm1.ROOT_PATH:
                for bearer in self._modem.active_bearers.keys():
                    self._modem.DeactivateBearer(bearer)
            else:
                self._modem.DeactivateBearer(self.bearer_path)
        except mm1.MMError as e:
            logging.error('DisconnectMachine: Failed to disconnect: ' + str(e))
            dc_reason = mm1.MM_MODEM_STATE_CHANGE_REASON_UNKNOWN
            self.raise_cb(e)
        finally:
            # TODO(armansito): What should happen in a disconnect
            # failure? Should we stay connected or become REGISTERED?
            logging.info('DisconnectMachine: Setting state to REGISTERED.')
            self._modem.ChangeState(mm1.MM_MODEM_STATE_REGISTERED,
                dc_reason)
            self._modem.disconnect_step = None
            logging.info('DisconnectMachine: Calling return callback.')
            self.return_cb(*self.return_cb_args)
            return False

    def _GetModemStateFunctionMap(self):
        return {
            mm1.MM_MODEM_STATE_CONNECTED:
                DisconnectMachine._HandleConnectedState,
            mm1.MM_MODEM_STATE_DISCONNECTING:
                DisconnectMachine._HandleDisconnectingState
        }

    def _ShouldStartStateMachine(self):
        if (self._modem.disconnect_step and
            # There is already a disconnect operation in progress.
            self._modem.disconnect_step != self):
            message = 'There is already an ongoing disconnect operation.'
            logging.error(message)
            self.raise_cb(
                mm1.MMCoreError(mm1.MMCoreError.IN_PROGRESS, message))
            return False
        elif self._modem.disconnect_step is None:
            # There is no disconnect operation going on, canceled or otherwise.
            state = self._modem.Get(mm1.I_MODEM, 'State')
            if state != mm1.MM_MODEM_STATE_CONNECTED:
                message = 'Modem cannot be disconnected when not connected.'
                logging.error(message)
                self.raise_cb(
                    mm1.MMCoreError(mm1.MMCoreError.WRONG_STATE, message))
                return False

            assert self._modem.bearers
            assert self._modem.active_bearers

            if self.bearer_path == mm1.ROOT_PATH:
                logging.info('All bearers will be disconnected.')
            elif not (self.bearer_path in self._modem.bearers):
                message = ('Bearer with path "%s" not found' %
                           self.bearer_path)
                logging.error(message)
                self.raise_cb(
                    mm1.MMCoreError(mm1.MMCoreError.NOT_FOUND, message))
                return False
            elif not (self.bearer_path in self._modem.active_bearers):
                message = ('No active bearer with path ' +
                    self.bearer_path +
                    ' found, current active bearers are ' +
                    str(self._modem.active_bearers))
                logging.error(message)
                self.raise_cb(mm1.MMCoreError(
                    mm1.MMCoreError.NOT_FOUND, message))
                return False

            assert not self._modem.IsPendingConnect()
            assert not self._modem.IsPendingEnable()
            assert not self._modem.IsPendingRegister()

            logging.info('Starting Disconnect.')
            self._modem.disconnect_step = self
        return True
