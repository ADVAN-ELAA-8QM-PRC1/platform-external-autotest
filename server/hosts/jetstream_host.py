# Copyright (c) 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Host object for Jetstream devices.

Host customization provided for fine-tuning autotest reset, verification,
and provisioning on Jetstream devices. A more customized host wrapper is
typicaly used in Jetstream autotests.

This host is not currently probed for in the create_host autodetection logic.

To use this host, the |os_type| host attribute must be set:

  os_type: jetstream

Otherwise, CrosHost will be used for Jetstream devices.

TODO(lgoodby): when known stable, plug this host into the autodection logic.
"""

import logging

import common
from autotest_lib.client.common_lib import error
from autotest_lib.server.hosts import cros_host
from autotest_lib.server.hosts import cros_repair


# Presence of any of these processes indicates that the host is up:
BOOT_DETECTION_PROCESSES = ('ap-controller',)

# Maximum time for host to recover after resetting
RESET_TIMEOUT_SECONDS = 60


class JetstreamHost(cros_host.CrosHost):
    """Jetstream-specific host class."""

    def _initialize(self, *args, **dargs):
        logging.debug('Initializing Jetstream host')
        super(JetstreamHost, self)._initialize(*args, **dargs)
        # Overwrite base class initialization
        self._repair_strategy = cros_repair.create_jetstream_repair_strategy()

    def get_os_type(self):
        return 'jetstream'

    def get_wait_up_processes(self):
        return BOOT_DETECTION_PROCESSES

    def cleanup_services(self):
        """Restores the host to default settings.

        @raises AutoservRunError: on failure.
        """
        logging.debug('Jetstream: Resetting AP services')
        # This is a 'fake' factory reset which restores the DUT to
        # its default state and restarts AP services.
        self.run('sudo ap-configure --factory_reset', ignore_status=False)
        self.wait_up(timeout=RESET_TIMEOUT_SECONDS)

        # Stop service ap-update-manager to prevent rebooting during autoupdate.
        self.run('sudo stop ap-update-manager', ignore_status=False)

    def prepare_for_update(self):
        """Prepare the host for an update."""
        logging.debug('Jetstream: Prepare for update')
        try:
            self.cleanup_services()
        except AutoservRunError:
            logging.exception('Failed to reset host')
