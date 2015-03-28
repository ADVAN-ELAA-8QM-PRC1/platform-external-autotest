#!/usr/bin/python

# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import logging.handlers

import common
from autotest_lib.client.common_lib.cros import xmlrpc_server
from autotest_lib.client.cros import dark_resume_listener
from autotest_lib.client.cros import sys_power


SERVER_PORT = 9993
SERVER_COMMAND = ('cd /usr/local/autotest/common_lib/cros; '
           './dark_resume_xmlrpc_server.py')
CLEANUP_PATTERN = 'dark_resume_xmlrpc_server'
READY_METHOD = 'ready'


class DarkResumeXmlRpcDelegate(xmlrpc_server.XmlRpcDelegate):
    """Exposes methods called remotely during dark resume autotests.

    All instance methods of this object without a preceding '_' are exposed via
    an XMLRPC server.  This is not a stateless handler object, which means that
    if you store state inside the delegate, that state will remain around for
    future calls.

    """

    def __init__(self):
        super(DarkResumeXmlRpcDelegate, self).__init__()
        self._listener = dark_resume_listener.DarkResumeListener()


    @xmlrpc_server.dbus_safe(None)
    def suspend_bg_for_dark_resume(self):
        """Suspends this system indefinitely for dark resume."""
        sys_power.suspend_bg_for_dark_resume()


    @xmlrpc_server.dbus_safe(0)
    def get_dark_resume_count(self):
        """Gets the number of dark resumes that have occurred since
        this listener was created."""
        return self._listener.count


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    handler = logging.handlers.SysLogHandler(address = '/dev/log')
    formatter = logging.Formatter(
            'dark_resume_xmlrpc_server: [%(levelname)s] %(message)s')
    handler.setFormatter(formatter)
    logging.getLogger().addHandler(handler)
    logging.debug('dark_resume_xmlrpc_server main...')
    server = xmlrpc_server.XmlRpcServer(
            'localhost', SERVER_PORT)
    server.register_delegate(DarkResumeXmlRpcDelegate())
    server.run()
