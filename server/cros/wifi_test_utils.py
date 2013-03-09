# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os
import re

from autotest_lib.client.common_lib import error


def get_server_addr_in_lab(hostname):
    """
    If we are in the lab use the names for the server, AKA rspro, and the
    router as defined in: go/chromeos-lab-hostname-convention

    @param hostname String machine name in wifi cell
            (e.g. chromeos1-shelf1-host1.cros)
    @return String server name in cell
            (e.g. chromeos1-shelf1-host1-rspro.cros)

    """
    domain = ''
    machine = hostname
    if hostname.find('.'):
        domain_start = hostname.find('.')
        domain = hostname[domain_start:]
        machine = hostname[0:domain_start]
    return '%s-rspro%s' % (machine, domain)


def get_router_addr_in_lab(hostname):
    """
    If we are in the lab use the names for the server, AKA rspro, and the
    router as defined in: go/chromeos-lab-hostname-convention

    @param hostname String machine name in wifi cell
            (e.g. chromeos1-shelf1-host1.cros)
    @return String router name in cell
            (e.g. chromeos1-shelf1-host1-router.cros)

    """
    domain = ''
    machine = hostname
    if hostname.find('.'):
        domain_start = hostname.find('.')
        domain = hostname[domain_start:]
        machine = hostname[0:domain_start]
    return '%s-router%s' % (machine, domain)


def is_installed(host, filename):
    """
    Checks if a file exists on a remote machine.

    @param host Host object representing the remote machine.
    @param filename String path of the file to check for existence.
    @return True if filename is installed on host; False otherwise.

    """
    result = host.run("ls %s" % filename, ignore_status=True)
    m = re.search(filename, result.stdout)
    return m is not None


def get_install_path(host, filename, paths):
    """
    Checks if a file exists on a remote machine in one of several paths.

    @param host Host object representing the remote machine.
    @param filename String name of the file to check for existence.
    @param paths List of paths to check for filename in.
    @return String full path of installed file, or None if not found.

    """
    if not paths:
        return None

    # A single path entry is the same as testing is_installed().
    if len(paths) == 1:
        install_path = os.path.join(paths, filename)
        if is_installed(host, install_path):
            return install_path
        return None

    result = host.run("ls {%s}/%s" % (','.join(paths), filename),
                      ignore_status=True)
    found_path = result.stdout.split('\n')[0]
    return found_path or None


def must_be_installed(host, cmd):
    """
    Asserts that cmd is installed on a remote machine at some path and raises
    an exception if this is not the case.

    @param host Host object representing the remote machine.
    @param cmd String name of the command to check for existence.
    @return String full path of cmd on success.  Error raised on failure.

    """
    if is_installed(host, cmd):
        return cmd

    # Hunt for the equivalent file in /usr/local.
    cmd_base = os.path.basename(cmd)
    local_paths = [ '/usr/local/bin', '/usr/local/sbin' ]
    alternate_path = get_install_path(host, cmd_base, local_paths)
    if alternate_path:
        return alternate_path

    raise error.TestFail('Unable to find %s on %s' % (cmd, host.ip))


def ping_args(params):
    """
    Builds up an argument string for the ping command from a dict of settings.

    @param params dict of settings for ping.
    @return String of arguments that ping will understand.

    """
    args = ""
    if 'count' in params:
        args += " -c %s" % params['count']
    if 'size' in params:
        args += " -s %s" % params['size']
    if 'bcast' in params:
        args += " -b"
    if 'flood' in params:
        args += " -f"
    if 'interval' in params:
        args += " -i %s" % params['interval']
    if 'interface' in params:
        args += " -I %s" % params['interface']
    if 'qos' in params:
        ac = string.lower(params['qos'])
        if ac == 'be':
            args += " -Q 0x04"
        elif ac == 'bk':
            args += " -Q 0x02"
        elif ac == 'vi':
            args += " -Q 0x08"
        elif ac == 'vo':
            args += " -Q 0x10"
        else:
            args += " -Q %s" % ac
    return args


def parse_ping_output(ping_output):
    """
    Extract a dictionary of statistics from the output of the ping command.
    On error, some statistics may be missing entirely from the output.

    @param ping_output String output of ping.
    @return dict of relevant statistics on success.

    """
    stats = {}
    for k in ('xmit', 'recv', 'loss', 'min', 'avg', 'max', 'dev'):
        stats[k] = '???'
    m = re.search('([0-9]*) packets transmitted,[ ]*([0-9]*)[ ]'
        '(packets |)received, ([0-9]*)', ping_output)
    if m is not None:
        stats['xmit'] = m.group(1)
        stats['recv'] = m.group(2)
        stats['loss'] = m.group(4)
    m = re.search('(round-trip|rtt) min[^=]*= '
                  '([0-9.]*)/([0-9.]*)/([0-9.]*)/([0-9.]*)', ping_output)
    if m is not None:
        stats['min'] = m.group(2)
        stats['avg'] = m.group(3)
        stats['max'] = m.group(4)
        stats['dev'] = m.group(5)
    return stats
