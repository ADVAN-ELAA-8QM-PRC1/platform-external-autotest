# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging

from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib import global_config
from autotest_lib.client.common_lib.cros import dev_server
from autotest_lib.server import test
from autotest_lib.server.cros import provision


_CONFIG = global_config.global_config
# pylint: disable-msg=E1120
_IMAGE_URL_PATTERN = _CONFIG.get_config_value(
        'CROS', 'image_url_pattern', type=str)


class provision_AutoUpdate(test.test):
    """A test that can provision a machine to the correct ChromeOS version."""
    version = 1

    def initialize(self, host, value, force=False):
        """Initialize."""
        # We check value in initialize so that it fails faster.
        if not value:
            raise error.TestFail('No build version specified.')


    def run_once(self, host, value, force=False):
        """The method called by the control file to start the test.

        @param host: The host object to update to |value|.
        @param value: The build type and version to install on the host.
        @param force: If False, will only provision the host if it is not
                      already running the build. If True, force the
                      provisioning regardless, and force a full-reimage.

        """
        logging.debug('Start provisioning %s to %s', host, value)
        image = value

        # If the host is already on the correct build, we have nothing to do.
        # Note that this means we're not doing any sort of stateful-only
        # update, and that we're relying more on cleanup to do cleanup.
        # We could just not pass |force_update=True| to |machine_install|,
        # but I'd like the semantics that a provision test 'returns' TestNA
        # if the machine is already properly provisioned.
        if not force and host.get_build() == value:
            # We can't raise a TestNA, as would make sense, as that makes
            # job.run_test return False as if the job failed.  However, it'd
            # still be nice to get this into the status.log, so we manually
            # emit an INFO line instead.
            self.job.record('INFO', None, None,
                            'Host already running %s' % value)
            return

        # We're about to reimage a machine, so we need full_payload and
        # stateful.  If something happened where the devserver doesn't have one
        # of these, then it's also likely that it'll be missing autotest.
        # Therefore, we require the devserver to also have autotest staged, so
        # that the test that runs after this provision finishes doesn't error
        # out because the devserver that its job_repo_url is set to is missing
        # autotest test code.
        # TODO(milleral): http://crbug.com/249426
        # Add an asynchronous staging call so that we can ask the devserver to
        # fetch autotest in the background here, and then wait on it after
        # reimaging finishes or at some other point in the provisioning.
        try:
            ds = dev_server.ImageServer.resolve(image)
            ds.stage_artifacts(image, ['full_payload', 'stateful',
                                       'autotest_packages'])
        except dev_server.DevServerException as e:
            raise error.TestFail(str(e))

        url = _IMAGE_URL_PATTERN % (ds.url(), image)

        logging.debug('Installing image')
        try:
            host.machine_install(force_update=True, update_url=url,
                                 force_full_update=force)
        except error.InstallError as e:
            logging.error(e)
            raise error.TestFail(str(e))
        build = host.get_build()
        if build != value:
            raise error.TestFail(
                    'Expected cros-version label of %s in AFE, but found %s' %
                    (value, build))
        logging.debug('Finished provisioning %s to %s', host, value)
