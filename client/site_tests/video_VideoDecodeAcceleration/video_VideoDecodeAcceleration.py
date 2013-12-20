# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os

from autotest_lib.client.bin import test, utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros import chrome


MEDIA_GVD_INIT_STATUS = 'Media.GpuVideoDecoderInitializeStatus'


class video_VideoDecodeAcceleration(test.test):
    """This test verifies VDA works in Chrome."""
    version = 1


    def run_once(self, video_file):
        """Tests whether VDA works by verifying histogram for the loaded video.

        @param video_file: Sample video file to be loaded in Chrome.
        """
        with chrome.Chrome() as cr:
            cr.browser.SetHTTPServerDirectories(self.bindir)
            video_url = cr.browser.http_server.UrlOf(
                    os.path.join(self.bindir, video_file))
            tab1 = cr.browser.tabs[0]
            tab1.Navigate(video_url)
            tab1.WaitForDocumentReadyStateToBeComplete()

            # Waits for histogram updated for the test video.
            tab2 = cr.browser.tabs.New()

            def search_histogram_text(text):
                """Searches the histogram text in the second tab.

                @param text: Text to be searched in the histogram tab.
                """
                return tab2.EvaluateJavaScript('document.documentElement && '
                         'document.documentElement.innerText.search('
                         '\'%s\') != -1' % text)

            def gpu_histogram_loaded():
                """Loads the histogram in the second tab."""
                tab2.Navigate('chrome://histograms/%s' % MEDIA_GVD_INIT_STATUS)
                return search_histogram_text(MEDIA_GVD_INIT_STATUS)

            utils.poll_for_condition(gpu_histogram_loaded,
                    exception=error.TestError(
                            'Histogram gpu status failed to load.'),
                            sleep_interval=1)
            if not search_histogram_text('average = 0.0'):
                raise error.TestError('Video decode acceleration not working.')
