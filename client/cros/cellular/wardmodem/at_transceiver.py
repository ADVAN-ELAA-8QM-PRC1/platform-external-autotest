# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import collections
import inspect
import logging
import os
import sys

import at_channel
import task_loop
import wardmodem_exceptions

MODEM_RESPONSE_TIMEOUT_MILLISECONDS = 30000
DEFAULT_AT_TO_WARDMODEM_CONF = 'base_at_to_wardmodem.conf'

class ATTransceiverMode(object):
    """
    Enum to specify what mode the ATTransceiver is operating in.

    There are three modes. These modes determine how the commands to/from
    the modemmanager are routed.
        WARDMODEM:  modemmanager interacts with wardmodem alone.
        SPLIT_VERIFY: modemmanager commands are sent to both the wardmodem
                and the physical modem on the device. Responses from
                wardmodem are verified against responses from the physical
                modem. In case of a mismatch, wardmodem's response is
                chosen, and a warning is issued.
        PASS_THROUGH: modemmanager commands are routed to/from the physical
                modem. Frankly, wardmodem isn't running in this mode.

    """
    WARDMODEM = 0
    SPLIT_VERIFY = 1
    PASS_THROUGH = 2

    MODE_NAME = {
            WARDMODEM: 'WARDMODEM',
            SPLIT_VERIFY: 'SPLIT_VERIFY',
            PASS_THROUGH: 'PASS_THROUGH'
    }


    @classmethod
    def to_string(cls, value):
        """
        A class method to obtain string representation of the enum values.

        @param value: the enum value to stringify.

        """
        return "%s.%s" % (cls.__name__, cls.MODE_NAME[value])


