#!/usr/bin/python

import os
import unittest

import common
from autotest_lib.client.common_lib.test_utils import mock
from autotest_lib.client.common_lib import autotemp
from autotest_lib.client.bin import local_host


class test_local_host_class(unittest.TestCase):
    def setUp(self):
        self.god = mock.mock_god()
        self.god.stub_function(local_host.utils, 'run')

        self.tmpdir = autotemp.tempdir(unique_id='localhost_unittest')


    def tearDown(self):
        self.god.unstub_all()
        self.tmpdir.clean()


    def test_init(self):
        self.god.stub_function(local_host.platform, 'node')
        local_host.platform.node.expect_call().and_return('foo')

        # run the actual test
        host = local_host.LocalHost()
        self.assertEqual(host.hostname, 'foo')
        self.god.check_playback()

        host = local_host.LocalHost(hostname='bar')
        self.assertEqual(host.hostname, 'bar')
        self.god.check_playback()


    def test_wait_up(self):
        # just test that wait_up always works
        host = local_host.LocalHost()
        host.wait_up(1)
        self.god.check_playback()


    def _setup_run(self, result):
        host = local_host.LocalHost()

        (local_host.utils.run.expect_call(result.command, timeout=123,
                ignore_status=True, stdout_tee=local_host.utils.TEE_TO_LOGS,
                stderr_tee=local_host.utils.TEE_TO_LOGS, stdin=None,
                ignore_timeout=False, args=())
                .and_return(result))

        return host


    def test_run_success(self):
        result = local_host.utils.CmdResult(command='yes', stdout='y',
                stderr='', exit_status=0, duration=1)

        host = self._setup_run(result)

        self.assertEqual(host.run('yes', timeout=123, ignore_status=True,
                stdout_tee=local_host.utils.TEE_TO_LOGS,
                stderr_tee=local_host.utils.TEE_TO_LOGS, stdin=None), result)
        self.god.check_playback()


    def test_run_failure_raised(self):
        result = local_host.utils.CmdResult(command='yes', stdout='',
                stderr='err', exit_status=1, duration=1)

        host = self._setup_run(result)

        self.assertRaises(local_host.error.AutotestHostRunError, host.run,
                          'yes', timeout=123)
        self.god.check_playback()


    def test_run_failure_ignored(self):
        result = local_host.utils.CmdResult(command='yes', stdout='',
                stderr='err', exit_status=1, duration=1)

        host = self._setup_run(result)

        self.assertEqual(host.run('yes', timeout=123, ignore_status=True),
                         result)
        self.god.check_playback()


    def test_list_files_glob(self):
        host = local_host.LocalHost()

        files = (os.path.join(self.tmpdir.name, 'file1'),
                 os.path.join(self.tmpdir.name, 'file2'))

        # create some files in tmpdir
        open(files[0], 'w').close()
        open(files[1], 'w').close()

        self.assertItemsEqual(
                files,
                host.list_files_glob(os.path.join(self.tmpdir.name, '*')))


    def test_symlink_closure_does_not_add_existent_file(self):
        host = local_host.LocalHost()

        # create a file and a symlink to it
        fname = os.path.join(self.tmpdir.name, 'file')
        sname = os.path.join(self.tmpdir.name, 'sym')
        open(fname, 'w').close()
        os.symlink(fname, sname)

        # test that when the symlinks point to already know files
        # nothing is added
        self.assertItemsEqual(
                [fname, sname],
                host.symlink_closure([fname, sname]))


    def test_symlink_closure_adds_missing_files(self):
        host = local_host.LocalHost()

        # create a file and a symlink to it
        fname = os.path.join(self.tmpdir.name, 'file')
        sname = os.path.join(self.tmpdir.name, 'sym')
        open(fname, 'w').close()
        os.symlink(fname, sname)

        # test that when the symlinks point to unknown files they are added
        self.assertItemsEqual(
                [fname, sname],
                host.symlink_closure([sname]))


    def test_get_file(self):
        """Tests get_file() copying a regular file."""
        host = local_host.LocalHost()

        source_file = os.path.join(self.tmpdir.name, 'file')
        open(os.path.join(source_file), 'w').close()

        dest_file = os.path.join(self.tmpdir.name, 'dest')

        host.get_file(source_file, dest_file)
        self.assertTrue(os.path.isfile(dest_file))


    def test_get_directory_into_new_directory(self):
        """Tests get_file() copying a directory into a new dir."""
        host = local_host.LocalHost()

        source_dir = os.path.join(self.tmpdir.name, 'dir')
        os.mkdir(source_dir)
        open(os.path.join(source_dir, 'file'), 'w').close()

        dest_dir = os.path.join(self.tmpdir.name, 'dest')

        host.get_file(source_dir, dest_dir)

        self.assertTrue(os.path.isfile(os.path.join(dest_dir, 'dir', 'file')))


    def test_get_directory_into_existing_directory(self):
        """Tests get_file() copying a directory into an existing dir."""
        host = local_host.LocalHost()

        source_dir = os.path.join(self.tmpdir.name, 'dir')
        os.mkdir(source_dir)
        open(os.path.join(source_dir, 'file'), 'w').close()

        dest_dir = os.path.join(self.tmpdir.name, 'dest')
        os.mkdir(dest_dir)

        host.get_file(source_dir, dest_dir)

        self.assertTrue(os.path.isfile(os.path.join(dest_dir, 'dir', 'file')))


    def test_get_directory_delete_dest(self):
        """Tests get_file() replacing a dir."""
        host = local_host.LocalHost()

        source_dir = os.path.join(self.tmpdir.name, 'dir')
        os.mkdir(source_dir)
        open(os.path.join(source_dir, 'file'), 'w').close()

        dest_dir = os.path.join(self.tmpdir.name, 'dest')
        os.mkdir(dest_dir)
        os.mkdir(os.path.join(dest_dir, 'dir'))
        open(os.path.join(dest_dir, 'dir', 'file2'), 'w').close()

        host.get_file(source_dir, dest_dir, delete_dest=True)

        self.assertTrue(os.path.isfile(os.path.join(dest_dir, 'dir', 'file')))
        self.assertFalse(os.path.isfile(os.path.join(dest_dir, 'dir', 'file2')))


    def test_get_directory_contents_into_new_directory(self):
        """Tests get_file() copying dir contents to a new dir."""
        host = local_host.LocalHost()

        source_dir = os.path.join(self.tmpdir.name, 'dir')
        os.mkdir(source_dir)
        open(os.path.join(source_dir, 'file'), 'w').close()

        dest_dir = os.path.join(self.tmpdir.name, 'dest')

        # End the source with '/' to copy the contents only.
        host.get_file(os.path.join(source_dir, ''), dest_dir)

        self.assertTrue(os.path.isfile(os.path.join(dest_dir, 'file')))


    def test_get_directory_contents_into_existing_directory(self):
        """Tests get_file() copying dir contents into an existing dir."""
        host = local_host.LocalHost()

        source_dir = os.path.join(self.tmpdir.name, 'dir')
        os.mkdir(source_dir)
        open(os.path.join(source_dir, 'file'), 'w').close()

        dest_dir = os.path.join(self.tmpdir.name, 'dest')
        os.mkdir(dest_dir)

        # End the source with '/' to copy the contents only.
        host.get_file(os.path.join(source_dir, ''), dest_dir)

        self.assertTrue(os.path.isfile(os.path.join(dest_dir, 'file')))


    def test_get_directory_contents_delete_dest(self):
        """Tests get_file() replacing contents of a dir."""
        host = local_host.LocalHost()

        source_dir = os.path.join(self.tmpdir.name, 'dir')
        os.mkdir(source_dir)
        open(os.path.join(source_dir, 'file'), 'w').close()

        dest_dir = os.path.join(self.tmpdir.name, 'dest')
        os.mkdir(dest_dir)
        open(os.path.join(dest_dir, 'file2'), 'w').close()

        # End the source with '/' to copy the contents only.
        host.get_file(os.path.join(source_dir, ''), dest_dir, delete_dest=True)

        self.assertTrue(os.path.isfile(os.path.join(dest_dir, 'file')))
        self.assertFalse(os.path.isfile(os.path.join(dest_dir, 'file2')))


if __name__ == "__main__":
    unittest.main()
