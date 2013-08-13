#!/usr/bin/env python

# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import dbus
import dbus.exceptions
import dbus.mainloop.glib
import gobject
import logging
import optparse
import os
import signal
import time

import client
import mm1
import modem_3gpp
import modemmanager
import net_interface
import sim
import testing

import common
from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error


DEFAULT_TEST_NETWORK_PREFIX = 'Test Network'

class TestModemManagerContextError(Exception):
    """
    Exception subclass for exceptions that can be raised by
    TestModemManagerContext for specific errors related to it.

    """
    pass

class TestModemManagerContext(object):
    """
    TestModemManagerContext is an easy way for an autotest to setup a pseudo
    modem manager environment. A typical test will look like:

    with pseudomodem.TestModemManagerContext(True):
        ...
        # Do stuff
        ...

    Which will stop the real modem managers that are executing and launch the
    pseudo modem manager in a subprocess.

    Passing False to the TestModemManagerContext constructor will simply render
    this class a no-op, not affecting any environment configuration.

    """

    DEFAULT_MANAGERS = [ ('modemmanager', 'ModemManager'),
                         ('cromo', 'cromo') ]

    def __init__(self, use_pseudomodem,
                 family='3GPP',
                 sim=None,
                 modem=None):
        """
        @param use_pseudomodem: Whether or not the context should create a
                                pseudo modem manager.

        @param family: If the value of |modem| is None, a default Modem of
                       family 3GPP or CDMA is initialized based on the value of
                       this parameter, which is a string that contains either
                       '3GPP' or 'CDMA'. The default value is '3GPP'.

        @param sim: An instance of sim.SIM. This is required for 3GPP modems
                    as it encapsulates information about the carrier.

        @param modem: An instance of a modem.Modem subclass. If none is provided
                      the default modem is defined by the |family| parameter.

        """
        self.use_pseudomodem = use_pseudomodem
        if modem:
            self.pseudo_modem = modem
        elif family == '3GPP':
            self.pseudo_modem = modem_3gpp.Modem3gpp()
        elif family == 'CDMA':
            # Import modem_cdma here to avoid circular imports.
            import modem_cdma
            self.pseudo_modem = modem_cdma.ModemCdma()
        else:
            raise TestModemManagerContextError(
                "Invalid modem family value: " + str(family))
        if not sim and family != 'CDMA':
            # Get a handle to the global 'sim' module here, as the name clashes
            # with a local variable.
            simmodule = globals()['sim']
            sim = simmodule.SIM(simmodule.SIM.Carrier('test'),
                                mm1.MM_MODEM_ACCESS_TECHNOLOGY_GSM)
        self.sim = sim
        self.pseudo_modem_manager = None

    def __enter__(self):
        if self.use_pseudomodem:
            for manager in self.DEFAULT_MANAGERS:
                try:
                    utils.run('/sbin/stop %s' % manager[0])
                except error.CmdError:
                    logging.info('Failed to stop upstart job "%s". Will try to'
                                 ' kill directly.', manager[0])
                    try:
                        utils.run('/usr/bin/pkill %s' % manager[1])
                    except error.CmdError:
                        logging.info(
                                'Failed to kill "%s", assuming it is gone',
                                manager[1])
            self.pseudo_modem_manager = \
                PseudoModemManager(modem=self.pseudo_modem, sim=self.sim)
            self.pseudo_modem_manager.Start()
        return self

    def __exit__(self, *args):
        if self.use_pseudomodem:
            self.pseudo_modem_manager.Stop()
            self.pseudo_modem_manager = None
            for manager in self.DEFAULT_MANAGERS:
                try:
                    utils.run('/sbin/start %s' % manager[0])
                except error.CmdError:
                    pass

    def GetPseudoModemManager(self):
        """
        Returns the underlying PseudoModemManager object.

        @return An instance of PseudoModemManager, or None, if this object
                was initialized with use_pseudomodem=False.

        """
        return self.pseudo_modem_manager


class PseudoModemManagerException(Exception):
    """Class for exceptions thrown by PseudoModemManager."""
    pass

