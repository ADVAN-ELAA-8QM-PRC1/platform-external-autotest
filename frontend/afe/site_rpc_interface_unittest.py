#!/usr/bin/python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Unit tests for frontend/afe/site_rpc_interface.py."""


import __builtin__
import ConfigParser
import mox
import StringIO
import unittest

import common

from autotest_lib.frontend import setup_django_environment
from autotest_lib.frontend.afe import frontend_test_utils
from autotest_lib.frontend.afe import models, rpc_utils
from autotest_lib.client.common_lib import control_data, error
from autotest_lib.client.common_lib import global_config
from autotest_lib.client.common_lib import priorities
from autotest_lib.client.common_lib.cros import dev_server
from autotest_lib.frontend.afe import rpc_interface, site_rpc_interface
from autotest_lib.server import utils
from autotest_lib.server.cros.dynamic_suite import control_file_getter
from autotest_lib.server.cros.dynamic_suite import constants


CLIENT = control_data.CONTROL_TYPE_NAMES.CLIENT
SERVER = control_data.CONTROL_TYPE_NAMES.SERVER


class SiteRpcInterfaceTest(mox.MoxTestBase,
                           frontend_test_utils.FrontendTestMixin):
    """Unit tests for functions in site_rpc_interface.py.

    @var _NAME: fake suite name.
    @var _BOARD: fake board to reimage.
    @var _BUILD: fake build with which to reimage.
    @var _PRIORITY: fake priority with which to reimage.
    """
    _NAME = 'name'
    _BOARD = 'link'
    _BUILD = 'link-release/R36-5812.0.0'
    _PRIORITY = priorities.Priority.DEFAULT
    _TIMEOUT = 24


    def setUp(self):
        super(SiteRpcInterfaceTest, self).setUp()
        self._SUITE_NAME = site_rpc_interface.canonicalize_suite_name(
            self._NAME)
        self.dev_server = self.mox.CreateMock(dev_server.ImageServer)
        self._frontend_common_setup(fill_data=False)


    def tearDown(self):
        self._frontend_common_teardown()


    def _setupDevserver(self):
        self.mox.StubOutClassWithMocks(dev_server, 'ImageServer')
        dev_server.ImageServer.resolve(self._BUILD).AndReturn(self.dev_server)


    def _mockDevServerGetter(self, get_control_file=True):
        self._setupDevserver()
        if get_control_file:
          self.getter = self.mox.CreateMock(
              control_file_getter.DevServerGetter)
          self.mox.StubOutWithMock(control_file_getter.DevServerGetter,
                                   'create')
          control_file_getter.DevServerGetter.create(
              mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(self.getter)


    def _mockRpcUtils(self, to_return, control_file_substring=''):
        """Fake out the autotest rpc_utils module with a mockable class.

        @param to_return: the value that rpc_utils.create_job_common() should
                          be mocked out to return.
        @param control_file_substring: A substring that is expected to appear
                                       in the control file output string that
                                       is passed to create_job_common.
                                       Default: ''
        """
        download_started_time = constants.DOWNLOAD_STARTED_TIME
        payload_finished_time = constants.PAYLOAD_FINISHED_TIME
        self.mox.StubOutWithMock(rpc_utils, 'create_job_common')
        rpc_utils.create_job_common(mox.And(mox.StrContains(self._NAME),
                                    mox.StrContains(self._BUILD)),
                            priority=self._PRIORITY,
                            timeout_mins=self._TIMEOUT*60,
                            max_runtime_mins=self._TIMEOUT*60,
                            control_type='Server',
                            control_file=mox.And(mox.StrContains(self._BOARD),
                                                 mox.StrContains(self._BUILD),
                                                 mox.StrContains(
                                                     control_file_substring)),
                            hostless=True,
                            keyvals=mox.And(mox.In(download_started_time),
                                            mox.In(payload_finished_time))
                            ).AndReturn(to_return)


    def testStageBuildFail(self):
        """Ensure that a failure to stage the desired build fails the RPC."""
        self._setupDevserver()
        self.dev_server.stage_artifacts(
            self._BUILD, ['test_suites']).AndRaise(
                dev_server.DevServerException())
        self.mox.ReplayAll()
        self.assertRaises(error.StageBuildFailure,
                          site_rpc_interface.create_suite_job,
                          self._NAME,
                          self._BOARD,
                          self._BUILD,
                          None)


    def testGetControlFileFail(self):
        """Ensure that a failure to get needed control file fails the RPC."""
        self._mockDevServerGetter()
        self.dev_server.stage_artifacts(self._BUILD,
                                        ['test_suites']).AndReturn(True)
        self.getter.get_control_file_contents_by_name(
            self._SUITE_NAME).AndReturn(None)
        self.mox.ReplayAll()
        self.assertRaises(error.ControlFileEmpty,
                          site_rpc_interface.create_suite_job,
                          self._NAME,
                          self._BOARD,
                          self._BUILD,
                          None)


    def testGetControlFileListFail(self):
        """Ensure that a failure to get needed control file fails the RPC."""
        self._mockDevServerGetter()
        self.dev_server.stage_artifacts(self._BUILD,
                                        ['test_suites']).AndReturn(True)
        self.getter.get_control_file_contents_by_name(
            self._SUITE_NAME).AndRaise(error.NoControlFileList())
        self.mox.ReplayAll()
        self.assertRaises(error.NoControlFileList,
                          site_rpc_interface.create_suite_job,
                          self._NAME,
                          self._BOARD,
                          self._BUILD,
                          None)


    def testBadNumArgument(self):
        """Ensure we handle bad values for the |num| argument."""
        self.assertRaises(error.SuiteArgumentException,
                          site_rpc_interface.create_suite_job,
                          self._NAME,
                          self._BOARD,
                          self._BUILD,
                          None,
                          num='goo')
        self.assertRaises(error.SuiteArgumentException,
                          site_rpc_interface.create_suite_job,
                          self._NAME,
                          self._BOARD,
                          self._BUILD,
                          None,
                          num=[])
        self.assertRaises(error.SuiteArgumentException,
                          site_rpc_interface.create_suite_job,
                          self._NAME,
                          self._BOARD,
                          self._BUILD,
                          None,
                          num='5')



    def testCreateSuiteJobFail(self):
        """Ensure that failure to schedule the suite job fails the RPC."""
        self._mockDevServerGetter()
        self.dev_server.stage_artifacts(self._BUILD,
                                        ['test_suites']).AndReturn(True)
        self.dev_server.url().AndReturn('mox_url')
        self.getter.get_control_file_contents_by_name(
            self._SUITE_NAME).AndReturn('f')
        self._mockRpcUtils(-1)
        self.mox.ReplayAll()
        self.assertEquals(
            site_rpc_interface.create_suite_job(name=self._NAME,
                                                board=self._BOARD,
                                                build=self._BUILD, pool=None),
            -1)


    def testCreateSuiteJobSuccess(self):
        """Ensures that success results in a successful RPC."""
        self._mockDevServerGetter()
        self.dev_server.stage_artifacts(self._BUILD,
                                        ['test_suites']).AndReturn(True)
        self.dev_server.url().AndReturn('mox_url')
        self.getter.get_control_file_contents_by_name(
            self._SUITE_NAME).AndReturn('f')
        job_id = 5
        self._mockRpcUtils(job_id)
        self.mox.ReplayAll()
        self.assertEquals(
            site_rpc_interface.create_suite_job(name=self._NAME,
                                                board=self._BOARD,
                                                build=self._BUILD,
                                                pool=None),
            job_id)


    def testCreateSuiteJobNoHostCheckSuccess(self):
        """Ensures that success results in a successful RPC."""
        self._mockDevServerGetter()
        self.dev_server.stage_artifacts(self._BUILD,
                                        ['test_suites']).AndReturn(True)
        self.dev_server.url().AndReturn('mox_url')
        self.getter.get_control_file_contents_by_name(
            self._SUITE_NAME).AndReturn('f')
        job_id = 5
        self._mockRpcUtils(job_id)
        self.mox.ReplayAll()
        self.assertEquals(
          site_rpc_interface.create_suite_job(name=self._NAME,
                                              board=self._BOARD,
                                              build=self._BUILD,
                                              pool=None, check_hosts=False),
          job_id)

    def testCreateSuiteIntegerNum(self):
        """Ensures that success results in a successful RPC."""
        self._mockDevServerGetter()
        self.dev_server.stage_artifacts(self._BUILD,
                                        ['test_suites']).AndReturn(True)
        self.dev_server.url().AndReturn('mox_url')
        self.getter.get_control_file_contents_by_name(
            self._SUITE_NAME).AndReturn('f')
        job_id = 5
        self._mockRpcUtils(job_id, control_file_substring='num=17')
        self.mox.ReplayAll()
        self.assertEquals(
            site_rpc_interface.create_suite_job(name=self._NAME,
                                                board=self._BOARD,
                                                build=self._BUILD,
                                                pool=None,
                                                check_hosts=False,
                                                num=17),
            job_id)


    def testCreateSuiteJobControlFileSupplied(self):
        """Ensure we can supply the control file to create_suite_job."""
        self._mockDevServerGetter(get_control_file=False)
        self.dev_server.stage_artifacts(self._BUILD,
                                        ['test_suites']).AndReturn(True)
        self.dev_server.url().AndReturn('mox_url')
        job_id = 5
        self._mockRpcUtils(job_id)
        self.mox.ReplayAll()
        self.assertEquals(
            site_rpc_interface.create_suite_job(name='%s/%s' % (self._NAME,
                                                                self._BUILD),
                                                board=None,
                                                build=self._BUILD,
                                                pool=None,
                                                control_file='CONTROL FILE'),
            job_id)


    def setIsMoblab(self, is_moblab):
        """Set utils.is_moblab result.

        @param is_moblab: Value to have utils.is_moblab to return.
        """
        self.mox.StubOutWithMock(utils, 'is_moblab')
        utils.is_moblab().AndReturn(is_moblab)


    def testMoblabOnlyDecorator(self):
        """Ensure the moblab only decorator gates functions properly."""
        self.setIsMoblab(False)
        self.mox.ReplayAll()
        self.assertRaises(error.RPCException,
                          site_rpc_interface.get_config_values)


    def testGetConfigValues(self):
        """Ensure that the config object is properly converted to a dict."""
        self.setIsMoblab(True)
        config_mock = self.mox.CreateMockAnything()
        site_rpc_interface._CONFIG = config_mock
        config_mock.get_sections().AndReturn(['section1', 'section2'])
        config_mock.config = self.mox.CreateMockAnything()
        config_mock.config.items('section1').AndReturn([('item1', 'value1'),
                                                        ('item2', 'value2')])
        config_mock.config.items('section2').AndReturn([('item3', 'value3'),
                                                        ('item4', 'value4')])

        rpc_utils.prepare_for_serialization(
            {'section1' : [('item1', 'value1'),
                           ('item2', 'value2')],
             'section2' : [('item3', 'value3'),
                           ('item4', 'value4')]})
        self.mox.ReplayAll()
        site_rpc_interface.get_config_values()


    def testUpdateConfig(self):
        """Ensure that updating the config works as expected."""
        self.setIsMoblab(True)
        # Reset the config.
        site_rpc_interface._CONFIG = global_config.global_config
        site_rpc_interface._CONFIG.shadow_file = 'fake_shadow'
        site_rpc_interface._CONFIG.config = ConfigParser.ConfigParser()
        site_rpc_interface._CONFIG.config.add_section('section1')
        site_rpc_interface._CONFIG.config.add_section('section2')
        site_rpc_interface.os = self.mox.CreateMockAnything()
        site_rpc_interface.os.path = self.mox.CreateMockAnything()
        site_rpc_interface.os.path.exists(
                site_rpc_interface._CONFIG.shadow_file).AndReturn(
                True)

        self.mox.StubOutWithMock(__builtin__, 'open')
        mockFile = self.mox.CreateMockAnything()
        file_contents = StringIO.StringIO()
        mockFile.__enter__().AndReturn(file_contents)
        mockFile.__exit__(mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg())
        open(site_rpc_interface._CONFIG.shadow_file, 'w').AndReturn(mockFile)

        site_rpc_interface.os.system('sudo reboot')
        self.mox.ReplayAll()
        site_rpc_interface.update_config_handler(
                {'section1' : [('item1', 'value1'),
                               ('item2', 'value2')],
                 'section2' : [('item3', 'value3'),
                               ('item4', 'value4')]})
        self.assertEquals(
                file_contents.getvalue(),
                '[section1]\nitem1 = value1\nitem2 = value2\n\n'
                '[section2]\nitem3 = value3\nitem4 = value4\n\n')


    def testResetConfig(self):
        """Ensure that reset opens the shadow_config file for writing."""
        self.setIsMoblab(True)
        config_mock = self.mox.CreateMockAnything()
        site_rpc_interface._CONFIG = config_mock
        config_mock.shadow_file = 'shadow_config.ini'
        self.mox.StubOutWithMock(__builtin__, 'open')
        mockFile = self.mox.CreateMockAnything()
        file_contents = self.mox.CreateMockAnything()
        mockFile.__enter__().AndReturn(file_contents)
        mockFile.__exit__(mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg())
        open(config_mock.shadow_file, 'w').AndReturn(mockFile)
        site_rpc_interface.os = self.mox.CreateMockAnything()
        site_rpc_interface.os.system('sudo reboot')
        self.mox.ReplayAll()
        site_rpc_interface.reset_config_settings()


    def testSetBotoKey(self):
        """Ensure that the botokey path supplied is copied correctly."""
        self.setIsMoblab(True)
        boto_key = '/tmp/boto'
        site_rpc_interface.os.path = self.mox.CreateMockAnything()
        site_rpc_interface.os.path.exists(boto_key).AndReturn(
                True)
        site_rpc_interface.shutil = self.mox.CreateMockAnything()
        site_rpc_interface.shutil.copyfile(
                boto_key, site_rpc_interface.MOBLAB_BOTO_LOCATION)
        self.mox.ReplayAll()
        site_rpc_interface.set_boto_key(boto_key)


    def _do_heartbeat_and_assert_response(self, shard_hostname=None, **kwargs):
        expected_shard_hostname = shard_hostname or str(
            models.Shard.objects.count() + 1)
        retval = site_rpc_interface.shard_heartbeat(
            shard_hostname=expected_shard_hostname)

        self._assert_shard_heartbeat_response(expected_shard_hostname, retval,
                                            **kwargs)

        return expected_shard_hostname


    def _assert_shard_heartbeat_response(self, shard_hostname, retval, jobs=[],
                                         hosts=[], hqes=[]):

        retval_hosts, retval_jobs = retval['hosts'], retval['jobs']

        expected_jobs = [
            (job.id, job.name, int(shard_hostname)) for job in jobs]
        returned_jobs = [(job['id'], job['name'], job['shard']['id'])
                         for job in retval_jobs]
        self.assertEqual(returned_jobs, expected_jobs)

        expected_hosts = [(host.id, host.hostname) for host in hosts]
        returned_hosts = [(host['id'], host['hostname'])
                          for host in retval_hosts]
        self.assertEqual(returned_hosts, expected_hosts)

        retval_hqes = []
        for job in retval_jobs:
            retval_hqes += job['hostqueueentry_set']

        expected_hqes = [(hqe.id) for hqe in hqes]
        returned_hqes = [(hqe['id']) for hqe in retval_hqes]
        self.assertEqual(returned_hqes, expected_hqes)


    def testShardHeartbeatFetchHostlessJob(self):
        models.Label.objects.create(name='board:lumpy', platform=True)
        label2 = models.Label.objects.create(name='bluetooth', platform=False)

        shard_hostname = self._do_heartbeat_and_assert_response()
        shard = models.Shard.smart_get(shard_hostname)
        shard.labels.add(models.Label.smart_get('board:lumpy'))

        job1 = self._create_job(hostless=True)

        # Hostless jobs should be executed by the global scheduler.
        self._do_heartbeat_and_assert_response(
            shard_hostname=shard_hostname)


    def testShardRetrieveJobs(self):
        host1, host2 = [models.Host.objects.create(
            hostname=hostname, leased=False) for hostname in ['host1', 'host2']]

        # should never be returned by heartbeat
        leased_host = models.Host.objects.create(hostname='leased_host',
                                                 leased=True)

        lumpy_label = models.Label.objects.create(name='board:lumpy',
                                                  platform=True)
        grumpy_label = models.Label.objects.create(name='board:grumpy',
                                                   platform=True)


        host1.labels.add(lumpy_label)
        leased_host.labels.add(lumpy_label)
        host2.labels.add(grumpy_label)

        shard_hostname1 = self._do_heartbeat_and_assert_response()
        shard_hostname2 = self._do_heartbeat_and_assert_response()

        shard1 = models.Shard.smart_get(shard_hostname1)
        shard2 = models.Shard.smart_get(shard_hostname2)

        shard1.labels.add(lumpy_label)
        shard2.labels.add(grumpy_label)

        job_id = rpc_interface.create_job(name='dummy', priority='Medium',
                                          control_file='foo',
                                          control_type=CLIENT,
                                          meta_hosts=['board:lumpy'],
                                          dependencies=('board:lumpy',),
                                          test_retry=10)
        job1 = models.Job.objects.get(id=job_id)
        job_id = rpc_interface.create_job(name='dummy', priority='Medium',
                                          control_file='foo',
                                          control_type=CLIENT,
                                          meta_hosts=['board:grumpy'],
                                          dependencies=('board:grumpy',),
                                          test_retry=10)

        job2 = models.Job.objects.get(id=job_id)
        job_id = rpc_interface.create_job(name='dummy', priority='Medium',
                                          control_file='foo',
                                          control_type=CLIENT,
                                          meta_hosts=['board:lumpy'],
                                          dependencies=('board:lumpy',),
                                          test_retry=10)
        job_completed = models.Job.objects.get(id=job_id)
        # Job is obviously already run, so don't sync it
        job_completed.hostqueueentry_set.update(complete=True)
        job_completed.hostqueueentry_set.create(complete=False)
        job_id = rpc_interface.create_job(name='dummy', priority='Medium',
                                          control_file='foo',
                                          control_type=CLIENT,
                                          meta_hosts=['board:lumpy'],
                                          dependencies=('board:lumpy',),
                                          test_retry=10)
        job_active = models.Job.objects.get(id=job_id)
        # Job is obviously already started, so don't sync it
        job_active.hostqueueentry_set.update(active=True)
        job_active.hostqueueentry_set.create(complete=False, active=False)

        self._do_heartbeat_and_assert_response(
            shard_hostname=shard_hostname1, jobs=[job1], hosts=[host1],
            hqes=job1.hostqueueentry_set.all())

        self._do_heartbeat_and_assert_response(
            shard_hostname=shard_hostname2, jobs=[job2], hosts=[host2],
            hqes=job2.hostqueueentry_set.all())

        host3 = models.Host.objects.create(hostname='host3', leased=False)
        host3.labels.add(lumpy_label)

        self._do_heartbeat_and_assert_response(
            shard_hostname=shard_hostname1, jobs=[], hosts=[host3])


if __name__ == '__main__':
  unittest.main()
