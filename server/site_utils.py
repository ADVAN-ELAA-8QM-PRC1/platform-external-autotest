# Copyright (c) 2013 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


import httplib
import json
import logging
import re
import time
import urllib2

import common
from autotest_lib.client.common_lib import base_utils, global_config
from autotest_lib.server.cros.dynamic_suite import constants


_SHERIFF_JS = global_config.global_config.get_config_value(
    'NOTIFICATIONS', 'sheriffs', default='')
_LAB_SHERIFF_JS = global_config.global_config.get_config_value(
    'NOTIFICATIONS', 'lab_sheriffs', default='')
_CHROMIUM_BUILD_URL = global_config.global_config.get_config_value(
    'NOTIFICATIONS', 'chromium_build_url', default='')

LAB_GOOD_STATES = ('open', 'throttled')


class LabIsDownException(Exception):
    """Raised when the Lab is Down"""
    pass


class BoardIsDisabledException(Exception):
    """Raised when a certain board is disabled in the Lab"""
    pass


class ParseBuildNameException(Exception):
    """Raised when ParseBuildName() cannot parse a build name."""
    pass


def ParseBuildName(name):
    """Format a build name, given board, type, milestone, and manifest num.

    @param name: a build name, e.g. 'x86-alex-release/R20-2015.0.0'

    @return board: board the manifest is for, e.g. x86-alex.
    @return type: one of 'release', 'factory', or 'firmware'
    @return milestone: (numeric) milestone the manifest was associated with.
    @return manifest: manifest number, e.g. '2015.0.0'

    """
    match = re.match(r'([\w-]+)-(\w+)/R(\d+)-([\d.ab-]+)', name)
    if match and len(match.groups()) == 4:
        return match.groups()
    raise ParseBuildNameException('%s is a malformed build name.' % name)


def get_label_from_afe(hostname, label_prefix, afe):
    """Retrieve a host's specific label from the AFE.

    Looks for a host label that has the form <label_prefix>:<value>
    and returns the "<value>" part of the label. None is returned
    if there is not a label matching the pattern

    @param hostname: hostname of given DUT.
    @param label_prefix: prefix of label to be matched, e.g., |board:|
    @param afe: afe instance.
    @returns the label that matches the prefix or 'None'

    """
    labels = afe.get_labels(name__startswith=label_prefix,
                            host__hostname__in=[hostname])
    if labels and len(labels) == 1:
        return labels[0].name.split(label_prefix, 1)[1]


def get_board_from_afe(hostname, afe):
    """Retrieve given host's board from its labels in the AFE.

    Looks for a host label of the form "board:<board>", and
    returns the "<board>" part of the label.  `None` is returned
    if there is not a single, unique label matching the pattern.

    @param hostname: hostname of given DUT.
    @param afe: afe instance.
    @returns board from label, or `None`.

    """
    return get_label_from_afe(hostname, constants.BOARD_PREFIX, afe)


def get_build_from_afe(hostname, afe):
    """Retrieve the current build for given host from the AFE.

    Looks through the host's labels in the AFE to determine its build.

    @param hostname: hostname of given DUT.
    @param afe: afe instance.
    @returns The current build or None if it could not find it or if there
             were multiple build labels assigned to this host.

    """
    return get_label_from_afe(hostname, constants.VERSION_PREFIX, afe)


