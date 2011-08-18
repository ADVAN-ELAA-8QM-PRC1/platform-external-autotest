# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging, os, shutil, urllib
from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros import cros_ui, cros_ui_test, httpd

class graphics_WebGLConformance(cros_ui_test.UITest):
    version = 1

    # TODO(ihf) not all tests are passing now, maintain this
    # list was assembled on mario but should be a superset
    # of all failing configurations
    waived_tests = {
        'conformance/canvas-test.html' : 1,
        'conformance/context-lost-restored.html' : 2,
        'conformance/copy-tex-image-and-sub-image-2d.html' : 34,
        'conformance/draw-arrays-out-of-bounds.html' : 36,
        'conformance/error-reporting.html' : 6,
        'conformance/gl-clear.html' : 4,
        'conformance/gl-drawelements.html' : 1,
        'conformance/gl-enable-vertex-attrib.html' : 1,
        'conformance/gl-object-get-calls.html' : 2,
        'conformance/gl-teximage.html' : 46,
        'conformance/gl-uniform-arrays.html' : 2,
        'conformance/gl-uniform-bool.html' : 1,
        'conformance/gl-uniformmatrix4fv.html' : 1,
        'conformance/gl-unknown-uniform.html' : 1,
        'conformance/glsl-conformance.html' : 1,
        'conformance/more/conformance/webGLArrays.html' : 1,
        'conformance/more/functions/copyTexSubImage2D.html' : 1,
        'conformance/more/functions/readPixelsBadArgs.html' : 1,
        'conformance/more/glsl/arrayOutOfBounds.html' : 1,
        'conformance/point-size.html' : 1,
        'conformance/premultiplyalpha-test.html' : 10,
        'conformance/read-pixels-pack-alignment.html' : 2,
        'conformance/read-pixels-test.html' : 28,
        'conformance/tex-image-and-sub-image-2d-with-array-buffer-view.html'
                                            : 192,
        'conformance/tex-image-and-sub-image-2d-with-image-data.html' : 16,
        'conformance/tex-image-and-sub-image-2d-with-image.html' : 8,
        'conformance/tex-image-and-sub-image-2d-with-video.html' : 8,
        'conformance/tex-image-with-format-and-type.html' : 12,
        'conformance/texture-active-bind.html' : 4,
        'conformance/texture-complete.html' : 1,
        'conformance/texture-formats-test.html' : 4,
        'conformance/texture-npot.html' : 12,
        'conformance/triangle.html' : 1
      }

    def initialize(self, creds='$default'):
        self._test_url = 'http://localhost:8000/webgl-conformance-tests.html'
        self._testServer = httpd.HTTPListener(8000, docroot=self.srcdir)
        self._testServer.run()
        cros_ui_test.UITest.initialize(self, creds,
                                       extra_chrome_flags=['--enable-webgl'])

    def setup(self, tarball='webgl-conformance-1.0.0.tar.bz2'):
        shutil.rmtree(self.srcdir, ignore_errors=True)
        tarball_path = os.path.join(self.bindir, tarball)
        if not os.path.exists(self.srcdir):
            if not os.path.exists(tarball_path):
                utils.get_file(
                    'http://commondatastorage.googleapis.com/'
                    'chromeos-localmirror/distfiles/' + tarball,
                    tarball_path)
            utils.extract_tarball_to_dir(tarball_path, self.srcdir)
        os.chdir(self.srcdir)
        utils.system('patch -p1 < ../webgl-conformance-1.0.0.patch')

    def cleanup(self):
        self._testServer.stop()
        cros_ui_test.UITest.cleanup(self)

    def run_once(self, timeout=300):
        # TODO(ihf) remove when stable. for now we have to expect crashes
        self.crash_blacklist.append('chrome')
        self.crash_blacklist.append('chromium')

        latch = self._testServer.add_wait_url('/WebGL/results')
        # Loading the url might take longer than pyauto automation timeout.
        # Temporarily increment pyauto timeout.
        pyauto_timeout_changer = self.pyauto.ActionTimeoutChanger(
            self.pyauto, timeout * 1000)
        logging.info('Going to %s' % self._test_url)
        self.pyauto.NavigateToURL(self._test_url)
        del pyauto_timeout_changer
        latch.wait(timeout)

        if not latch.is_set():
            raise error.TestFail('Timeout after ' + timeout +
                  ' seconds - never received callback from browser.')

        # receive data from webgl-conformance-tests.html::postFinalResults
        results = self._testServer.get_form_entries()
        groups_total  = int(results['gtotal'])
        groups_pass   = int(results['gpass'])
        groups_fail   = groups_total - groups_pass
        tests_total   = int(results['ttotal'])
        tests_pass    = int(results['tpass'])
        tests_timeout = int(results['ttimeout'])
        tests_fail    = tests_total - tests_pass

        logging.info('WebGLConformance: %d groups pass',   groups_pass)
        logging.info('WebGLConformance: %d groups fail',   groups_fail)
        logging.info('WebGLConformance: %d tests pass',    tests_pass)
        logging.info('WebGLConformance: %d tests fail',    tests_fail)
        logging.info('WebGLConformance: %d tests timeout', tests_timeout)

        # output numbers for plotting by harness
        keyvals = {}
        keyvals['count_tests_pass']    = tests_pass
        keyvals['count_tests_fail']    = tests_fail
        keyvals['count_tests_timeout'] = tests_timeout

        # handle failed groups/urls and apply waivers
        failTestRun = False
        i = 0
        for key in results:
            unquote_key = urllib.unquote_plus(key)
            if unquote_key.startswith('failed_url:'):
                new_key = "waived_url_%03d" % i
                failures = int(results[key])
                url = unquote_key[11:]
                waived_failures = 0
                if url in self.waived_tests:
                    waived_failures = self.waived_tests[url]
                if failures > waived_failures:
                    failTestRun = True
                    new_key = "failed_url_%03d" % i
                message = url + " : %d failures (%d waived)"\
                                   % (failures, waived_failures)
                keyvals[new_key] = message
                logging.info(new_key + "   " + message)
                i = i+1
        self.write_perf_keyval(keyvals)

        # write transmitted summary to graphics_WebGLConformance/summary.txt
        summary = urllib.unquote_plus(results['summary'])
        logging.info('\n' + summary)
        results_path = os.path.join(self.bindir,
              "../../results/default/graphics_WebGLConformance/summary.txt")
        f = open(results_path, 'w+')
        f.write(summary)
        f.close()

        # if we saw failures that were not waived raise an error now
        # TODO(ihf) remove < 5000 when things become more stable
        if failTestRun and tests_pass < 5000:
            raise error.TestFail('Results: saw failures without waivers. ')


