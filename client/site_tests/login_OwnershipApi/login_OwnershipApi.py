# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import dbus
import dbus.glib
import gobject
import logging
import os
import tempfile

from autotest_lib.client.bin import test
from autotest_lib.client.common_lib import autotemp, error
from autotest_lib.client.cros import constants, cros_ui, cryptohome, login
from autotest_lib.client.cros import ownership


class login_OwnershipApi(test.test):
    version = 1

    _testuser = 'cryptohometest@chromium.org'
    _testpass = 'testme'
    _testpolicydata = 'hooberbloob'

    _tempdir = None

    def initialize(self):
        try:
            os.unlink(constants.OWNER_KEY_FILE)
            os.unlink(constants.SIGNED_PREFERENCES_FILE)
        except (IOError, OSError) as error:
            logging.info(error)
        login.refresh_login_screen()
        cryptohome.remove_vault(self._testuser)
        cryptohome.mount_vault(self._testuser, self._testpass, create=True)
        self._tempdir = autotemp.tempdir(unique_id=self.__class__.__name__)
        # to prime nssdb.
        tmpname = self.__generate_temp_filename()
        cros_ui.xsystem_as('HOME=%s %s %s' % (constants.CRYPTOHOME_MOUNT_PT,
                                              constants.KEYGEN,
                                              tmpname))
        os.unlink(tmpname)
        super(login_OwnershipApi, self).initialize()


    def __generate_temp_filename(self):
        just_for_name = tempfile.NamedTemporaryFile(mode='w', delete=True)
        basename = just_for_name.name
        just_for_name.close()  # deletes file.
        return basename


    def __log_and_stop(self, ret_code):
        logging.info("exited %s" % ret_code)
        self._loop.quit()


    def __log_err_and_stop(self, e):
        logging.debug(e)
        self._loop.quit()


    def run_once(self):
        keyfile = ownership.generate_and_register_owner_keypair(self._testuser,
                                                                self._testpass)

        # open DBus connection to session_manager
        bus = dbus.SystemBus()
        proxy = bus.get_object('org.chromium.SessionManager',
                               '/org/chromium/SessionManager')
        sm = dbus.Interface(proxy, 'org.chromium.SessionManagerInterface')

        sig = ownership.sign(keyfile, self._testuser)
        sm.Whitelist(self._testuser, dbus.ByteArray(sig))
        wl_sig = sm.CheckWhitelist(self._testuser, byte_arrays=True)
        if sig != wl_sig:
            raise error.TestFail("CheckWhitelist signature mismatch")

        sm.StorePolicy(self._testpolicydata,
                       reply_handler=self.__log_and_stop,
                       error_handler=self.__log_err_and_stop)

        sm.Unwhitelist(self._testuser, dbus.ByteArray(sig))
        try:
            sm.CheckWhitelist(self._testuser)
            raise error.TestFail("Should not have found user in whitelist!")
        except dbus.DBusException as e:
            logging.debug(e)

        self._loop = gobject.MainLoop()
        self._loop.run()

        retrieved_policy = sm.RetrievePolicy()
        if retrieved_policy != self._testpolicydata:
            raise error.TestFail('Policy should not be %s' % retrieved_policy)


    def cleanup(self):
        cryptohome.unmount_vault()
        self._tempdir.clean()
        super(login_OwnershipApi, self).cleanup()