class ATTransceiver(object):
    """
    A world facing multiplexer class that orchestrates the communication between
    modem manager, the physical modem, and wardmodem back-end.

    """

    def __init__(self, mm_at_port, plugin_at_to_wardmodem_conf=None,
                 modem_at_port=None):
        """
        @param mm_at_port: File descriptor for AT port used by modem manager.
                Can not be None.

        @param plugin_at_to_wardmodem_conf: Path to file that overrides
                the default map from AT commands to wardmodem actions.

        @param modem_at_port: File descriptor for AT port used by the modem. May
                be None, but that forces ATTransceiverMode.WARDMODEM. Default:
                None.

        """
        super(ATTransceiver, self).__init__()
        assert mm_at_port is not None

        self._logger = logging.getLogger(__name__)
        self._task_loop = task_loop.get_instance()
        self._mode = ATTransceiverMode.WARDMODEM
        # The time we wait for any particular response from physical modem.
        self._modem_response_timeout_milliseconds = (
                MODEM_RESPONSE_TIMEOUT_MILLISECONDS)
        # We keep a queue of responses from the wardmodem and physical modem,
        # so that we can verify they match.
        self._cached_modem_responses = collections.deque()
        self._cached_wardmodem_responses = collections.deque()

        # When a wardmodem response has been received but the corresponding
        # physical modem response hasn't arrived, we post a task to wait for the
        # response.
        self._modem_response_wait_task = None

        # We use a map from a set of well known state machine names to actual
        # objects to dispatch state machine calls. This allows tests to provide
        # alternative implementations of any state machine to wardmodem.
        self._state_machines = {}

        # Load configuration files
        self._at_to_wardmodem = {}
        conf = {}
        conf = self._load_conf_file(DEFAULT_AT_TO_WARDMODEM_CONF)
        self._update_at_to_wardmodem(conf['at_to_wardmodem'])
        if plugin_at_to_wardmodem_conf is not None:
            conf = self._load_conf_file(plugin_at_to_wardmodem_conf)
            self._update_at_to_wardmodem(conf['at_to_wardmodem'])
        self._logger.debug('Finished loading AT --> wardmodem configuration.')
        self._logger.debug(self._at_to_wardmodem)

        # Initialize channels -- let the session begin.
        if modem_at_port is not None:
            self._modem_channel = at_channel.ATChannel(
                    self._process_modem_at_command,
                    modem_at_port,
                    'modem_primary_channel')
        else:
            self._modem_channel = None

        self._mm_channel = at_channel.ATChannel(self._process_mm_at_command,
                                                mm_at_port,
                                                'mm_primary_channel')


    # Verification failure reasons
    VERIFICATION_FAILED_MISMATCH = 1
    VERIFICATION_FAILED_TIME_OUT = 2


    @property
    def mode(self):
        """
        ATTranscieverMode value. Determines how commands are routed.

        @see ATTransceiverMode

        """
        return self._mode


    @mode.setter
    def mode(self, value):
        """
        Set mode.

        @param value: The value to set. Type: ATTransceiverMode.

        """
        if value != ATTransceiverMode.WARDMODEM and self._modem_channel is None:
            self._logger.warning(
                    'Can not switch to %s mode. No modem port provided.',
                    ATTransceiverMode.to_string(value))
            return
        self._logger.info('Set mode to %s',
                          ATTransceiverMode.to_string(value))
        self._mode = value


    @property
    def at_terminator(self):
        """
        The string used to terminate AT commands sent / received on the channel.

        Default value: '\r\n'
        """
        return self._mm_channel.at_terminator

    @at_terminator.setter
    def at_terminator(self, value):
        """
        Set the string to use to terminate AT commands.

        This can vary by the modem being used.

        @param value: The string terminator.

        """
        assert self._mm_channel
        self._mm_channel.at_terminator = value
        if self._modem_channel:
            self._modem_channel.at_terminator = value


    def register_state_machine(self, state_machine):
        """
        Register a new state machine.

        We maintain a map from the well known name of the state machine to the
        object. Any older object mapped to the same name will be replaced.

        @param state_machine: [StateMachine object] The state machine
                object to be used to dispatch calls.

        """
        state_machine_name = state_machine.get_well_known_name()
        self._state_machines[state_machine_name] = state_machine

    def process_wardmodem_response(self, response, *args):
        """
        TODO(pprabhu)

        @param response: wardmodem response to be translated to AT response to
                the modem manager.

        """
        raise NotImplementedError()

    # ##########################################################################
    # Callbacks -- These are the functions that process events from the
    # ATChannel or the TaskLoop. These functions are either
    #   (1) set as callbacks in the ATChannel, or
    #   (2) called internally to process the AT command to/from the TaskLoop.

    def _process_modem_at_command(self, command):
        """
        Callback called by the physical modem channel when an AT response is
        received.

        @param command: AT command sent by the physical modem.

        """
        assert self.mode != ATTransceiverMode.WARDMODEM
        self._logger.debug('Command {modem ==> []}: |%s|', command)
        if self.mode == ATTransceiverMode.PASS_THROUGH:
            self._logger.debug('Command {[] ==> mm}: |%s|' , command)
            self._mm_channel.send(command)
        else:
            self._cached_modem_responses.append(command)
            self._verify_and_send_mm_commands()


    def _process_mm_at_command(self, command):
        """
        Callback called by the modem manager channel when an AT command is
        received.

        @param command: AT command sent by modem manager.

        """
        self._logger.debug('Command {mm ==> []}: |%s|', command)
        if(self.mode == ATTransceiverMode.PASS_THROUGH or
           self.mode == ATTransceiverMode.SPLIT_VERIFY):
            self._logger.debug('Command {[] ==> modem}: |%s|', command)
            self._modem_channel.send(command)
        if(self.mode == ATTransceiverMode.WARDMODEM or
           self.mode == ATTransceiverMode.SPLIT_VERIFY):
            self._logger.debug('Command {[] ==> wardmodem}: |%s|', command)
            self._post_wardmodem_request(command)


    def _process_wardmodem_at_command(self, command):
        """
        Function called to process an AT command response of wardmodem.

        This function is called after the response from the task loop has been
        converted to an AT command.

        @param command: The AT command response of wardmodem.

        """
        assert self.mode != ATTransceiverMode.PASS_THROUGH
        self._logger.debug('Command {wardmodem ==> []: |%s|', command)
        if self.mode == ATTransceiverMode.WARDMODEM:
            self._logger.debug('Command {[] ==> mm}: |%s|', command)
            self._mm_channel.send(command)
        else:
            self._cached_wardmodem_responses.append(command)
            self._verify_and_send_mm_commands()


    def _post_wardmodem_request(self, command):
        """
        For an AT command, find out the action to be taken on wardmodem and post
        the action.

        @param command: AT command for which a request must be posted to
                wardmodem.

        @raises: ATTransceiverException if no valid action exists for the given
                AT command.

        """
        action = self._find_wardmodem_action_for_at(command)
        state_machine_name, function_name, args = action
        try:
            state_machine = self._state_machines[state_machine_name]
        except KeyError:
            self._runtime_error(
                    'Malformed action registered for AT command -- Unknown '
                    'state machine. AT command: |%s|. Action: |%s|' %
                    (command, action))
        try:
            function = getattr(state_machine, function_name)
        except AttributeError:
            self._runtime_error(
                    'Malformed action registered for AT command -- Unkonwn '
                    'function name. AT command: |%s|. Action: |%s|. Object '
                    'dictionary: %s.' % (command, action, dir(state_machine)))

        self._task_loop.post_task(
                self._execute_state_machine_function, command, action, function,
                args)

    # ##########################################################################
    # Helper functions

    def _execute_state_machine_function(self, at_command, action, function,
                                        args):
        """
        A thin wrapper to execute state_machine.function(args). Instead of
        posting the call directly, this method is posted for better error
        reporting in case of failure.

        @param at_command: The AT command for which this function was called.

        @param action: The matching wardmodem action which led to this function
                call.

        @param function: The function to call.

        @param args: The arguments to be passed to function.

        """
        try:
            function(args)
        except TypeError:
            self._runtime_error(
                    'Malformed action registered for AT command -- Incorrect '
                    'arguments. AT command: |%s|. Action: |%s|. Expected '
                    'function signature: %s' % (at_command, action,
                                                inspect.getargspec(function)))


    def _load_conf_file(self, file_name):
        """
        Load the configuration file from the module directory.

        The configuration file is an executable python file. Since the file name
        is known only at run-time, we must find the module directory and
        manually point execfile to the directory for loading the configuration
        file.

        @param file_name: The configuration file name.

        """
        current_module = sys.modules[__name__]
        dir_name = os.path.dirname(current_module.__file__)
        full_path = os.path.join(dir_name, file_name)
        conf = {}
        execfile(full_path, conf)
        return conf


    def _update_at_to_wardmodem(self, raw_map):
        """
        Update the dictionary that maps AT commands and their arguments to the
        action to be taken by wardmodem.

        The internal map updated is
            {at_command, {(arg1, arg2, ...), (state_machine_name,
                                              function,
                                              (idx1, idx2, ...))}}
        Here,
            - at_command [string] is the AT Command received,
            - (arg1, arg2, ...) [tuple of string] is possibly empty, and
              specifies the arguments that need to be matched. It may contain
              the special symbol '*' to mean ignore that argument while
              matching.
            - state_machine_name [string] is name of a state machine in the
              state machine map.
            - function [string] is a function exported by the state machine
              mapped to by state_machine_name
            - (idx1, idx2, ...) [tuple of int] lists the (string) arguments that
              should be passed on from the AT command to the called function.

        @param raw_map: The raw map from AT command to function read in from the
                configuration file. For the format of this map, see the comment
                at the head of a configuration file.

        @raises WardModemSetupException if raw_map was not well-formed, and the
                update failed. Absolutely no guarantees about the state of the
                map if the update fails.

        """
        for atcom in raw_map:
            try:
                at, args = self._parse_at_command(atcom)
            except wardmodem_exceptions.ATTransceiverException as e:
                self._setup_error(e.args)
            action = self._sanitize_wardmodem_action(raw_map[atcom])

            if at not in self._at_to_wardmodem:
                self._at_to_wardmodem[at] = {}
            if args in self._at_to_wardmodem[at]:
                self._logger.debug('Updated at_to_wardmodem: '
                                   '|%s(%s): [%s --> %s]|',
                                   at, args,
                                   str(self._at_to_wardmodem[at][args]),
                                   str(action))
            else:
                self._logger.debug('Added to at_to_wardmodem: |%s(%s): %s|',
                                   at, args, str(action))
            self._at_to_wardmodem[at][args] = action


    def _sanitize_wardmodem_action(self, action):
        """
        Test that the action specified in the AT command --> wardmodem action
        map is sane and normalize to simplify handling later.

        Currently, this only checks that the action consists of tuples of the
        right size / type. It might make sense to make this check a lot stricter
        so that ill-formed configuration files are caught early.

        Returns the normalized form: 3-tuple with the last item being a tuple of
        integers.

        @param action: The action tuple to check.

        @return action: Sanitized action tuple. Normalized form is (string,
        string, (int*)).

        @raises: WardModemSetupException if action is ill-formed.

        """
        errstr = ('Ill formed action |%s|. Action must be of the form: '
                  '(state_machine_name, function_name, (index_tuple)) '
                  'Here, index_tuple is a tuple of integers.' % str(action))
        sanitized_action = []
        if type(action) is not tuple:
            self._setup_error(errstr)
        if len(action) != 2 and len(action) != 3:
            self._setup_error(errstr)
        if type(action[0]) != str or type(action[1]) != str:
            self._setup_error(errstr)
        sanitized_action.append(action[0])
        sanitized_action.append(action[1])
        if len(action) != 3:
            sanitized_action.append(())
        else:
            if type(action[2]) == tuple:
                for idx in action[2]:
                    if type(idx) != int:
                        self._setup_error(errstr)
                sanitized_action.append(action[2])
            else:
                if type(action[2]) != int:
                    self._setup_error(errstr)
                sanitized_action.append((action[2],))
        return tuple(sanitized_action)


    def _parse_at_command(self, atcom):
        """
        Parse an AT command into the command and its arguments

        Examples:
        'AT?' --> ('AT?', ())
        'AT+XX' --> ('AT+XX', ())
        'AT%SCF=1,2' --> ('AT%SCF=', ('1', '2'))
        'ATX=*' --> ('ATX=', ('*',))

        @param atcom: [string] the AT command to parse

        @return: [(string, (string))] A tuple of the AT command proper and a
        tuple of arguments. If no arguments are present, an empty argument
        tuple is included.

        @raises ATTransceiverError if atcom is not well-formed.

        """
        parts = atcom.split('=')
        if len(parts) > 2:
            self._runtime_error('Parsing error: |%s|' % atcom)
        if len(parts) == 1:
            return (atcom, ())
        # Note: Include the trailing '=' in the AT commmand.
        at = parts[0] + '='
        if parts[1] == '':
            # This was a command of the form 'ATXXX='.
            # Treat this as having no arguments, instead of a single ''
            # argument.
            return (at, ())
        else:
            return (at, tuple(parts[1].split(',')))


    def _find_wardmodem_action_for_at(self, atcom):
        """
        For the given AT command, find the appropriate action from wardmodem.

        @param atcom: [string] The AT command to find action for.

        @return: [(string, string, (string))] Returns the tuple of
                (state_machine_name, function, (arguments)) for the
                corresponding action. The action to be taken is roughly --

                state_machine.function(arguments)


        @raises: ATTransceiverException if the at command is ill-formed or we
                don't have a corresponding action.

        """
        try:
            at, args = self._parse_at_command(atcom)
        except wardmodem_exceptions.ATTransceiverException as e:
            self._runtime_error(
                    'Ill formed AT command received. %s' % str(e.args))
        if at not in self._at_to_wardmodem:
            self._runtime_error('Unknown AT command: |%s|' % atcom)

        for candidate_args in self._at_to_wardmodem[at]:
            candidate_action = self._at_to_wardmodem[at][candidate_args]
            if self._args_match(args, candidate_args):
                # Found corresponding entry, now replace the indices of the
                # arguments in the action with actual arguments.
                machine, function, idxs = candidate_action
                fargs = []
                for idx in idxs:
                    fargs.append(args[idx])
                return machine, function, tuple(fargs)

        self._runtime_error('Unhandled arguments: |%s|' % atcom)


    def _args_match(self, args, matches):
        """
        Check whether args are captured by regexp.

        @param args: A tuple of strings, the arguments to check for inclusion.

        @param matches: A similar tuple, but may contain the wild-card '*'.

        @return True if args is represented by regexp, False otherwise.

        """
        if len(args) != len(matches):
            return False
        for i in range(len(args)):
            arg = args[i]
            match = matches[i]
            if match == '*':
                return True
            if arg != match:
                return False
        return True


    def _verify_and_send_mm_commands(self):
        """
        While there are corresponding responses from wardmodem and physical
        modem, verify that they match and respond to modem manager.

        """
        if not self._cached_wardmodem_responses:
            return
        elif not self._cached_modem_responses:
            if self._modem_response_wait_task is not None:
                return
            self._modem_response_wait_task = (
                    self._task_loop.post_task_after_delay(
                            self._modem_response_timed_out,
                            self._modem_response_timeout_milliseconds))
        else:
            if self._modem_response_wait_task is not None:
                self._task_loop.cancel_posted_task(
                        self._modem_response_wait_task)
                self._modem_response_wait_task = None
            self._verify_and_send_mm_command(
                    self._cached_modem_responses.popleft(),
                    self._cached_wardmodem_responses.popleft())
            self._verify_and_send_mm_commands()


    def _verify_and_send_mm_command(self, modem_response, wardmodem_response):
        """
        Verify that the two AT commands match and respond to modem manager.

        @param modem_response: AT command response of the physical modem.

        @param wardmodem_response: AT command response of wardmodem.

        """
        # TODO(pprabhu) This can not handle unsolicited commands yet.
        # Unsolicited commands from either of the modems will push the lists out
        # of sync.
        if wardmodem_response != modem_response:
            self._logger.warning('Response verification failed.')
            self._logger.warning('modem response: |%s|', modem_response)
            self._logger.warning('wardmodem response: |%s|', wardmodem_response)
            self._logger.warning('wardmodem response takes precedence.')
            self._report_verification_failure(
                    self.VERIFICATION_FAILED_MISMATCH,
                    modem_response,
                    wardmodem_response)
        self._logger.debug('Command {[] ==> mm}: |%s|' , wardmodem_response)
        self._mm_channel.send(wardmodem_response)


    def _modem_response_timed_out(self):
        """
        Callback called when we time out waiting for physical modem response for
        some wardmodem response. Can't do much -- log physical modem failure and
        forward wardmodem response anyway.

        """
        assert (not self._cached_modem_responses and
                self._cached_wardmodem_responses)
        wardmodem_response = self._cached_wardmodem_responses.popleft()
        self._logger.warning('modem response timed out. '
                             'Forwarding wardmodem response |%s| anyway.',
                             wardmodem_response)
        self._logger.debug('Command {[] ==> mm}: |%s|' , wardmodem_response)
        self._report_verification_failure(
                self.VERIFICATION_FAILED_TIME_OUT,
                None,
                wardmodem_response)
        self._mm_channel.send(wardmodem_response)
        self._modem_response_wait_task = None
        self._verify_and_send_mm_commands()


    def _report_verification_failure(self, failure, modem_response,
                                     wardmodem_response):
        """
        Failure to verify the wardmodem response will call this non-public
        method.

        At present, it is only used by unittests to detect failure.

        @param failure: The cause of failure. Must be one of
                VERIFICATION_FAILED_MISMATCH or VERIFICATION_FAILED_TIME_OUT.

        @param modem_response: The received modem response (if any).

        @param wardmodem_response: The received wardmodem response.

        """
        pass


    def _runtime_error(self, error_message):
        """
        Log the message at error level and raise ATTransceiverException.

        @param error_message: The error message.

        @raises: ATTransceiverException.

        """
        self._logger.error(error_message)
        raise wardmodem_exceptions.ATTransceiverException(error_message)


    def _setup_error(self, error_message):
        """
        Log the message at error level and raise WardModemSetupException.

        @param error_message: The error message.

        @raises: WardModemSetupException.

        """
        self._logger.error(error_message)
        raise wardmodem_exceptions.WardModemSetupException(error_message)
