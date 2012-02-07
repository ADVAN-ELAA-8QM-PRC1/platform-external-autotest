# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

if __name__ == '__main__':
    import os, sys
    sys.path.append(
        os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    import common


import tempfile
import thread
import time
import unittest

# Set the factory log root so that we can watch it.
log_root = os.environ['CROS_FACTORY_LOG_ROOT'] = tempfile.mkdtemp()
console_log_path = os.path.join(log_root, "console.log")

from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros.rf.config import PluggableConfig


TIMEOUT_SEC = 3


class PluggableConfigTestCase(unittest.TestCase):
    def assertInRange(self, value, min, max):
        assert min <= max
        self.assertTrue(value >= min and value <= max,
                        '%s not in range [%s,%s]' % (value, min, max))

    def testPathExists(self):
        tmp = tempfile.NamedTemporaryFile()
        print >>tmp, '12345'
        tmp.flush()

        self.assertEqual(12345,
                         PluggableConfig('').Read(config_path=tmp.name))

        self.assertEqual(
            ["[INFO] Waiting for test configuration file %r...\n" % tmp.name,
             "[INFO] Read test configuration file %r\n" % tmp.name],
            open(console_log_path).readlines()[-2:])

    def testPathDoesntExist(self):
        start = time.time()
        self.assertRaises(
            utils.TimeoutError,
            PluggableConfig('').Read,
            '/file-that-does-not-exist', timeout=TIMEOUT_SEC)
        self.assertInRange(time.time() - start,
                           TIMEOUT_SEC - 1, TIMEOUT_SEC + 1)

    def testWaitForPath(self):
        tmp_fd, tmp_path = tempfile.mkstemp()
        os.close(tmp_fd)
        os.unlink(tmp_path)

        delay = TIMEOUT_SEC / 2.0
        def CreateFile():
            time.sleep(delay)
            with open(tmp_path, "w") as tmp:
                print >>tmp, '12345'

        thread.start_new_thread(CreateFile, ())

        start = time.time()
        self.assertEqual(
            12345,
            PluggableConfig('').Read(config_path=tmp_path, timeout=TIMEOUT_SEC))
        # Check that 'delay' seconds have passed, +/-1 second.
        self.assertInRange(time.time() - start,
                           delay - 1, delay + 1)


if __name__ == "__main__":
    unittest.main()
