#!/usr/bin/python
#pylint: disable-msg=C0111

# Copyright (c) 2014 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc

import common

from autotest_lib.database import database_connection
from autotest_lib.frontend import setup_django_environment
from autotest_lib.frontend.afe import frontend_test_utils
from autotest_lib.frontend.afe import models
from autotest_lib.frontend.afe import rdb_model_extensions as rdb_models
from autotest_lib.scheduler import monitor_db
from autotest_lib.scheduler import monitor_db_functional_test
from autotest_lib.scheduler import scheduler_lib
from autotest_lib.scheduler import scheduler_models
from autotest_lib.scheduler import rdb_hosts
from autotest_lib.scheduler import rdb_requests
from autotest_lib.server.cros import provision


# Set for verbose table creation output.
_DEBUG = False
DEFAULT_ACLS = ['Everyone', 'my_acl']
DEFAULT_DEPS = ['a', 'b']
DEFAULT_USER = 'system'

def get_default_job_params():
    return {'deps': DEFAULT_DEPS, 'user': DEFAULT_USER, 'acls': DEFAULT_ACLS,
            'priority': 0, 'parent_job_id': 0}


def get_default_host_params():
    return {'deps': DEFAULT_DEPS, 'acls': DEFAULT_ACLS}


class FakeHost(rdb_hosts.RDBHost):
    """Fake host to use in unittests."""

    def __init__(self, hostname, host_id, **kwargs):
        kwargs.update({'hostname': hostname, 'id': host_id})
        kwargs = rdb_models.AbstractHostModel.provide_default_values(
                kwargs)
        super(FakeHost, self).__init__(**kwargs)


def wire_format_response_map(response_map):
    wire_formatted_map = {}
    for request, response in response_map.iteritems():
        wire_formatted_map[request] = [reply.wire_format()
                                       for reply in response]
    return wire_formatted_map


class DBHelper(object):
    """Utility class for updating the database."""

    def __init__(self):
        """Initialized django so it uses an in memory sqllite database."""
        self.database = (
            database_connection.TranslatingDatabase.get_test_database(
                translators=monitor_db_functional_test._DB_TRANSLATORS))
        self.database.connect(db_type='django')
        self.database.debug = _DEBUG


    @classmethod
    def get_labels(cls, **kwargs):
        """Get a label queryset based on the kwargs."""
        return models.Label.objects.filter(**kwargs)


    @classmethod
    def get_acls(cls, **kwargs):
        """Get an aclgroup queryset based on the kwargs."""
        return models.AclGroup.objects.filter(**kwargs)


    @classmethod
    def get_host(cls, **kwargs):
        """Get a host queryset based on the kwargs."""
        return models.Host.objects.filter(**kwargs)


    @classmethod
    def create_label(cls, name, **kwargs):
        label = cls.get_labels(name=name, **kwargs)
        return (models.Label.add_object(name=name, **kwargs)
                if not label else label[0])


    @classmethod
    def create_user(cls, name):
        user = models.User.objects.filter(login=name)
        return models.User.add_object(login=name) if not user else user[0]


    @classmethod
    def add_labels_to_host(cls, host, label_names=set([])):
        label_objects = set([])
        for label in label_names:
            label_objects.add(cls.create_label(label))
        host.labels.add(*label_objects)


    @classmethod
    def create_acl_group(cls, name):
        aclgroup = cls.get_acls(name=name)
        return (models.AclGroup.add_object(name=name)
                if not aclgroup else aclgroup[0])


    @classmethod
    def add_deps_to_job(cls, job, dep_names=set([])):
        label_objects = set([])
        for label in dep_names:
            label_objects.add(cls.create_label(label))
        job.dependency_labels.add(*label_objects)


    @classmethod
    def add_host_to_aclgroup(cls, host, aclgroup_names=set([])):
        for group_name in aclgroup_names:
            aclgroup = cls.create_acl_group(group_name)
            aclgroup.hosts.add(host)


    @classmethod
    def add_user_to_aclgroups(cls, username, aclgroup_names=set([])):
        user = cls.create_user(username)
        for group_name in aclgroup_names:
            aclgroup = cls.create_acl_group(group_name)
            aclgroup.users.add(user)


    @classmethod
    def create_host(cls, name, deps=set([]), acls=set([]), status='Ready',
                 locked=0, leased=0, protection=0, dirty=0):
        """Create a host.

        Also adds the appropriate labels to the host, and adds the host to the
        required acl groups.

        @param name: The hostname.
        @param kwargs:
            deps: The labels on the host that match job deps.
            acls: The aclgroups this host must be a part of.
            status: The status of the host.
            locked: 1 if the host is locked.
            leased: 1 if the host is leased.
            protection: Any protection level, such as Do Not Verify.
            dirty: 1 if the host requires cleanup.

        @return: The host object for the new host.
        """
        # TODO: Modify this to use the create host request once
        # crbug.com/350995 is fixed.
        host = models.Host.add_object(
                hostname=name, status=status, locked=locked,
                leased=leased, protection=protection)
        cls.add_labels_to_host(host, label_names=deps)
        cls.add_host_to_aclgroup(host, aclgroup_names=acls)

        # Though we can return the host object above, this proves that the host
        # actually got saved in the database. For example, this will return none
        # if save() wasn't called on the model.Host instance.
        return cls.get_host(hostname=name)[0]


    @classmethod
    def add_host_to_job(cls, host, job_id):
        """Add a host to the hqe of a job.

        @param host: An instance of the host model.
        @param job_id: The job to which we need to add the host.

        @raises ValueError: If the hqe for the job already has a host,
            or if the host argument isn't a Host instance.
        """
        hqe = models.HostQueueEntry.objects.get(job_id=job_id)
        if hqe.host:
            raise ValueError('HQE for job %s already has a host' % job_id)
        hqe.host = host
        hqe.save()


    @classmethod
    def add_host_to_job(cls, host, job_id):
        """Add a host to the hqe of a job.

        @param host: An instance of the host model.
        @param job_id: The job to which we need to add the host.

        @raises ValueError: If the hqe for the job already has a host,
            or if the host argument isn't a Host instance.
        """
        hqe = models.HostQueueEntry.objects.get(job_id=job_id)
        if hqe.host:
            raise ValueError('HQE for job %s already has a host' % job_id)
        hqe.host = host
        hqe.save()


    @classmethod
    def increment_priority(cls, job_id):
        job = models.Job.objects.get(id=job_id)
        job.priority = job.priority + 1
        job.save()


