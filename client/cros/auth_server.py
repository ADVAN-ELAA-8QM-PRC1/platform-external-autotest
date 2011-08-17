# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import httplib, logging, os, socket, stat, time

import common
import constants, cryptohome, httpd
from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error


class GoogleAuthServer(object):
    """A mock Google accounts server that can be run in a separate thread
    during autotests. By default, it returns happy-signals, accepting any
    credentials.
    """

    sid = '1234'
    lsid = '5678'
    token = 'aaaa'

    __service_login_html = """
<HTML><BODY onload='gaia.chromeOSLogin.clearOldAttempts();'>
  <SCRIPT type='text/javascript' src='../service_login.js'>
  </SCRIPT>
  <FORM>
    <INPUT TYPE=text id="Email">
    <INPUT TYPE=text id="Passwd">
    <INPUT TYPE=text id="continue" value=%(continue)s>
  </FORM>
</BODY></HTML>
    """
    __issue_auth_token_miss_count = 0
    __token_auth_miss_count = 0


    def __init__(self,
                 cert_path='/etc/fake_root_ca/mock_server.pem',
                 key_path='/etc/fake_root_ca/mock_server.key',
                 ssl_port=443,
                 port=80,
                 cl_responder=None,
                 it_responder=None,
                 sl_responder=None,
                 ta_responder=None):
        self._service_login = constants.SERVICE_LOGIN_URL
        self._client_login = constants.CLIENT_LOGIN_URL
        self._issue_token = constants.ISSUE_AUTH_TOKEN_URL
        self._token_auth = constants.TOKEN_AUTH_URL
        self._test_over = '/webhp'

        self._testServer = httpd.SecureHTTPListener(
            port=ssl_port,
            docroot=os.path.dirname(__file__),
            cert_path=cert_path,
            key_path=key_path)
        sa = self._testServer.getsockname()
        logging.info('Serving HTTPS on %s, port %s' % (sa[0], sa[1]))

        if cl_responder is None:
            cl_responder = self.client_login_responder
        if it_responder is None:
            it_responder = self.issue_token_responder
        if sl_responder is None:
            sl_responder = self.service_login_responder
        if ta_responder is None:
            ta_responder = self.token_auth_responder

        self._testServer.add_url_handler(self._service_login, sl_responder)
        self._testServer.add_url_handler(self._client_login, cl_responder)
        self._testServer.add_url_handler(self._issue_token, it_responder)
        self._testServer.add_url_handler(self._token_auth, ta_responder)

        self._client_latch = self._testServer.add_wait_url(self._client_login)
        self._issue_latch = self._testServer.add_wait_url(self._issue_token)


        self._testHttpServer = httpd.HTTPListener(port=port)
        self._testHttpServer.add_url_handler(self._test_over,
                                             self.__test_over_responder)
        self._testHttpServer.add_url_handler(constants.PORTAL_CHECK_URL,
                                             self.portal_check_responder)
        self._over_latch = self._testHttpServer.add_wait_url(self._test_over)


    def run(self):
        self._testServer.run()
        self._testHttpServer.run()


    def stop(self):
        self._testServer.stop()
        self._testHttpServer.stop()


    def wait_for_client_login(self, timeout=10):
        self._client_latch.wait(timeout)
        if not self._client_latch.is_set():
            raise error.TestError('Never hit ClientLogin endpoint.')


    def wait_for_issue_token(self, timeout=10):
        self._issue_latch.wait(timeout)
        if not self._issue_latch.is_set():
            self.__issue_auth_token_miss_count += 1
            logging.error('Never hit IssueAuthToken endpoint.')


    def wait_for_test_over(self, timeout=10):
        self._over_latch.wait(timeout)
        if not self._over_latch.is_set():
            self.__token_auth_miss_count += 1
            logging.error('Never redirected to /webhp.')


    def get_endpoint_misses(self):
        results = {}
        if (self.__issue_auth_token_miss_count > 0):
            results['issue_auth_token_miss'] =self.__issue_auth_token_miss_count
        if (self.__token_auth_miss_count > 0):
            results['token_auth_miss'] = self.__token_auth_miss_count
        return results


    def client_login_responder(self, handler, url_args):
        logging.debug(url_args)
        handler.send_response(httplib.OK)
        handler.end_headers()
        handler.wfile.write('SID=%s\n' % self.sid)
        handler.wfile.write('LSID=%s\n' % self.lsid)


    def issue_token_responder(self, handler, url_args):
        logging.debug(url_args)
        if url_args['service'].value != constants.LOGIN_SERVICE:
            handler.send_response(httplib.FORBIDDEN)
            handler.end_headers()
            handler.wfile.write(constants.LOGIN_ERROR)
            return

        if not (self.sid == url_args['SID'].value and
                self.lsid == url_args['LSID'].value):
            raise error.TestError('IssueAuthToken called with incorrect args')
        handler.send_response(httplib.OK)
        handler.end_headers()
        handler.wfile.write(self.token)


    def service_login_responder(self, handler, url_args):
        logging.debug(url_args)
        handler.send_response(httplib.OK)
        handler.end_headers()
        handler.wfile.write(self.__service_login_html % {
            'continue': url_args['continue'][0] })


    def token_auth_responder(self, handler, url_args):
        logging.debug(url_args)
        if not self.token == url_args['auth'][0]:
            raise error.TestError('TokenAuth called with incorrect args')
        if not 'continue' in url_args:
            raise error.TestError('TokenAuth called with no continue param')
        handler.send_response(httplib.SEE_OTHER)
        handler.send_header('Location', url_args['continue'][0])
        handler.end_headers()


    def portal_check_responder(self, handler, url_args):
        logging.debug('Handling captive portal check')
        handler.send_response(httplib.NO_CONTENT)
        handler.end_headers()


    def __test_over_responder(self, handler, url_args):
        handler.send_response(httplib.OK)
        handler.end_headers()
