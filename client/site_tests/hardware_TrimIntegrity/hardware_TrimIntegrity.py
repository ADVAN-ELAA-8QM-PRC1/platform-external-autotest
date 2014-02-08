# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging, os, fcntl, struct, random

from autotest_lib.client.bin import test, utils
from autotest_lib.client.common_lib import error


class hardware_TrimIntegrity(test.test):
    """
    Performs data integrity trim test on an unmounted partition.

    This test will write 1 GB of data and verify that trimmed data are gone and
    untrimmed data are unaffected. The verification will be run in 5 passes with
    0%, 25%, 50%, 75%, and 100% of data trimmed.
    """

    version = 1
    FILE_SIZE = 1024 * 1024 * 1024
    CHUNK_SIZE = 64 * 1024
    TRIM_RATIO = [0, 0.25, 0.5, 0.75, 1]

    # Use hash value to check integrity of the random data.
    HASH_CMD = 'sha256sum | cut -d" " -f 1'
    # 0x1277 is ioctl BLKDISCARD command
    IOCTL_TRIM_CMD = 0x1277
    IOCTL_NOT_SUPPORT_ERRNO = 95

    def _find_free_root_partition(self):
        """
        Locate the spare root partition that we didn't boot off.
        """

        spare_root_map = {
            '3': '5',
            '5': '3',
        }
        rootdev = utils.system_output('rootdev -s')
        spare_root = rootdev[:-1] + spare_root_map[rootdev[-1]]
        self._filename = spare_root

    def _get_hash(self, chunk_count, chunk_size):
        """
        Get hash for every chunk of data.
        """
        cmd = str('for i in $(seq 0 %d); do dd if=%s of=/dev/stdout bs=%d'
                  ' count=1 skip=$i iflag=direct | %s; done' %
                  (chunk_count - 1, self._filename, chunk_size, self.HASH_CMD))
        return utils.run(cmd).stdout.split()

    def _do_trim(self, fd, offset, size):
        """
        Invoke ioctl to trim command.
        """
        fcntl.ioctl(fd, self.IOCTL_TRIM_CMD, struct.pack('QQ', offset, size))

    def run_once(self, file_size=FILE_SIZE, chunk_size=CHUNK_SIZE,
                 trim_ratio=TRIM_RATIO):
        """
        Executes the test and logs the output.
        """

        self._find_free_root_partition()

        # Check for trim support in ioctl. Gracefully exit if not support.
        try:
            fd = os.open(self._filename, os.O_RDWR, 0666)
            self._do_trim(fd, 0, chunk_size)
        except IOError, err:
            if err.errno == self.IOCTL_NOT_SUPPORT_ERRNO:
                logging.info("IOCTL Does not support trim.")
                return 0
            else:
                raise
        finally:
            os.close(fd)

        # Write random data to disk
        chunk_count = file_size / chunk_size
        cmd = str('dd if=/dev/urandom of=%s bs=%d count=%d oflag=direct' %
                  (self._filename, chunk_size, chunk_count))
        utils.run(cmd)

        # Calculate hash value for zero'ed and one'ed data
        cmd = str('dd if=/dev/zero of=/dev/stdout bs=%d count=1 | %s' %
                  (chunk_size, self.HASH_CMD))
        zero_hash = utils.run(cmd).stdout.strip()

        cmd = str('dd if=/dev/ibe of=/dev/stdout bs=%d count=1 | %s' %
                  (chunk_size, self.HASH_CMD))
        one_hash = utils.run(cmd).stdout.strip()

        trim_hash = ""

        ref_hash = self._get_hash(chunk_count, chunk_size)

        # Generate random order of chunk to trim
        trim_order = list(range(0, chunk_count))
        random.shuffle(trim_order)
        trim_status = [False] * chunk_size

        # Init stat variable
        data_verify_count = 0
        data_verify_match = 0
        trim_verify_count = 0
        trim_verify_zero = 0
        trim_verify_one = 0
        trim_verify_non_delete = 0
        trim_deterministic = True

        last_ratio = 0
        for ratio in trim_ratio:

            # Do trim
            begin_trim_chunk = int(last_ratio * chunk_count)
            end_trim_chunk = int(ratio * chunk_count)
            fd = os.open(self._filename, os.O_RDWR, 0666)
            for chunk in trim_order[begin_trim_chunk:end_trim_chunk]:
                self._do_trim(fd, chunk * chunk_size, chunk_size)
                trim_status[chunk] = True
            os.close(fd)
            last_ratio = ratio

            cur_hash = self._get_hash(chunk_count, chunk_size)

            trim_verify_count += int(ratio * chunk_count)
            data_verify_count += chunk_count - int(ratio * chunk_count)

            # Verify hash
            for cur, ref, trim in zip(cur_hash, ref_hash, trim_status):
                if trim:
                    if not trim_hash:
                        trim_hash = cur
                    elif cur != trim_hash:
                        trim_deterministic = False

                    if cur == zero_hash:
                        trim_verify_zero += 1
                    elif cur == one_hash:
                        trim_verify_one += 1
                    elif cur == ref:
                        trim_verify_non_delete += 1
                else:
                    if cur == ref:
                        data_verify_match += 1

        keyval = dict()
        keyval['data_verify_count'] = data_verify_count
        keyval['data_verify_match'] = data_verify_match
        keyval['trim_verify_count'] = trim_verify_count
        keyval['trim_verify_zero'] = trim_verify_zero
        keyval['trim_verify_one'] = trim_verify_one
        keyval['trim_verify_non_delete'] = trim_verify_non_delete
        keyval['trim_deterministic'] = trim_deterministic
        self.write_perf_keyval(keyval)

        # Raise error when untrimmed data changed only.
        # Don't care about trimmed data.
        if data_verify_match < data_verify_count:
            error.testFail("Fail to verify untrimmed data.")
        if trim_verify_non_delete > 0 :
            error.testFail("Trimmed data are not deleted.")
