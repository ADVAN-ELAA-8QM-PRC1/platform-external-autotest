# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging, os, shutil
from autotest_lib.client.bin import ui_test, utils
from autotest_lib.client.common_lib import error, site_httpd, site_ui
from autotest_lib.client.cros import ui_test

class graphics_WebGLConformance(ui_test.UITest):
    version = 1


    def initialize(self, creds = '$default'):
        self._test_url = 'http://localhost:8000/webgl-conformance-tests.html'
        self._testServer = site_httpd.HTTPListener(8000, docroot=self.srcdir)
        self._testServer.run()
        ui_test.UITest.initialize(self, creds)


    def setup(self, tarball='webgl-tests-0.0.1.tar.bz2'):
        shutil.rmtree(self.srcdir, ignore_errors=True)

        dst_path = os.path.join(self.bindir, 'WebGL')
        tarball_path = os.path.join(self.bindir, tarball)
        if not os.path.exists(dst_path):
            if not os.path.exists(tarball_path):
                utils.get_file(
                    'http://commondatastorage.googleapis.com/chromeos-localmirror/distfiles/' + tarball,
                     tarball_path)
            utils.extract_tarball_to_dir(tarball_path, dst_path)

        shutil.copytree(os.path.join(self.bindir, 'WebGL'), self.srcdir)
        os.chdir(self.srcdir)
        utils.system('patch -p1 < ../r11002.patch')


    def cleanup(self):
        self._testServer.stop()
        ui_test.UITest.cleanup(self)


    def run_once(self, timeout=300):
        latch = self._testServer.add_wait_url('/WebGL/results')
        session = site_ui.ChromeSession(' --enable-webgl %s' % self._test_url)
        logging.debug('Chrome session started.')
        latch.wait(timeout)
        session.close()

        if not latch.is_set():
            raise error.TestFail('Never received callback from browser.')
        results = self._testServer.get_form_entries()
        total = int(results['total'])
        passed = int(results['pass'])
        if passed < total:
            raise error.TestFail('Results: %d out of %d tests failed!' %
                                 (total - passed, total))
