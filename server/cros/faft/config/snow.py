# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""FAFT config setting overrides for Snow."""


class Values(object):
    chrome_ec = True
    ec_capability = (['battery', 'keyboard', 'arm'])
    ec_boot_to_console = 0.4
