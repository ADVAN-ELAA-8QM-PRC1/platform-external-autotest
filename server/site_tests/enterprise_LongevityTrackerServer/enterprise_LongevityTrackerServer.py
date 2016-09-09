# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# pylint: disable=invalid-name
# pylint: disable=missing-docstring
# pylint: disable=module-missing-docstring
# pylint: disable=docstring-section-name
# pylint: disable=no-init

import os
import shutil

from autotest_lib.client.common_lib.cros import tpm_utils
from autotest_lib.server import afe_utils
from autotest_lib.server import autotest
from autotest_lib.server import site_utils
from autotest_lib.server import test


class enterprise_LongevityTrackerServer(test.test):
    """Run Longevity Test: Collect performance data over long duration.

    Run enterprise_KioskEnrollment and clear the TPM as necessary. After
    enterprise enrollment is successful, collect and log cpu, memory, and
    temperature data from the device under test.
    """
    version = 1

    CLIENT_RESULTS_PATH = 'longevity_Tracker/results/'

    def copy_results_files_to_server(self):
        host_results = os.path.join(
                os.path.dirname(self.resultsdir),
                self.CLIENT_RESULTS_PATH)
        result_files = os.listdir(host_results)
        for file_name in result_files:
            full_file_name = os.path.join(host_results, file_name)
            if os.path.isfile(full_file_name):
                shutil.copy(full_file_name, self.resultsdir)

    def run_once(self, host=None, kiosk_app_attributes=None):
        self.client = host
        app_config_id = None
        tpm_utils.ClearTPMOwnerRequest(self.client)

        app_config_id = site_utils.get_label_from_afe(
                self.client.hostname, 'app_config_id', afe_utils.AFE)
        if app_config_id and app_config_id.startswith(':'):
            app_config_id = app_config_id[1:]
        autotest.Autotest(self.client).run_test(
                'enterprise_KioskEnrollment',
                kiosk_app_attributes=kiosk_app_attributes,
                app_config_id=app_config_id,
                check_client_result=True)

        for cycle in range(5):
            autotest.Autotest(self.client).run_test(
                    'longevity_Tracker',
                    kiosk_app_attributes=kiosk_app_attributes,
                    check_client_result=True)
        self.copy_results_files_to_server()

        tpm_utils.ClearTPMOwnerRequest(self.client)