def get_sheriffs(lab_only=False):
    """
    Polls the javascript file that holds the identity of the sheriff and
    parses it's output to return a list of chromium sheriff email addresses.
    The javascript file can contain the ldap of more than one sheriff, eg:
    document.write('sheriff_one, sheriff_two').

    @param lab_only: if True, only pulls lab sheriff.
    @return: A list of chroium.org sheriff email addresses to cc on the bug.
             An empty list if failed to parse the javascript.
    """
    sheriff_ids = []
    sheriff_js_list = _LAB_SHERIFF_JS.split(',')
    if not lab_only:
        sheriff_js_list.extend(_SHERIFF_JS.split(','))

    for sheriff_js in sheriff_js_list:
        try:
            url_content = base_utils.urlopen('%s%s'% (
                _CHROMIUM_BUILD_URL, sheriff_js)).read()
        except (ValueError, IOError) as e:
            logging.warning('could not parse sheriff from url %s%s: %s',
                             _CHROMIUM_BUILD_URL, sheriff_js, str(e))
        except (urllib2.URLError, httplib.HTTPException) as e:
            logging.warning('unexpected error reading from url "%s%s": %s',
                             _CHROMIUM_BUILD_URL, sheriff_js, str(e))
        else:
            ldaps = re.search(r"document.write\('(.*)'\)", url_content)
            if not ldaps:
                logging.warning('Could not retrieve sheriff ldaps for: %s',
                                 url_content)
                continue
            sheriff_ids += ['%s@chromium.org' % alias.replace(' ', '')
                            for alias in ldaps.group(1).split(',')]
    return sheriff_ids


def remote_wget(source_url, dest_path, ssh_cmd):
    """wget source_url from localhost to dest_path on remote host using ssh.

    @param source_url: The complete url of the source of the package to send.
    @param dest_path: The path on the remote host's file system where we would
        like to store the package.
    @param ssh_cmd: The ssh command to use in performing the remote wget.
    """
    wget_cmd = ("wget -O - %s | %s 'cat >%s'" %
                (source_url, ssh_cmd, dest_path))
    base_utils.run(wget_cmd)


def get_lab_status():
    """Grabs the current lab status and message.

    @returns a dict with keys 'lab_is_up' and 'message'. lab_is_up points
             to a boolean and message points to a string.
    """
    result = {'lab_is_up' : True, 'message' : ''}
    status_url = global_config.global_config.get_config_value('CROS',
            'lab_status_url')
    max_attempts = 5
    retry_waittime = 1
    for _ in range(max_attempts):
        try:
            response = urllib2.urlopen(status_url)
        except IOError as e:
            logging.debug('Error occured when grabbing the lab status: %s.',
                          e)
            time.sleep(retry_waittime)
            continue
        # Check for successful response code.
        if response.getcode() == 200:
            data = json.load(response)
            result['lab_is_up'] = data['general_state'] in LAB_GOOD_STATES
            result['message'] = data['message']
            return result
        time.sleep(retry_waittime)
    # We go ahead and say the lab is open if we can't get the status.
    logging.warn('Could not get a status from %s', status_url)
    return result


def check_lab_status(board=None):
    """Check if the lab is up and if we can schedule suites to run.

    Also checks if the lab is disabled for that particular board, and if so
    will raise an error to prevent new suites from being scheduled for that
    board.

    @param board: board name that we want to check the status of.

    @raises LabIsDownException if the lab is not up.
    @raises BoardIsDisabledException if the desired board is currently
                                           disabled.
    """
    # Ensure we are trying to schedule on the actual lab.
    if not (global_config.global_config.get_config_value('SERVER',
            'hostname').startswith('cautotest')):
        return

    # First check if the lab is up.
    lab_status = get_lab_status()
    if not lab_status['lab_is_up']:
        raise LabIsDownException('Chromium OS Lab is currently not up: '
                                       '%s.' % lab_status['message'])

    # Check if the board we wish to use is disabled.
    # Lab messages should be in the format of:
    # Lab is 'status' [boards not to be ran] (comment). Example:
    # Lab is Open [stumpy, kiev, x86-alex] (power_resume rtc causing duts to go
    # down)
    boards_are_disabled = re.search('\[(.*)\]', lab_status['message'])
    if board and boards_are_disabled:
        if board in boards_are_disabled.group(1):
            raise BoardIsDisabledException('Chromium OS Lab is '
                    'currently not allowing suites to be scheduled on board '
                    '%s: %s' % (board, lab_status['message']))
    return
