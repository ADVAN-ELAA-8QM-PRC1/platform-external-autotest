# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
from autotest_lib.client.bin import base_partition, os_dep, test
from autotest_lib.client.common_lib import error, utils, site_verity

class platform_DMVerityCorruption(site_verity.VerityImageTest):
    version = 1

    def mod_zerofill_block(self, run_count, backing_path, block_size,
                           block_count):
        logging.info('mod_zerofill_block(%d, %s, %d, %d)' % (
                     run_count, backing_path, block_size, block_count))
        dd_cmd = 'dd if=/dev/zero of=%s bs=%d seek=%d count=1'
        run_count = run_count % block_count
        utils.system(dd_cmd % (backing_path, block_size, run_count))

    def mod_Afill_hash_block(self, run_count, backing_path, block_size,
                             block_count):
        logging.info('mod_Afill_hash_block(%d, %s, %d, %d)' % (
                     run_count, backing_path, block_size, block_count))
        with open(backing_path, 'wb') as dev:
          dev.seek(block_count * block_size, os.SEEK_CUR)
          dev.seek(run_count * 4096, os.SEEK_CUR)
          dev.write('A' * 4096)

    def run_once(self):
        # If dm-verity has a different error_behavior specified, then
        # running this may result in a reboot or invalid test responses.
        if self.verity.error_behavior != site_verity.ERROR_BEHAVIOR_ERROR:
            raise error.TestFail('unexpected error_behavior parameter: %d' %
                                  self.verity.error_behavior)

        # Ensure that basic verification is working.
        # This should NOT fail.
        self.mod_and_test(self.mod_nothing, 1, True)

        # Corrupt the image once per block (on a per-block basis).
        self.mod_and_test(self.mod_zerofill_block, self.image_blocks, False)

        # Repeat except each block in the hash tree data
        hash_blocks = (os.path.getsize(self.verity.hash_file) /
                       site_verity.BLOCK_SIZE)
        self.mod_and_test(self.mod_Afill_hash_block, hash_blocks, False)

        # TODO(wad) Repeat except one bit in each block
