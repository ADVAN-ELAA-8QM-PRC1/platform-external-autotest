# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from autotest_lib.client.common_lib import error
from autotest_lib.client.cros import auth_server, cros_ui_test, cryptohome
from autotest_lib.client.cros import constants as chromeos_constants

class login_CryptohomeIncognitoMounted(cros_ui_test.UITest):
    version = 1


    def __login_denier(self, handler, url_args):
        handler.send_response(403)
        handler.end_headers()
        handler.wfile.write('Error=BadAuthentication.')


    def start_authserver(self):
        self._authServer = auth_server.GoogleAuthServer(
            cl_responder=self.__login_denier)
        self._authServer.run()

        self.use_local_dns()


    def run_once(self):
        if (cryptohome.is_mounted(allow_fail=True) or
            not cryptohome.is_mounted_on_tmpfs(
                     device=chromeos_constants.CRYPTOHOME_INCOGNITO)):
            raise error.TestFail('CryptohomeIsMountedOnTmpfs should return '
                                 'True.')