class PseudoModemManager(object):
    """
    This class is responsible for setting up the virtual ethernet interfaces,
    initializing the DBus objects and running the main loop.

    This class can be utilized either using Python's with statement, or by
    calling Start and Stop:

        with PseudoModemManager(modem, sim):
            ... do stuff ...

    or

        pmm = PseudoModemManager(modem, sim)
        pmm.Start()
        ... do stuff ...
        pmm.Stop()

    The PseudoModemManager constructor takes a variable called "detach". If a
    value of True is given, the PseudoModemManager will run the main loop in
    a child process. This is particularly useful when using PseudoModemManager
    in an autotest:

        with PseudoModemManager(modem, sim, detach=True):
            ... This will run the modem manager in the background while this
            block executes. When the code in this block finishes running, the
            PseudoModemManager will automatically kill the child process.

    If detach=False, then the pseudo modem manager will run the main process
    until the process exits. PseudoModemManager is created with detach=False
    when this file is run as an executable.

    """

    MODEM_INIT_TIMEOUT = 5

    modem_net_interface = net_interface.PseudoNetInterface()

    def __init__(self,
                 modem,
                 sim=None,
                 detach=True):
        self.modem = modem
        self.sim = sim
        self.detach = detach
        self.child = None
        self.started = False

    def __enter__(self):
        self.Start()
        return self

    def __exit__(self, *args):
        self.Stop()

    def Start(self):
        """
        Starts the pseudo modem manager based on the initialization parameters.
        Depending on the configuration, this method may or may not fork. If a
        subprocess is launched, a DBus mainloop will be initialized by the
        subprocess. This method sets up the virtual Ethernet interfaces and
        initializes tha DBus objects and servers.

        """
        logging.info('Starting pseudo modem manager.')
        self.started = True

        if self.detach:
            self.child = os.fork()
            if self.child == 0:
                self._Run()
            else:
                time.sleep(self.MODEM_INIT_TIMEOUT)
        else:
            self._Run()

    def Stop(self):
        """
        Stops the pseudo modem manager. This means killing the subprocess,
        if any, stopping the DBus server, and tearing down the virtual Ethernet
        pair.

        """
        logging.info('Stopping pseudo modem manager.')
        if not self.started:
            logging.info('Not started, cannot stop.')
            return
        if self.detach:
            if self.child != 0:
                os.kill(self.child, signal.SIGINT)
                os.waitpid(self.child, 0)
                self.child = 0
        else:
            self._Cleanup()
        self.started = False

    def Restart(self):
        """
        Restarts the pseudo modem manager.

        """
        self.Stop()
        self.Start()

    def SetModem(self, new_modem):
        """
        Sets the modem object that is exposed by the pseudo modem manager and
        restarts the pseudo modem manager.

        @param new_modem: An instance of modem.Modem to assign.

        """
        self.modem = new_modem
        self.Restart()
        time.sleep(5)

    def SetSIM(self, new_sim):
        """
        Sets the SIM object that is exposed by the pseudo modem manager and
        restarts the pseudo modem manager.

        @param new_sim: An instance of sim.SIM to assign.

        """
        self.sim = new_sim
        self.Restart()

    def _Cleanup(self):
        self.modem_net_interface.Teardown()

    def _Run(self):
        if not self.modem:
            raise Exception('No modem object has been provided.')
        self.modem_net_interface.Setup()
        dbus_loop = dbus.mainloop.glib.DBusGMainLoop()
        bus = dbus.SystemBus(private=True, mainloop=dbus_loop)
        name = dbus.service.BusName(mm1.I_MODEM_MANAGER, bus)
        self.manager = modemmanager.ModemManager(bus)

        self.modem.SetBus(bus)
        if self.sim:
            self.modem.SetSIM(self.sim)
        self.manager.Add(self.modem)

        self.testing_object = testing.Testing(self.modem, bus)

        self.mainloop = gobject.MainLoop()

        def _SignalHandler(signum, frame):
            logging.info('Signal handler called with signal %s', signum)
            self.manager.Remove(self.modem)
            self.mainloop.quit()
            if self.detach:
                self._Cleanup()
                os._exit(0)

        signal.signal(signal.SIGINT, _SignalHandler)
        signal.signal(signal.SIGTERM, _SignalHandler)

        self.mainloop.run()

    def SendTextMessage(self, sender_no, text):
        """
        Allows sending a fake text message notification.

        @param sender_no: TODO
        @param text: TODO

        """
        # TODO(armansito): Implement
        raise NotImplementedError()


