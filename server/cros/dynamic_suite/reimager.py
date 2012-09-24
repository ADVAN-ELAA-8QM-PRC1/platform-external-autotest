# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


import compiler, datetime, hashlib, itertools, logging, random, os

import common

from autotest_lib.client.common_lib import control_data, global_config
from autotest_lib.client.common_lib import error, utils
from autotest_lib.client.common_lib.cros import dev_server
from autotest_lib.server.cros.dynamic_suite import constants
from autotest_lib.server.cros.dynamic_suite import control_file_getter
from autotest_lib.server.cros.dynamic_suite import frontend_wrappers
from autotest_lib.server.cros.dynamic_suite import host_lock_manager, host_spec
from autotest_lib.server.cros.dynamic_suite import job_status, tools
from autotest_lib.server.cros.dynamic_suite.host_spec import ExplicitHostGroup
from autotest_lib.server.cros.dynamic_suite.host_spec import HostSpec
from autotest_lib.server.cros.dynamic_suite.host_spec import MetaHostGroup
from autotest_lib.server.cros.dynamic_suite.job_status import Status
from autotest_lib.server import frontend
from autotest_lib.frontend.afe.json_rpc import proxy


class Reimager(object):
    """
    A class that can run jobs to reimage devices.

    @var _afe: a frontend.AFE instance used to talk to autotest.
    @var _tko: a frontend.TKO instance used to query the autotest results db.
    @var _results_dir: The directory where the job can write results to.
                       This must be set if you want the 'name_job-id' tuple
                       of each per-device reimaging job listed in the
                       parent reimaging job's keyvals.
    @var _cf_getter: a ControlFileGetter used to get the AU control file.
    """

    JOB_NAME = 'try_new_image'


    def __init__(self, autotest_dir, afe=None, tko=None, results_dir=None):
        """
        Constructor

        @param autotest_dir: the place to find autotests.
        @param afe: an instance of AFE as defined in server/frontend.py.
        @param tko: an instance of TKO as defined in server/frontend.py.
        @param results_dir: The directory where the job can write results to.
                            This must be set if you want the 'name_job-id' tuple
                            of each per-device reimaging job listed in the
                            parent reimaging job's keyvals.
        """
        self._afe = afe or frontend_wrappers.RetryingAFE(timeout_min=30,
                                                         delay_sec=10,
                                                         debug=False)
        self._tko = tko or frontend_wrappers.RetryingTKO(timeout_min=30,
                                                         delay_sec=10,
                                                         debug=False)
        self._results_dir = results_dir
        self._reimaged_hosts = {}
        self._cf_getter = control_file_getter.FileSystemGetter(
            [os.path.join(autotest_dir, 'server/site_tests')])


    def attempt(self, build, board, pool, devserver, record, check_hosts,
                manager, tests_to_skip, dependencies={'':[]}, num=None):
        """
        Synchronously attempt to reimage some machines.

        Fire off attempts to reimage |num| machines of type |board|, using an
        image at |url| called |build|.  Wait for completion, polling every
        10s, and log results with |record| upon completion.

        Unfortunately, we can't rely on the scheduler to pick hosts for
        us when using dependencies.  The problem is that the scheduler
        treats all host queue entries as independent, and isn't capable
        of looking across a set of entries to make intelligent decisions
        about which hosts to use.  Consider a testbed that has only one
        'bluetooth'-labeled device, and a set of tests in which some
        require bluetooth and some could run on any machine.  If we
        schedule two reimaging jobs, one of which states that it should
        run on a bluetooth-having machine, the scheduler may choose to
        run the _other_ reimaging job (which has fewer constraints)
        on the DUT with the 'bluetooth' label -- thus starving the first
        reimaging job.  We can't schedule a single job with heterogeneous
        dependencies, either, as that is unsupported and devolves to the
        same problem: the scheduler is not designed to make decisions
        across multiple host queue entries.

        Given this, we'll grab lists of hosts on our own and make our
        own scheduling decisions.

        @param build: the build to install e.g.
                      x86-alex-release/R18-1655.0.0-a1-b1584.
        @param board: which kind of devices to reimage.
        @param pool: Specify the pool of machines to use for scheduling
                purposes.
        @param devserver: an instance of a devserver to use to complete this
                  call.
        @param record: callable that records job status.
               prototype:
                 record(base_job.status_log_entry)
        @param check_hosts: require appropriate hosts to be available now.
        @param manager: an as-yet-unused HostLockManager instance to handle
                        locking DUTs that we decide to reimage.
        @param tests_to_skip: a list output parameter.  After execution, this
                              contains a list of control files not to run.
        @param dependencies: test-name-indexed dict of labels, e.g.
                             {'test1': ['label1', 'label2']}
                             Defaults to trivial set of dependencies, to cope
                             with builds that have no dependency information.

        @param num: the maximum number of devices to reimage.
        @return True if all reimaging jobs succeed, false otherwise.
        """
        if not num:
            num = tools.sharding_factor()
        logging.debug("scheduling reimaging across at most %d machines", num)
        begin_time_str = datetime.datetime.now().strftime(job_status.TIME_FMT)
        try:
            self._ensure_version_label(constants.VERSION_PREFIX + build)

            # Figure out what kind of hosts we need to grab.
            per_test_specs = self._build_host_specs_from_dependencies(
                board, pool, dependencies)

            # Pick hosts to use, make sure we have enough (if needed).
            to_reimage = self._build_host_group(set(per_test_specs.values()),
                                                num, check_hosts)

            # Determine which, if any, tests can't be run on the hosts we found.
            tests_to_skip.extend(
                self._discover_unrunnable_tests(per_test_specs,
                                                to_reimage.unsatisfied_specs))
            for test_name in tests_to_skip:
                Status('TEST_NA', test_name, 'Unsatisfiable DEPENDENCIES',
                       begin_time_str=begin_time_str).record_all(record)

            # Schedule job and record job metadata.
            canary_job = self._schedule_reimage_job(build, to_reimage,
                                                    devserver)

            self._record_job_if_possible(Reimager.JOB_NAME, canary_job)
            logging.info('Created re-imaging job: %d', canary_job.id)

            job_status.wait_for_jobs_to_start(self._afe, [canary_job])
            logging.debug('Re-imaging job running.')

            hosts = job_status.wait_for_and_lock_job_hosts(
                self._afe, [canary_job], manager)
            logging.info('%r locked for reimaging.', hosts)

            job_status.wait_for_jobs_to_finish(self._afe, [canary_job])
            logging.debug('Re-imaging job finished.')

            results = job_status.gather_per_host_results(self._afe,
                                                         self._tko,
                                                         [canary_job],
                                                         Reimager.JOB_NAME+'-')
            self._reimaged_hosts[build] = results.keys()

        except error.InadequateHostsException as e:
            logging.warning(e)
            Status('WARN', Reimager.JOB_NAME, str(e),
                   begin_time_str=begin_time_str).record_all(record)
            return False

        except Exception as e:
            # catch Exception so we record the job as terminated no matter what.
            import traceback
            logging.error(traceback.format_exc())
            logging.error(e)

            Status('ERROR', Reimager.JOB_NAME, str(e),
                   begin_time_str=begin_time_str).record_all(record)
            return False

        should_continue = job_status.check_and_record_reimage_results(
            results, to_reimage, record)

        # Currently, this leads to us skipping even tests with no DEPENDENCIES
        # in certain cases: http://crosbug.com/34635
        doomed_tests = self._discover_unrunnable_tests(per_test_specs,
                                                       to_reimage.doomed_specs)
        for test_name in doomed_tests:
            Status('ERROR', test_name,
                   'Failed to reimage machine with appropriate labels.',
                   begin_time_str=begin_time_str).record_all(record)
        tests_to_skip.extend(doomed_tests)
        return should_continue


    def _build_host_specs_from_dependencies(self, board, pool, deps):
        """
        Return an iterable of host specs, given some test dependencies.

        Given a dict of test dependency sets, build and return an iterable
        of 'host specifications' -- sets of labels that specify a kind of host
        needed to run at least one test in the suite.

        @param board: which kind of devices to reimage.
        @param pool: the pool of machines to use for scheduling purposes.
        @param deps: test-name-indexed dict of labels, e.g.
                     {'test1': ['label1', 'label2']}
        @return test-name-indexed dict of HostSpecs.
        """
        base = [l for l in [board, pool] if l is not None]
        return dict(
            [(name, HostSpec(base + d)) for name, d in deps.iteritems()])


    def _build_host_group(self, host_specs, num, require_usable_hosts=True):
        """
        Given a list of HostSpec objects, build an appropriate HostGroup.

        Given a list of HostSpec objects, try to build a HostGroup that
        statisfies them all and contains num hosts.  If all can be satisfied
        with fewer than num hosts, log a warning and continue.  The caller
        can choose whether to check that we have enough currently usable hosts
        to satisfy the given requirements by passing True for check_hosts.

        @param host_specs: an iterable of HostSpecs.
        @param require_usable_hosts: require appropriate hosts to be available
                                     now.
        @param num: the maximum number of devices to reimage.
        @return a HostGroup derived from the provided HostSpec(s).
        @raises error.InadequateHostsException if there are more HostSpecs
                greater than the number of hosts requested.
        @raises error.NoHostsException if we find no usable hosts at all.
        """
        if len(host_specs) > num:
            raise error.InadequateHostsException(
                '%d hosts cannot satisfy dependencies %r' % (num, host_specs))

        hosts_per_spec = self._gather_hosts_from_host_specs(host_specs)
        if host_spec.is_trivial(host_specs):
            spec, hosts = host_spec.trivial_get_spec_and_hosts(
                host_specs, hosts_per_spec)
            if require_usable_hosts and not filter(tools.is_usable, hosts):
                raise error.NoHostsException('All hosts with %r are dead!' %
                                             spec)
            return MetaHostGroup(spec.labels, num)
        else:
            return self._choose_hosts(hosts_per_spec, num,
                                      require_usable_hosts)


    def _gather_hosts_from_host_specs(self, specs):
        """
        Given an iterable of HostSpec objets, find all hosts that satisfy each.

        @param specs: an iterable of HostSpecs.
        @return a dict of {HostSpec: [list, of, hosts]}
        """
        return dict(
            [(s, self._afe.get_hosts(multiple_labels=s.labels)) for s in specs])


    def _choose_hosts(self, hosts_per_spec, num, require_usable_hosts=True):
        """
        For each (spec, host_list) pair, choose >= 1 of the 'best' hosts.

        If picking one of each does not get us up to num total hosts, fill out
        the list with more hosts that fit the 'least restrictive' host_spec.

        Hosts are stack-ranked by availability.  So, 'Ready' is the best,
        followed by anything else that can pass the tools.is_usable() predicate
        below.  If require_usable_hosts is False, we'll fall all the way back to
        currently unusable hosts.

        @param hosts_per_spec: {HostSpec: [list, of, hosts]}.
        @param num: how many devices to reimage.
        @param require_usable_hosts: only return hosts currently in a usable
                                     state.
        @return a HostGroup encoding the set of hosts to reimage.
        @raises error.NoHostsException if we find no usable hosts at all.
        """
        ordered_specs = host_spec.order_by_complexity(hosts_per_spec.keys())
        hosts_to_use = ExplicitHostGroup()
        for spec in ordered_specs:
            to_check = filter(lambda h: not hosts_to_use.contains_host(h),
                              hosts_per_spec[spec])
            chosen = self._get_random_best_host(to_check, require_usable_hosts)
            hosts_to_use.add_host_for_spec(spec, chosen)

        if hosts_to_use.size() == 0:
            raise error.NoHostsException('All hosts for %r are dead!' %
                                         ordered_specs)

        # fill out the set with DUTs that fit the least complex HostSpec.
        simplest_spec = ordered_specs[-1]
        for i in xrange(num - hosts_to_use.size()):
            to_check = filter(lambda h: not hosts_to_use.contains_host(h),
                              hosts_per_spec[simplest_spec])
            chosen = self._get_random_best_host(to_check, require_usable_hosts)
            hosts_to_use.add_host_for_spec(simplest_spec, chosen)

        if hosts_to_use.unsatisfied_specs:
            logging.warn('Could not find %d hosts to use; '
                         'unsatisfied dependencies: %r.',
                         num, hosts_to_use.unsatisfied_specs)
        elif num > hosts_to_use.size():
            logging.warn('Could not find %d hosts to use, '
                         'but dependencies are satisfied.', num)

        return hosts_to_use


    def _get_random_best_host(self, host_list, require_usable_hosts=True):
        """
        Randomly choose the 'best' host from host_list, using fresh status.

        Hit the AFE to get latest status for the listed hosts.  Then apply
        the following heuristic to pick the 'best' set:

        Remove unusable hosts (not tools.is_usable()), then
        'Ready' > 'Running, Cleaning, Verifying, etc'

        If any 'Ready' hosts exist, return a random choice.  If not, randomly
        choose from the next tier.  If there are none of those either, None.

        @param host_list: an iterable of Host objects, per server/frontend.py
        @param require_usable_hosts: only return hosts currently in a usable
                                     state.
        @return a Host object, or None if no appropriate host is found.
        """
        if not host_list:
            return None
        hostnames = [host.hostname for host in host_list]
        updated_hosts = self._afe.get_hosts(hostnames=hostnames)
        usable_hosts = [host for host in updated_hosts if tools.is_usable(host)]
        ready_hosts = [host for host in usable_hosts if host.status == 'Ready']
        unusable_hosts = [h for h in updated_hosts if not tools.is_usable(h)]
        if ready_hosts:
            return random.choice(ready_hosts)
        if usable_hosts:
            return random.choice(usable_hosts)
        if not require_usable_hosts and unusable_hosts:
            return random.choice(unusable_hosts)
        return None


    def _discover_unrunnable_tests(self, per_test_specs, bad_specs):
        """
        Exclude tests by name based on a blacklist of bad HostSpecs.

        @param per_test_specs: {'test/name/control': HostSpec}
        @param bad_specs: iterable of HostSpec whose associated tests should
                          be excluded.
        @return iterable of test names that are associated with bad_specs.
        """
        return [n for n,s in per_test_specs.iteritems() if s in bad_specs]


    def clear_reimaged_host_state(self, build):
        """
        Clear per-host state created in the autotest DB for this job.

        After reimaging a host, we label it and set some host attributes on it
        that are then used by the suite scheduling code.  This call cleans
        that up.

        @param build: the build whose hosts we want to clean up e.g.
                      x86-alex-release/R18-1655.0.0-a1-b1584.
        """
        for host in self._reimaged_hosts.get('build', []):
            if not host.startswith('hostless'):
                self._clear_build_state(host)


    def _clear_build_state(self, machine):
        """
        Clear all build-specific labels, attributes from the target.

        @param machine: the host to clear labels, attributes from.
        """
        self._afe.set_host_attribute(constants.JOB_REPO_URL, None,
                                     hostname=machine)


    def _record_job_if_possible(self, test_name, job):
        """
        Record job id as keyval, if possible, so it can be referenced later.

        If |self._results_dir| is None, then this is a NOOP.

        @param test_name: the test to record id/owner for.
        @param job: the job object to pull info from.
        """
        if self._results_dir:
            job_id_owner = '%s-%s' % (job.id, job.owner)
            utils.write_keyval(
                self._results_dir,
                {hashlib.md5(test_name).hexdigest(): job_id_owner})


    def _ensure_version_label(self, name):
        """
        Ensure that a label called |name| exists in the autotest DB.

        @param name: the label to check for/create.
        """
        try:
            self._afe.create_label(name=name)
        except proxy.ValidationError as ve:
            if ('name' in ve.problem_keys and
                'This value must be unique' in ve.problem_keys['name']):
                logging.debug('Version label %s already exists', name)
            else:
                raise ve


    def _schedule_reimage_job(self, build, host_group, devserver):
        """
        Schedules the reimaging of |num_machines| |board| devices with |image|.

        Sends an RPC to the autotest frontend to enqueue reimaging jobs on
        |num_machines| devices of type |board|.

        @param build: the build to install (must be unique).
        @param host_group: the HostGroup to be used for this reimaging job.
        @param devserver: an instance of devserver that DUTs should use to get
                          build artifacts from.

        @return a frontend.Job object for the reimaging job we scheduled.
        """
        image_url = tools.image_url_pattern() % (devserver.url(), build)
        control_file = tools.inject_vars(
            dict(image_url=image_url, image_name=build,
                 devserver_url=devserver.url()),
            self._cf_getter.get_control_file_contents_by_name('autoupdate'))

        return self._afe.create_job(control_file=control_file,
                                     name=build + '-try',
                                     control_type='Server',
                                     priority='Low',
                                     **host_group.as_args())
