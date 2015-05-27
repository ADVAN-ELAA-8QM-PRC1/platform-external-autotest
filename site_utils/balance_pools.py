#!/usr/bin/env python
# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Adjust pool balances to cover DUT shortfalls.

This command takes all broken DUTs in a specific pool for specific
boards and swaps them with working DUTs taken from a selected pool
of spares.  The command is meant primarily for replacing broken DUTs
in critical pools like BVT or CQ, but it can also be used to adjust
pool sizes, or to create or remove pools.

usage:  balance_pool.py [ options ] POOL BOARD [ BOARD ... ]

positional arguments:
  POOL                  Name of the pool to balance
  BOARD                 Names of boards to balance

optional arguments:
  -h, --help            show this help message and exit
  -t COUNT, --total COUNT
                        Set the number of DUTs in the pool to the specified
                        count for every BOARD
  -a COUNT, --grow COUNT
                        Add the specified number of DUTs to the pool for every
                        BOARD
  -d COUNT, --shrink COUNT
                        Remove the specified number of DUTs from the pool for
                        every BOARD
  -s POOL, --spare POOL
                        Pool from which to draw replacement spares (default:
                        pool:suites)
  -n, --dry-run         Report actions to take in the form of shell commands


The command attempts to remove all broken DUTs from the target POOL
for every BOARD, and replace them with enough working DUTs taken
from the spare pool to bring the strength of POOL to the requested
total COUNT.

If no COUNT options are supplied (i.e. there are no --total, --grow,
or --shrink options), the command will maintain the current totals of
DUTs for every BOARD in the target POOL.

If not enough working spares are available, broken DUTs may be left
in the pool to keep the pool at the target COUNT.

When reducing pool size, working DUTs will be returned after broken
DUTs, if it's necessary to achieve the target COUNT.

If the selected target POOL is for a Freon board, *and* the selected
spare pool has no DUTs (in any state), *and* the corresponding
non-Freon spare pool is populated, then the non-Freon pool will
be used for the Freon board.  A similar rule applies to balancing
non-Freon boards when there is an available Freon spare pool.

