# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
import re

from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error
try:
    from autotest_lib.client.common_lib.cros import arc
except ImportError:
    from autotest_lib.client.common_lib.cros import arc_new as arc

_SDCARD_EXEC ='/sdcard/gralloctest'
_EXEC_DIRECTORY = '/data/executables/'
_ANDROID_EXEC = _EXEC_DIRECTORY + 'gralloctest'

class graphics_Gralloc(arc.ArcTest):
    version = 1

    def setup(self):
        os.chdir(self.srcdir)
        utils.make('clean')
        utils.make('all')
        super(graphics_Gralloc, self).setup()

    def initialize(self):
        super(graphics_Gralloc, self).initialize(autotest_ext=True)
        # Get the executable from CrOS and copy it to Android container. Due to
        # weird permission issues inside the container, we first have to copy
        # the test to /sdcard/, then move it to a /data/ subdirectory we create.
        # The permissions on the exectuable have to be modified as well.
        arc.adb_root();
        cmd = os.path.join(self.srcdir, 'gralloctest')
        arc.adb_cmd('-e push %s %s' % (cmd, _SDCARD_EXEC))
        arc._android_shell('mkdir %s' % (_EXEC_DIRECTORY))
        arc._android_shell('mv %s %s' % (_SDCARD_EXEC, _ANDROID_EXEC))
        arc._android_shell('chmod o+rwx %s' % (_ANDROID_EXEC))

    def cleanup(self):
        # Remove test contents from Android container.
        arc._android_shell('rm -rf %s' % (_EXEC_DIRECTORY))

    def run_once(self):
        success = True
        test_names = ['alloc_varying_sizes', 'alloc_usage', 'api',
                      'gralloc_order', 'uninitialized_handle', 'freed_handle',
                      'mapping', 'perform', 'ycbcr', 'async']

        # Run the tests and capture stdout.
        for test_name in test_names:
            stdout = arc._android_shell('%s %s' % (_ANDROID_EXEC, test_name))
            # Look for the regular expression indicating success.
            match = re.search(r'\[  PASSED  \]', stdout)
            if not match:
                success = False
                logging.error(stdout)
            else:
                logging.debug(stdout)

        if not success:
            raise error.TestFail()