def Start(use_cdma=False, activated=True, sim_locked=False,
          roaming_networks=0, interactive=False):
    """
    Runs the pseudomodem in script mode. This function is called only by the
    main function.

    @param use_cdma: If True, the pseudo modem manager will be initialized with
                     an instance of modem_cdma.ModemCdma, otherwise the default
                     modem will be used, which is an instance of
                     modem_3gpp.Modem3gpp.
    @param activated: If True, the pseudo modem will be initialized as
                      unactivated and will require service activation.
    @param sim_locked: If True, the SIM will be initialized with a PIN lock.
                       This option does nothing if 'use_cdma' is also True.
    @param roaming_networks: The number networks that will be returned from a
                             network scan in addition to the home network.
    @param interactive: If True, the pseudomodem gets launched with an
                        interactive shell.

    """
    # TODO(armansito): Support "not activated" initialization option for 3GPP
    #                  carriers.
    networks = []
    if use_cdma:
        # Import modem_cdma here to avoid circular imports.
        import modem_cdma
        m = modem_cdma.ModemCdma(
            modem_cdma.ModemCdma.CdmaNetwork(activated=activated))
        s = None
    else:
        networks = [
                modem_3gpp.Modem3gpp.GsmNetwork(
                    'Roaming Network Long ' + str(i),
                    'Roaming Network Short ' + str(i),
                    '00100' + str(i + 1),
                    dbus.types.UInt32(
                            mm1.MM_MODEM_3GPP_NETWORK_AVAILABILITY_AVAILABLE),
                    dbus.types.UInt32(
                            mm1.MM_MODEM_ACCESS_TECHNOLOGY_GSM))
                for i in xrange(roaming_networks)]
        m = modem_3gpp.Modem3gpp(roaming_networks=networks)
        s = sim.SIM(sim.SIM.Carrier(),
                    mm1.MM_MODEM_ACCESS_TECHNOLOGY_GSM,
                    locked=sim_locked)

    if interactive:
        logging.disable(logging.INFO)
    with PseudoModemManager(modem=m, sim=s, detach=interactive):
        if interactive:
            pmclient = client.PseudoModemClient()
            pmclient.Begin()

def main():
    """
    The main method, executed when this file is executed as a script.

    """
    usage = """

      Run pseudomodem to simulate a modem using the modemmanager-next
      DBus interfaces.

      Use --help for info.

    """

    parser = optparse.OptionParser(usage=usage)
    parser.add_option('-f', '--family', dest='family',
                      metavar='<family>', type="string",
                      help='<family> := 3GPP|CDMA')
    parser.add_option('-n', '--not-activated', dest='not_activated',
                      action='store_true', default=False,
                      help='Initialize the service as not-activated.')
    parser.add_option('-l', '--locked', dest='sim_locked',
                      action='store_true', default=False,
                      help='Initialize the SIM as locked.')
    parser.add_option('-r', '--roaming-networks', dest='roaming_networks',
                      default=0, type="int", metavar="<# networks>",
                      help='Number of roaming networks available for scan '
                           '(3GPP only).')
    parser.add_option('-i', '--interactive', dest='interactive',
                      action='store_true', default=False,
                      help='Launch in interactive mode.')

    (opts, args) = parser.parse_args()
    if not opts.family:
        print "A mandatory option '--family' is missing\n"
        parser.print_help()
        return

    family = opts.family
    if family not in [ '3GPP', 'CDMA' ]:
        print 'Unsupported family: ' + family
        return

    if opts.roaming_networks < 0:
        print ('Invalid number of roaming_networks: ' +
               str(opts.roaming_networks))
        return

    if opts.roaming_networks > 0 and family == 'CDMA':
        print 'Cannot initialize roaming networks for family: CDMA'
        return

    Start(family == 'CDMA', not opts.not_activated, opts.sim_locked,
          opts.roaming_networks, opts.interactive)


if __name__ == '__main__':
    main()
