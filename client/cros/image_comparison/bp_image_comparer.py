# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging, time
from autotest_lib.client.cros.image_comparison import bp_http_client
from autotest_lib.client.cros.video import method_logger


class BpImageComparer(object):
    """
    Encapsulates the BioPic image comparison strategy.

    """


    @method_logger.log
    def __init__(self, project_name, contact_email, wait_time_btwn_comparisons,
                 retries=0):
        """
        Initializes the underlying bp client.

        @param project_name: string, name of test run project to view results.
        @param contact_email: string, email to receive test results on failure.
        @param wait_time_btwn_comparisons: int, time in seconds to wait between
                                           two consecutive pair of calls to
                                           upload reference and test images.
                                           If we upload without a break, biopic
                                           server could get overwhelmed and
                                           throw an exception.
        @param retries: int, number of times to retry upload before giving up.

        """
        self.bp_client = bp_http_client.BiopicClient(project_name)
        self.test_run = self.bp_client.CreateTestRun(contact_email)
        self.wait_time_btwn_comparisons = wait_time_btwn_comparisons
        self.retries = retries


    def __enter__(self):
        """
         Enables BpImageComparer to be used with the 'with' construct.

         Using this class with the 'with' construct guarantees EndTestRun will
         be called.

         @returns this current object.

        """
        return self


    def _upload_image_with_retry(self, bp_upload_function, image_path, retries):
        """
        Uploads a golden image or run image to biopic, retries on upload fail.

        @param bp_upload_function: Function to call to upload either the golden
                                   or test image.
        @param image_path: path, complete path to the image.
        @param retries: number of times to retry uploading before giving up.
                        NOTE: if retries = 1 that means we will upload the first
                        time if that fails we will retry once bringing the total
                        number of upload tries to TWO (2)..
        @throws: Whatever exception biopic threw if no more retries are left.
        """

        while True:

            try:
                res = bp_upload_function(self.id, image_path)
                return res  # Great Success!!

            except bp_http_client.BiopicClientError as e:
                e.message = ("BiopicClientError thrown while uploading file %s."
                             "Original message: %s" % (image_path, e.message))

                logging.debug(e)
                logging.debug("RETRY LEFT : %d", retries)

                if retries == 0:
                    raise

                retries -= 1


    @property
    def id(self):
        """
        Returns the id of the testrun.

        """
        return self.test_run['testrun_id']


    @method_logger.log
    def compare(self, golden_image_path, test_run_image_path, box=None,
                retries=None):
        """
        Compares a test image with a known reference image.

        Uses http_client interface to communicate with biopic service.

        @param golden_image_path: path, complete path to a golden image.
        @param test_run_image_path: path, complete path to a test run image.
        @param box: int tuple, left, upper, right, lower pixel coordinates
                    defining a box region within which the comparison is made.
        @param retries: int, number of times to retry before giving up.
                        This is configured at object creation but test can
                        override the configured value at method call..

        @raises whatever biopic http interface raises.

        @returns: int, num of differing pixels. Right now just -1 as we do not
                       have a way to extract this from biopic.

        """

        logging.debug("*** Beginning Biopic Upload ... **** \n")
        
        if not retries:
            retries = self.retries

        rs = self._upload_image_with_retry(self.bp_client.UploadGoldenImage,
                                           golden_image_path,
                                           retries)

        logging.debug(rs)

        rs = self._upload_image_with_retry(self.bp_client.UploadRunImage,
                                           test_run_image_path,
                                           retries)

        logging.debug(rs)

        time.sleep(self.wait_time_btwn_comparisons)

        logging.debug("*** Biopic Upload COMPLETED. **** \n")

        # We don't have a way to get back the pixel different number from bp
        # just return -1

        return -1


    def complete(self):
        """
        Completes the test run.

        Biopic service requires its users to end the test run when finished.

        """
        self.bp_client.EndTestRun(self.id)


    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Ends the test run. Meant to be used with the 'with' construct.

        """
        self.complete()
