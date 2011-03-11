# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""WiFiManager is a suite of 3-machine tests to validate basic WiFi
functionality.  One client, one server, and one programmable WiFi AP/Router
are required (either off-the-shelf with a network-accesible CLI or a
Linux/BSD system with a WiFi card that supports HostAP functionality).

Configuration information to run_test:

server     - the IP address of the server (automatically filled in)
client     - the IP address of the client (automatically filled in)
router     - the IP address of the WiFi AP/Router and the names of the
             wifi and wired devices to configure
"""

from autotest_lib.server import site_wifitest

class network_WiFiManager(site_wifitest.test):
      pass