class AbstractBaseRDBTester(frontend_test_utils.FrontendTestMixin):

    __meta__ = abc.ABCMeta
    _config_section = 'AUTOTEST_WEB'


    @staticmethod
    def get_request(dep_names, acl_names, priority=0, parent_job_id=0):
        deps = [dep.id for dep in DBHelper.get_labels(name__in=dep_names)]
        acls = [acl.id for acl in DBHelper.get_acls(name__in=acl_names)]
        return rdb_requests.AcquireHostRequest(
                        deps=deps, acls=acls, host_id=None, priority=priority,
                        parent_job_id=parent_job_id)._request


    def _release_unused_hosts(self):
        """Release all hosts unused by an active hqe. """
        self.host_scheduler.tick()


    def setUp(self):
        self.db_helper = DBHelper()
        self._database = self.db_helper.database
        # Runs syncdb setting up initial database conditions
        self._frontend_common_setup()
        connection_manager = scheduler_lib.ConnectionManager(autocommit=False)
        self.god.stub_with(connection_manager, 'db_connection', self._database)
        self.god.stub_with(monitor_db, '_db_manager', connection_manager)
        self.god.stub_with(scheduler_models, '_db', self._database)
        self._dispatcher = monitor_db.Dispatcher()
        self.host_scheduler = self._dispatcher._host_scheduler
        self._release_unused_hosts()


    def tearDown(self):
        self.god.unstub_all()
        self._database.disconnect()
        self._frontend_common_teardown()


    def create_job(self, user='autotest_system',
                   deps=set([]), acls=set([]), hostless_job=False,
                   priority=0, parent_job_id=None):
        """Create a job owned by user, with the deps and acls specified.

        This method is a wrapper around frontend_test_utils.create_job, that
        also takes care of creating the appropriate deps for a job, and the
        appropriate acls for the given user.

        @raises ValueError: If no deps are specified for a job, since all jobs
            need at least the metahost.
        @raises AssertionError: If no hqe was created for the job.

        @return: An instance of the job model associated with the new job.
        """
        # This is a slight hack around the implementation of
        # scheduler_models.is_hostless_job, even though a metahost is just
        # another label to the rdb.
        if not deps:
            raise ValueError('Need at least one dep for metahost')

        # TODO: This is a hack around the fact that frontend_test_utils still
        # need a metahost, but metahost is treated like any other label.
        metahost = self.db_helper.create_label(list(deps)[0])
        job = self._create_job(metahosts=[metahost.id], priority=priority,
                owner=user, parent_job_id=parent_job_id)
        self.assert_(len(job.hostqueueentry_set.all()) == 1)

        self.db_helper.add_deps_to_job(job, dep_names=list(deps)[1:])
        self.db_helper.add_user_to_aclgroups(user, aclgroup_names=acls)
        return models.Job.objects.filter(id=job.id)[0]


    def assert_host_db_status(self, host_id):
        """Assert host state right after acquisition.

        Call this method to check the status of any host leased by the
        rdb before it has been assigned to an hqe. It must be leased and
        ready at this point in time.

        @param host_id: Id of the host to check.

        @raises AssertionError: If the host is either not leased or Ready.
        """
        host = models.Host.objects.get(id=host_id)
        self.assert_(host.leased)
        self.assert_(host.status == 'Ready')


    def check_hosts(self, host_iter):
        """Sanity check all hosts in the host_gen.

        @param host_iter: A generator/iterator of RDBClientHostWrappers.
            eg: The generator returned by rdb_lib.acquire_hosts. If a request
            was not satisfied this iterator can contain None.

        @raises AssertionError: If any of the sanity checks fail.
        """
        for host in host_iter:
            if host:
                self.assert_host_db_status(host.id)
                self.assert_(host.leased == 1)


    def create_suite(self, user='autotest_system', num=2, priority=0,
                     board='z', build='x'):
        """Create num jobs with the same parent_job_id, board, build, priority.

        @return: A dictionary with the parent job object keyed as 'parent_job'
            and all other jobs keyed at an index from 0-num.
        """
        jobs = {}
        # Create a hostless parent job without an hqe or deps. Since the
        # hostless job does nothing, we need to hand craft cros-version.
        parent_job = self._create_job(owner=user, priority=priority)
        jobs['parent_job'] = parent_job
        build = '%s:%s' % (provision.CROS_VERSION_PREFIX, build)
        for job_index in range(0, num):
            jobs[job_index] = self.create_job(user=user, priority=priority,
                                              deps=set([board, build]),
                                              parent_job_id=parent_job.id)
        return jobs


    def check_host_assignment(self, job_id, host_id):
        """Check is a job<->host assignment is valid.

        Uses the deps of a job and the aclgroups the owner of the job is
        in to see if the given host can be used to run the given job. Also
        checks that the host-job assignment has Not been made, but that the
        host is no longer in the available hosts pool.

        Use this method to check host assignements made by the rdb, Before
        they're handed off to the scheduler, since the scheduler.

        @param job_id: The id of the job to use in the compatibility check.
        @param host_id: The id of the host to check for compatibility.

        @raises AssertionError: If the job and the host are incompatible.
        """
        job = models.Job.objects.get(id=job_id)
        host = models.Host.objects.get(id=host_id)
        hqe = job.hostqueueentry_set.all()[0]

        # Confirm that the host has not been assigned, either to another hqe
        # or the this one.
        all_hqes = models.HostQueueEntry.objects.filter(
                host_id=host_id, complete=0)
        self.assert_(len(all_hqes) <= 1)
        self.assert_(hqe.host_id == None)
        self.assert_host_db_status(host_id)

        # Assert that all deps of the job are satisfied.
        job_deps = set([d.name for d in job.dependency_labels.all()])
        host_labels = set([l.name for l in host.labels.all()])
        self.assert_(job_deps.intersection(host_labels) == job_deps)

        # Assert that the owner of the job is in at least one of the
        # groups that owns the host.
        job_owner_aclgroups = set([job_acl.name for job_acl
                                   in job.user().aclgroup_set.all()])
        host_aclgroups = set([host_acl.name for host_acl
                              in host.aclgroup_set.all()])
        self.assert_(job_owner_aclgroups.intersection(host_aclgroups))