"""


import argparse
import sys
import time

import common
from autotest_lib.server import frontend
from autotest_lib.site_utils import status_history
from autotest_lib.site_utils.suite_scheduler import constants


_POOL_PREFIX = constants.Labels.POOL_PREFIX
_BOARD_PREFIX = constants.Labels.BOARD_PREFIX

_FREON_BOARD_TAG = 'freon'


def _log_message(message, *args):
    """Log a message with optional format arguments to stdout.

    This function logs a single line to stdout, with formatting
    if necessary, and without adornments.

    If `*args` are supplied, the message will be formatted using
    the arguments.

    @param message  Message to be logged, possibly after formatting.
    @param args     Format arguments.  If empty, the message is logged
                    without formatting.

    """
    if args:
        message = message % args
    sys.stdout.write('%s\n' % message)


def _log_info(dry_run, message, *args):
    """Log information in a dry-run dependent fashion.

    This function logs a single line to stdout, with formatting
    if necessary.  When logging for a dry run, the message is
    printed as a shell comment, rather than as unadorned text.

    If `*args` are supplied, the message will be formatted using
    the arguments.

    @param message  Message to be logged, possibly after formatting.
    @param args     Format arguments.  If empty, the message is logged
                    without formatting.

    """
    if dry_run:
        message = '# ' + message
    _log_message(message, *args)


def _log_error(message, *args):
    """Log an error to stderr, with optional format arguments.

    This function logs a single line to stderr, prefixed to indicate
    that it is an error message.

    If `*args` are supplied, the message will be formatted using
    the arguments.

    @param message  Message to be logged, possibly after formatting.
    @param args     Format arguments.  If empty, the message is logged
                    without formatting.

    """
    if args:
        message = message % args
    sys.stderr.write('ERROR: %s\n' % message)


class _DUTPool(object):
    """Information about a pool of DUTs for a given board.

    This class collects information about all DUTs for a given
    board and pool pair, and divides them into three categories:
      + Working - the DUT is working for testing, and not locked.
      + Broken - the DUT is unable to run tests, or it is locked.
      + Ineligible - the DUT is not available to be removed from
          this pool.  The DUT may be either working or broken.

    DUTs with more than one pool: label are ineligible for exchange
    during balancing.  This is done for the sake of chameleon hosts,
    which must always be assigned to pool:suites.  These DUTs are
    always marked with pool:chameleon to prevent their reassignment.

    TODO(jrbarnette):  The use of `pool:chamelon` (instead of just
    the `chameleon` label is a hack that should be eliminated.

    _DUTPool instances are used to track both main pools that need
    to be resupplied with working DUTs and spare pools that supply
    those DUTs.

    @property board               Name of the board associated with
                                  this pool of DUTs.
    @property pool                Name of the pool associated with
                                  this pool of DUTs.
    @property _working_hosts      The list of this pool's working
                                  DUTs.
    @property _broken_hosts       The list of this pool's broken
                                  DUTs.
    @property _ineligible__hosts  The list of this pool's ineligible
                                  DUTs.
    @property _labels             A list of labels that identify a DUT
                                  as part of this pool.
    @property _total_hosts        The total number of hosts in pool.

    """


    @staticmethod
    def _get_platform_label(board):
        """Return the platform label associated with `board`.

        When swapping between freon and non-freon boards, the
        platform label must also change (because wmatrix reports
        build results against platform labels, not boards).  So, we
        must be able to get the platform label from the board name.

        For non-freon boards, the platform label is based on a name
        assigned by the firmware, which in some cases is different
        from the board name.  For freon boards, the platform label
        is always the board name.

        @param board The board name to convert to a platform label.
        @return The platform label for the given board name.

        """
        if board.endswith(_FREON_BOARD_TAG):
            return board
        if board.startswith('x86-'):
            return board[len('x86-') :]
        platform_map = {
          'daisy': 'snow',
          'daisy_spring': 'spring',
          'daisy_skate': 'skate',
          'parrot_ivb': 'parrot_2',
          'falco_li': 'falco'
        }
        return platform_map.get(board, board)


    @staticmethod
    def _freon_board_toggle(board):
        """Toggle a board name between freon and non-freon.

        For boards naming a freon build, return the name of the
        associated non-freon board.  For boards naming non-freon
        builds, return the name of the associated freon board.

        @param board The board name to be toggled.
        @return A new board name, toggled for freon.

        """
        if board.endswith(_FREON_BOARD_TAG):
            # The actual board name ends with either "-freon" or
            # "_freon", so we have to strip off one extra character.
            return board[: -len(_FREON_BOARD_TAG) - 1]
        else:
            # The actual board name will end with either "-freon" or
            # "_freon"; we have to figure out which one to use.
            joiner = '_'
            if joiner in board:
                joiner = '-'
            return joiner.join([board, _FREON_BOARD_TAG])


    def __init__(self, afe, board, pool, start_time, end_time,
                 use_freon=False):
        self.board = board
        self.pool = pool
        self._working_hosts = []
        self._broken_hosts = []
        self._ineligible_hosts = []
        self._total_hosts = self._get_hosts(
                afe, start_time, end_time, use_freon)
        self._labels = set([_BOARD_PREFIX + self.board,
                            self._get_platform_label(self.board),
                            _POOL_PREFIX + self.pool])


    def _get_hosts(self, afe, start_time, end_time, use_freon):
        all_histories = (
            status_history.HostJobHistory.get_multiple_histories(
                    afe, start_time, end_time,
                    board=self.board, pool=self.pool))
        if not all_histories and use_freon:
            alternate_board = self._freon_board_toggle(self.board)
            alternate_histories = (
                status_history.HostJobHistory.get_multiple_histories(
                        afe, start_time, end_time,
                        board=alternate_board, pool=self.pool))
            if alternate_histories:
                self.board = alternate_board
                all_histories = alternate_histories
        for h in all_histories:
            host = h.host
            host_pools = [l for l in host.labels
                          if l.startswith(_POOL_PREFIX)]
            if len(host_pools) != 1:
                self._ineligible_hosts.append(host)
            else:
                diag = h.last_diagnosis()[0]
                if (diag == status_history.WORKING and
                        not host.locked):
                    self._working_hosts.append(host)
                else:
                    self._broken_hosts.append(host)
        return len(all_histories)


    @property
    def pool_labels(self):
        """Return the AFE labels that identify this pool.

        The returned labels are the labels that must be removed
        to remove a DUT from the pool, or added to add a DUT.

        @return A list of AFE labels suitable for AFE.add_labels()
                or AFE.remove_labels().

        """
        return self._labels


    def calculate_inventory(self, dry_run):
        """Calculate and log how many DUTs are in this pool.

        Return the total number of DUTs in the pool across all three
        categories (working, broken, and ineligible).  As a side
        effect, log the totals.

        @param dry_run Whether the logging is for a dry run or for
                       actual execution.

        @return The total number of DUTs in this pool.

        """
        _log_info(dry_run, 'Balancing %s %s pool:',
                  self.board, self.pool)
        _log_info(dry_run,
                  'Total %d DUTs, %d working, %d broken, %d reserved.',
                  self._total_hosts, len(self._working_hosts),
                  len(self._broken_hosts), len(self._ineligible_hosts))
        return self._total_hosts


    def calculate_spares_needed(self, dry_run, target_total):
        """Calculate and log the spares needed to achieve a target.

        Return how many working spares are needed to achieve the
        given `target_total` with all DUTs working.  Log the
        adjustments entailed.

        The spares count may be positive or negative.  Positive
        values indicate spares are needed to replace broken DUTs in
        order to reach the target; negative numbers indicate that
        no spares are needed, and that a corresponding number of
        working devices can be returned.

        If the new target total would require returning ineligible
        DUTs, an error is logged, and the target total is adjusted
        so that those DUTs are not exchanged.

        @param dry_run       Whether the logging is for a dry run or
                             for actual execution.
        @param target_total  The new target pool size.

        @return The number of spares needed.

        """
        num_ineligible = len(self._ineligible_hosts)
        if target_total < num_ineligible:
            _log_error('%s %s pool: Target of %d is below '
                       'minimum of %d DUTs.',
                       self.board, self.pool,
                       target_total, num_ineligible)
            _log_error('Adjusting target to %d DUTs.', num_ineligible)
            target_total = num_ineligible
        adjustment = target_total - self._total_hosts
        if adjustment > 0:
            add_msg = 'grow pool by %d DUTs' % adjustment
        elif adjustment < 0:
            add_msg = 'shrink pool by %d DUTs' % -adjustment
        else:
            add_msg = 'no change to pool size'
        _log_info(dry_run, 'Target is %d working DUTs; %s.',
                  target_total, add_msg)
        return len(self._broken_hosts) + adjustment


    def allocate_working_spares(self, dry_run, num_requested):
        """Allocate and log a list DUTs that can be used as spares.

        Return a list of up to `num_requested` hosts from this
        pool's list of working hosts.  Log details about this pool's
        working spares.

        If the requested number of DUTs exceeds the supply, log an
        error, and return as many working devices as possible.

        @param dry_run       Whether the logging is for a dry run or
                             for actual execution.
        @param num_requested Total number of DUTs to allocate from
                             this pool's working DUTs.

        @return A list of spare DUTs.

        """
        _log_info(dry_run,
                  '%s %s pool has %d spares available.',
                  self.board, self.pool, len(self._working_hosts))
        if num_requested > len(self._working_hosts):
            _log_error('Not enough spares: need %d, only have %d.',
                       num_requested, len(self._working_hosts))
        return self._working_hosts[:num_requested]


    def allocate_surplus(self, dry_run, num_broken):
        """Allocate and log a list DUTs that can returned as surplus.

        Return a list of devices that can be returned in order to
        reduce this pool's supply.  Broken DUTs will be preferred
        over working ones.  Log information about the DUTs to be
        returned.

        The `num_broken` parameter indicates the number of broken
        DUTs to be left in the pool.  If this number exceeds the
        number of broken DUTs actually in the pool, the returned
        list will be empty.  If this number is negative, it
        indicates a number of working DUTs to be returned in
        addition to all broken ones.

        @param dry_run       Whether the logging is for a dry run or
                             for actual execution.
        @param num_broken    Total number of broken DUTs to be left in
                             this pool.

        @return A list of DUTs to be returned as surplus.

        """
        if num_broken >= 0:
            surplus = self._broken_hosts[num_broken:]
            _log_info(dry_run,
                      '%s %s pool will return %d broken DUTs, '
                      'leaving %d still in the pool.',
                      self.board, self.pool,
                      len(surplus),
                      len(self._broken_hosts) - len(surplus))
            return surplus
        else:
            _log_info(dry_run,
                      '%s %s pool will return %d surplus DUTs, '
                      'including %d working DUTs.',
                      self.board, self.pool,
                      len(self._broken_hosts) - num_broken,
                      -num_broken)
            return (self._broken_hosts +
                    self._working_hosts[:-num_broken])


def _exchange_labels(dry_run, hosts, target_pool, spare_pool):
    """Reassign a list of DUTs from one pool to another.

    For all the given hosts, remove all labels associated with
    `spare_pool`, and add the labels for `target_pool`.  Log the
    action.

    If `dry_run` is true, perform no changes, but log the `atest`
    commands needed to accomplish the necessary label changes.

    @param dry_run       Whether the logging is for a dry run or
                         for actual execution.
    @param hosts         List of DUTs (AFE hosts) to be reassigned.
    @param target_pool   The `_DUTPool` object from which the hosts
                         are drawn.
    @param spare_pool    The `_DUTPool` object to which the hosts
                         will be added.

    """
    if not hosts:
        return
    _log_info(dry_run, 'Transferring %d DUTs from %s to %s.',
              len(hosts), spare_pool.pool, target_pool.pool)
    additions = target_pool.pool_labels
    removals = spare_pool.pool_labels
    intersection = additions & removals
    additions -= intersection
    removals -= intersection
    for host in hosts:
        if not dry_run:
            _log_message('Updating host: %s.', host.hostname)
            host.remove_labels(list(removals))
            host.add_labels(list(additions))
        else:
            _log_message('atest label remove -m %s %s',
                         host.hostname, ' '.join(removals))
            _log_message('atest label add -m %s %s',
                         host.hostname, ' '.join(additions))


def _balance_board(arguments, afe, board, start_time, end_time):
    """Balance one board as requested by command line arguments.

    @param arguments     Parsed command line arguments.
    @param dry_run       Whether the logging is for a dry run or
                         for actual execution.
    @param afe           AFE object to be used for the changes.
    @param board         Board to be balanced.
    @param start_time    Start time for HostJobHistory objects in
                         the DUT pools.
    @param end_time      End time for HostJobHistory objects in the
                         DUT pools.

    """
    spare_pool = _DUTPool(afe, board, arguments.spare,
                          start_time, end_time, use_freon=True)
    main_pool = _DUTPool(afe, board, arguments.pool,
                         start_time, end_time)

    target_total = main_pool.calculate_inventory(arguments.dry_run)
    if arguments.total is not None:
        target_total = arguments.total
    elif arguments.grow:
        target_total += arguments.grow
    elif arguments.shrink:
        target_total -= arguments.shrink

    spares_needed = main_pool.calculate_spares_needed(
            arguments.dry_run, target_total)
    if spares_needed > 0:
        spare_duts = spare_pool.allocate_working_spares(
                arguments.dry_run, spares_needed)
        shortfall = spares_needed - len(spare_duts)
    else:
        spare_duts = []
        shortfall = spares_needed

    surplus_duts = main_pool.allocate_surplus(
            arguments.dry_run, shortfall)
    if not spare_duts and not surplus_duts:
        _log_info(arguments.dry_run, 'No exchange required.')
        return

    _exchange_labels(arguments.dry_run, surplus_duts,
                     spare_pool, main_pool)
    _exchange_labels(arguments.dry_run, spare_duts,
                     main_pool, spare_pool)


def _parse_command(argv):
    """Parse the command line arguments.

    Create an argument parser for this command's syntax, parse the
    command line, and return the result of the `ArgumentParser`
    `parse_args()` method.

    @param argv Standard command line argument vector; `argv[0]` is
                assumed to be the command name.

    @return Result returned by `ArgumentParser.parse_args()`.

    """
    parser = argparse.ArgumentParser(
            prog=argv[0],
            description='Balance pool shortages from spares on reserve')

    count_group = parser.add_mutually_exclusive_group()
    count_group.add_argument('-t', '--total', type=int,
                             metavar='COUNT', default=None,
                             help='Set the number of DUTs in the '
                                  'pool to the specified count for '
                                  'every BOARD')
    count_group.add_argument('-a', '--grow', type=int,
                             metavar='COUNT', default=None,
                             help='Add the specified number of DUTs '
                                  'to the pool for every BOARD')
    count_group.add_argument('-d', '--shrink', type=int,
                             metavar='COUNT', default=None,
                             help='Remove the specified number of DUTs '
                                  'from the pool for every BOARD')

    parser.add_argument('-s', '--spare', default='suites',
                        metavar='POOL',
                        help='Pool from which to draw replacement '
                             'spares (default: pool:suites)')
    parser.add_argument('-n', '--dry-run', action='store_true',
                        help='Report actions to take in the form of '
                             'shell commands')

    parser.add_argument('pool',
                        metavar='POOL',
                        help='Name of the pool to balance')
    parser.add_argument('boards', nargs='+',
                        metavar='BOARD',
                        help='Names of boards to balance')

    arguments = parser.parse_args(argv[1:])
    return arguments


def main(argv):
    """Standard main routine.

    @param argv  Command line arguments including `sys.argv[0]`.

    """
    arguments = _parse_command(argv)
    end_time = time.time()
    start_time = end_time - 24 * 60 * 60

    first_time = True
    try:
        afe = frontend.AFE(server=None)
        for board in arguments.boards:
            if not first_time:
                _log_message('')
            _balance_board(arguments, afe, board, start_time, end_time)
            first_time = False
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main(sys.argv)
