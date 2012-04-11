# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import common
import compiler, logging, os, random, re, time
from autotest_lib.client.common_lib import base_job, control_data, global_config
from autotest_lib.client.common_lib import error, utils
from autotest_lib.client.common_lib.cros import dev_server
from autotest_lib.server.cros import control_file_getter, frontend_wrappers
from autotest_lib.server import frontend


VERSION_PREFIX = 'cros-version:'
CONFIG = global_config.global_config


class AsynchronousBuildFailure(Exception):
    """Raised when the dev server throws 500 while finishing staging of a build.
    """
    pass


class SuiteArgumentException(Exception):
    """Raised when improper arguments are used to run a suite."""
    pass


class InadequateHostsException(Exception):
    """Raised when there are too few hosts to run a suite."""
    pass


class NoHostsException(Exception):
    """Raised when there are no healthy hosts to run a suite."""
    pass


def reimage_and_run(**dargs):
    """
    Backward-compatible API for dynamic_suite.

    Will re-image a number of devices (of the specified board) with the
    provided build, and then run the indicated test suite on them.
    Guaranteed to be compatible with any build from stable to dev.

    Currently required args:
    @param build: the build to install e.g.
                  x86-alex-release/R18-1655.0.0-a1-b1584.
    @param board: which kind of devices to reimage.
    @param name: a value of the SUITE control file variable to search for.
    @param job: an instance of client.common_lib.base_job representing the
                currently running suite job.

    Currently supported optional args:
    @param pool: specify the pool of machines to use for scheduling purposes.
                 Default: None
    @param num: how many devices to reimage.
                Default in global_config
    @param check_hosts: require appropriate hosts to be available now.
    @param skip_reimage: skip reimaging, used for testing purposes.
                         Default: False
    @param add_experimental: schedule experimental tests as well, or not.
                             Default: True
    @raises AsynchronousBuildFailure: if there was an issue finishing staging
                                      from the devserver.
    """
    (build, board, name, job, pool, num, check_hosts, skip_reimage,
     add_experimental) = _vet_reimage_and_run_args(**dargs)
    board = 'board:%s' % board
    if pool:
        pool = 'pool:%s' % pool
    reimager = Reimager(job.autodir, pool=pool, results_dir=job.resultdir)

    if skip_reimage or reimager.attempt(build, board, job.record, check_hosts,
                                        num=num):

        # Ensure that the image's artifacts have completed downloading.
        ds = dev_server.DevServer.create()
        if not ds.finish_download(build):
            raise AsynchronousBuildFailure(
                "Server error completing staging for " + build)

        suite = Suite.create_from_name(name, build, pool=pool,
                                       results_dir=job.resultdir)
        suite.run_and_wait(job.record, add_experimental=add_experimental)

    reimager.clear_reimaged_host_state(build)


def _vet_reimage_and_run_args(build=None, board=None, name=None, job=None,
                              pool=None, num=None, check_hosts=True,
                              skip_reimage=False, add_experimental=True,
                              **dargs):
    """
    Vets arguments for reimage_and_run().

    Currently required args:
    @param build: the build to install e.g.
                  x86-alex-release/R18-1655.0.0-a1-b1584.
    @param board: which kind of devices to reimage.
    @param name: a value of the SUITE control file variable to search for.
    @param job: an instance of client.common_lib.base_job representing the
                currently running suite job.

    Currently supported optional args:
    @param pool: specify the pool of machines to use for scheduling purposes.
                 Default: None
    @param num: how many devices to reimage.
                Default in global_config
    @param check_hosts: require appropriate hosts to be available now.
    @param skip_reimage: skip reimaging, used for testing purposes.
                         Default: False
    @param add_experimental: schedule experimental tests as well, or not.
                             Default: True
    @return a tuple of args set to provided (or default) values.
    """
    required_keywords = {'build': str,
                         'board': str,
                         'name': str,
                         'job': base_job.base_job}
    for key, expected in required_keywords.iteritems():
        value = locals().get(key)
        if not value or not isinstance(value, expected):
            raise SuiteArgumentException("reimage_and_run() needs %s=<%r>" % (
                key, expected))
    return (build, board, name, job, pool, num, check_hosts, skip_reimage,
            add_experimental)


def inject_vars(vars, control_file_in):
    """
    Inject the contents of |vars| into |control_file_in|.

    @param vars: a dict to shoehorn into the provided control file string.
    @param control_file_in: the contents of a control file to munge.
    @return the modified control file string.
    """
    control_file = ''
    for key, value in vars.iteritems():
        # None gets injected as 'None' without this check; same for digits.
        if isinstance(value, str):
            control_file += "%s='%s'\n" % (key, value)
        else:
            control_file += "%s=%r\n" % (key, value)
    return control_file + control_file_in


def _image_url_pattern():
    return CONFIG.get_config_value('CROS', 'image_url_pattern', type=str)


def _package_url_pattern():
    return CONFIG.get_config_value('CROS', 'package_url_pattern', type=str)


def skip_reimage(g):
    return g.get('SKIP_IMAGE')


class Reimager(object):
    """
    A class that can run jobs to reimage devices.

    @var _afe: a frontend.AFE instance used to talk to autotest.
    @var _tko: a frontend.TKO instance used to query the autotest results db.
    @var _cf_getter: a ControlFileGetter used to get the AU control file.
    """


    def __init__(self, autotest_dir, afe=None, tko=None, pool=None,
                 results_dir=None):
        """
        Constructor

        @param autotest_dir: the place to find autotests.
        @param afe: an instance of AFE as defined in server/frontend.py.
        @param tko: an instance of TKO as defined in server/frontend.py.
        @param pool: Specify the pool of machines to use for scheduling
                purposes.
        @param results_dir: The directory where the job can write results to.
                            This must be set if you want job_id of sub-jobs
                            list in the job keyvals.
        """
        self._afe = afe or frontend_wrappers.RetryingAFE(timeout_min=30,
                                                         delay_sec=10,
                                                         debug=False)
        self._tko = tko or frontend_wrappers.RetryingTKO(timeout_min=30,
                                                         delay_sec=10,
                                                         debug=False)
        self._pool = pool
        self._results_dir = results_dir
        self._reimaged_hosts = {}
        self._cf_getter = control_file_getter.FileSystemGetter(
            [os.path.join(autotest_dir, 'server/site_tests')])


    def skip(self, g):
        """Deprecated in favor of dynamic_suite.skip_reimage()."""
        return 'SKIP_IMAGE' in g and g['SKIP_IMAGE']


    def attempt(self, build, board, record, check_hosts, num=None):
        """
        Synchronously attempt to reimage some machines.

        Fire off attempts to reimage |num| machines of type |board|, using an
        image at |url| called |build|.  Wait for completion, polling every
        10s, and log results with |record| upon completion.

        @param build: the build to install e.g.
                      x86-alex-release/R18-1655.0.0-a1-b1584.
        @param board: which kind of devices to reimage.
        @param record: callable that records job status.
                       prototype:
                         record(status, subdir, name, reason)
        @param check_hosts: require appropriate hosts to be available now.
        @param num: how many devices to reimage.
        @return True if all reimaging jobs succeed, false otherwise.
        """
        if not num:
            num = CONFIG.get_config_value('CROS', 'sharding_factor', type=int)
        logging.debug("scheduling reimaging across %d machines", num)
        wrapper_job_name = 'try_new_image'
        record('START', None, wrapper_job_name)
        try:
            self._ensure_version_label(VERSION_PREFIX + build)

            if check_hosts:
                self._ensure_enough_hosts(board, self._pool, num)

            # Schedule job and record job metadata.
            canary_job = self._schedule_reimage_job(build, num, board)
            self._record_job_if_possible(wrapper_job_name, canary_job)
            logging.debug('Created re-imaging job: %d', canary_job.id)

            # Poll until reimaging is complete.
            self._wait_for_job_to_start(canary_job.id)
            self._wait_for_job_to_finish(canary_job.id)

            # Gather job results.
            canary_job.result = self._afe.poll_job_results(self._tko,
                                                           canary_job,
                                                           0)
        except InadequateHostsException as e:
            logging.warning(e)
            record('END WARN', None, wrapper_job_name, str(e))
            return False
        except Exception as e:
            # catch Exception so we record the job as terminated no matter what.
            logging.error(e)
            record('END ERROR', None, wrapper_job_name, str(e))
            return False

        self._remember_reimaged_hosts(build, canary_job)

        if canary_job.result is True:
            self._report_results(canary_job, record)
            record('END GOOD', None, wrapper_job_name)
            return True

        if canary_job.result is None:
            record('FAIL', None, canary_job.name, 'reimaging tasks did not run')
        else:  # canary_job.result is False
            self._report_results(canary_job, record)

        record('END FAIL', None, wrapper_job_name)
        return False


    def _ensure_enough_hosts(self, board, pool, num):
        """
        Determine if there are enough working hosts to run on.

        Raises exception if there are not enough hosts.

        @param board: which kind of devices to reimage.
        @param pool: the pool of machines to use for scheduling purposes.
        @param num: how many devices to reimage.
        @raises InadequateHostsException: if too few working hosts.
        """
        labels = [l for l in [board, pool] if l is not None]
        available = self._count_usable_hosts(labels)
        if available == 0:
            raise NoHostsException('All hosts with %r are dead!' % labels)
        elif num > available:
            raise InadequateHostsException('Too few hosts with %r' % labels)


    def _wait_for_job_to_start(self, job_id):
        """
        Wait for the job specified by |job_id| to start.

        @param job_id: the job ID to poll on.
        """
        while len(self._afe.get_jobs(id=job_id, not_yet_run=True)) > 0:
            time.sleep(10)
        logging.debug('Re-imaging job running.')


    def _wait_for_job_to_finish(self, job_id):
        """
        Wait for the job specified by |job_id| to finish.

        @param job_id: the job ID to poll on.
        """
        while len(self._afe.get_jobs(id=job_id, finished=True)) == 0:
            time.sleep(10)
        logging.debug('Re-imaging job finished.')


    def _remember_reimaged_hosts(self, build, canary_job):
        """
        Remember hosts that were reimaged with |build| as a part |canary_job|.

        @param build: the build that was installed e.g.
                      x86-alex-release/R18-1655.0.0-a1-b1584.
        @param canary_job: a completed frontend.Job object, possibly populated
                           by frontend.AFE.poll_job_results.
        """
        if not hasattr(canary_job, 'results_platform_map'):
            return
        if not self._reimaged_hosts.get('build'):
            self._reimaged_hosts[build] = []
        for platform in canary_job.results_platform_map:
            for host in canary_job.results_platform_map[platform]['Total']:
                self._reimaged_hosts[build].append(host)


    def clear_reimaged_host_state(self, build):
        """
        Clear per-host state created in the autotest DB for this job.

        After reimaging a host, we label it and set some host attributes on it
        that are then used by the suite scheduling code.  This call cleans
        that up.

        @param build: the build whose hosts we want to clean up e.g.
                      x86-alex-release/R18-1655.0.0-a1-b1584.
        """
        labels = self._afe.get_labels(name__startswith=VERSION_PREFIX + build)
        for label in labels: self._afe.run('delete_label', id=label.id)
        for host in self._reimaged_hosts.get('build', []):
            self._clear_build_state(host)


    def _clear_build_state(self, machine):
        """
        Clear all build-specific labels, attributes from the target.

        @param machine: the host to clear labels, attributes from.
        """
        self._afe.set_host_attribute('job_repo_url', None, hostname=machine)


    def _record_job_if_possible(self, test_name, job):
        """
        Record job id as keyval, if possible, so it can be referenced later.

        If |self._results_dir| is None, then this is a NOOP.

        @param test_name: the test to record id/owner for.
        @param job: the job object to pull info from.
        """
        if self._results_dir:
            job_id_owner = '%s-%s' % (job.id, job.owner)
            utils.write_keyval(self._results_dir, {test_name: job_id_owner})


    def _count_usable_hosts(self, host_spec):
        """
        Given a set of host labels, count the live hosts that have them all.

        @param host_spec: list of labels specifying a set of hosts.
        @return the number of live hosts that satisfy |host_spec|.
        """
        count = 0
        for h in self._afe.get_hosts(multiple_labels=host_spec):
            if h.status not in ['Repair Failed', 'Repairing']:
                count += 1
        return count


    def _ensure_version_label(self, name):
        """
        Ensure that a label called |name| exists in the autotest DB.

        @param name: the label to check for/create.
        """
        labels = self._afe.get_labels(name=name)
        if len(labels) == 0:
            self._afe.create_label(name=name)


    def _schedule_reimage_job(self, build, num_machines, board):
        """
        Schedules the reimaging of |num_machines| |board| devices with |image|.

        Sends an RPC to the autotest frontend to enqueue reimaging jobs on
        |num_machines| devices of type |board|

        @param build: the build to install (must be unique).
        @param num_machines: how many devices to reimage.
        @param board: which kind of devices to reimage.
        @return a frontend.Job object for the reimaging job we scheduled.
        """
        control_file = inject_vars(
            {'image_url': _image_url_pattern() % build, 'image_name': build},
            self._cf_getter.get_control_file_contents_by_name('autoupdate'))
        job_deps = []
        if self._pool:
            meta_host = self._pool
            board_label = board
            job_deps.append(board_label)
        else:
            # No pool specified use board.
            meta_host = board

        return self._afe.create_job(control_file=control_file,
                                    name=build + '-try',
                                    control_type='Server',
                                    meta_hosts=[meta_host] * num_machines,
                                    dependencies=job_deps)


    def _report_results(self, job, record):
        """
        Record results from a completed frontend.Job object.

        @param job: a completed frontend.Job object populated by
               frontend.AFE.poll_job_results.
        @param record: callable that records job status.
               prototype:
                 record(status, subdir, name, reason)
        """
        if job.result == True:
            record('GOOD', None, job.name)
            return

        for platform in job.results_platform_map:
            for status in job.results_platform_map[platform]:
                if status == 'Total':
                    continue
                for host in job.results_platform_map[platform][status]:
                    if host not in job.test_status:
                        record('ERROR', None, host, 'Job failed to run.')
                    elif status == 'Failed':
                        for test_status in job.test_status[host].fail:
                            record('FAIL', None, host, test_status.reason)
                    elif status == 'Aborted':
                        for test_status in job.test_status[host].fail:
                            record('ABORT', None, host, test_status.reason)
                    elif status == 'Completed':
                        record('GOOD', None, host)


class Suite(object):
    """
    A suite of tests, defined by some predicate over control file variables.

    Given a place to search for control files a predicate to match the desired
    tests, can gather tests and fire off jobs to run them, and then wait for
    results.

    @var _predicate: a function that should return True when run over a
         ControlData representation of a control file that should be in
         this Suite.
    @var _tag: a string with which to tag jobs run in this suite.
    @var _build: the build on which we're running this suite.
    @var _afe: an instance of AFE as defined in server/frontend.py.
    @var _tko: an instance of TKO as defined in server/frontend.py.
    @var _jobs: currently scheduled jobs, if any.
    @var _cf_getter: a control_file_getter.ControlFileGetter
    """


    @staticmethod
    def create_ds_getter(build):
        """
        @param build: the build on which we're running this suite.
        @return a FileSystemGetter instance that looks under |autotest_dir|.
        """
        return control_file_getter.DevServerGetter(
            build, dev_server.DevServer.create())


    @staticmethod
    def create_fs_getter(autotest_dir):
        """
        @param autotest_dir: the place to find autotests.
        @return a FileSystemGetter instance that looks under |autotest_dir|.
        """
        # currently hard-coded places to look for tests.
        subpaths = ['server/site_tests', 'client/site_tests',
                    'server/tests', 'client/tests']
        directories = [os.path.join(autotest_dir, p) for p in subpaths]
        return control_file_getter.FileSystemGetter(directories)


    @staticmethod
    def parse_tag(tag):
        """Splits a string on ',' optionally surrounded by whitespace."""
        return map(lambda x: x.strip(), tag.split(','))


    @staticmethod
    def name_in_tag_predicate(name):
        """Returns predicate that takes a control file and looks for |name|.

        Builds a predicate that takes in a parsed control file (a ControlData)
        and returns True if the SUITE tag is present and contains |name|.

        @param name: the suite name to base the predicate on.
        @return a callable that takes a ControlData and looks for |name| in that
                ControlData object's suite member.
        """
        return lambda t: hasattr(t, 'suite') and \
                         name in Suite.parse_tag(t.suite)


    @staticmethod
    def list_all_suites(build, cf_getter=None):
        """
        Parses all ControlData objects with a SUITE tag and extracts all
        defined suite names.

        @param cf_getter: control_file_getter.ControlFileGetter. Defaults to
                          using DevServerGetter.

        @return list of suites
        """
        if cf_getter is None:
            cf_getter = Suite.create_ds_getter(build)

        suites = set()
        predicate = lambda t: hasattr(t, 'suite')
        for test in Suite.find_and_parse_tests(cf_getter, predicate):
            suites.update(Suite.parse_tag(test.suite))
        return list(suites)


    @staticmethod
    def create_from_name(name, build, cf_getter=None, afe=None, tko=None,
                         pool=None, results_dir=None):
        """
        Create a Suite using a predicate based on the SUITE control file var.

        Makes a predicate based on |name| and uses it to instantiate a Suite
        that looks for tests in |autotest_dir| and will schedule them using
        |afe|.  Pulls control files from the default dev server.
        Results will be pulled from |tko| upon completion.

        @param name: a value of the SUITE control file variable to search for.
        @param build: the build on which we're running this suite.
        @param cf_getter: a control_file_getter.ControlFileGetter.
                          If None, default to using a DevServerGetter.
        @param afe: an instance of AFE as defined in server/frontend.py.
        @param tko: an instance of TKO as defined in server/frontend.py.
        @param pool: Specify the pool of machines to use for scheduling
                     purposes.
        @param results_dir: The directory where the job can write results to.
                            This must be set if you want job_id of sub-jobs
                            list in the job keyvals.
        @return a Suite instance.
        """
        if cf_getter is None:
            cf_getter = Suite.create_ds_getter(build)
        return Suite(Suite.name_in_tag_predicate(name),
                     name, build, cf_getter, afe, tko, pool, results_dir)


    def __init__(self, predicate, tag, build, cf_getter, afe=None, tko=None,
                 pool=None, results_dir=None):
        """
        Constructor

        @param predicate: a function that should return True when run over a
               ControlData representation of a control file that should be in
               this Suite.
        @param tag: a string with which to tag jobs run in this suite.
        @param build: the build on which we're running this suite.
        @param cf_getter: a control_file_getter.ControlFileGetter
        @param afe: an instance of AFE as defined in server/frontend.py.
        @param tko: an instance of TKO as defined in server/frontend.py.
        @param pool: Specify the pool of machines to use for scheduling
                purposes.
        @param results_dir: The directory where the job can write results to.
                            This must be set if you want job_id of sub-jobs
                            list in the job keyvals.
        """
        self._predicate = predicate
        self._tag = tag
        self._build = build
        self._cf_getter = cf_getter
        self._results_dir = results_dir
        self._afe = afe or frontend_wrappers.RetryingAFE(timeout_min=30,
                                                         delay_sec=10,
                                                         debug=False)
        self._tko = tko or frontend_wrappers.RetryingTKO(timeout_min=30,
                                                         delay_sec=10,
                                                         debug=False)
        self._pool = pool
        self._jobs = []
        self._tests = Suite.find_and_parse_tests(self._cf_getter,
                                                 self._predicate,
                                                 add_experimental=True)


    @property
    def tests(self):
        """
        A list of ControlData objects in the suite, with added |text| attr.
        """
        return self._tests


    def stable_tests(self):
        """
        |self.tests|, filtered for non-experimental tests.
        """
        return filter(lambda t: not t.experimental, self.tests)


    def unstable_tests(self):
        """
        |self.tests|, filtered for experimental tests.
        """
        return filter(lambda t: t.experimental, self.tests)


    def _create_job(self, test):
        """
        Thin wrapper around frontend.AFE.create_job().

        @param test: ControlData object for a test to run.
        @return a frontend.Job object with an added test_name member.
                test_name is used to preserve the higher level TEST_NAME
                name of the job.
        """
        job_deps = []
        if self._pool:
            meta_hosts = self._pool
            cros_label = VERSION_PREFIX + self._build
            job_deps.append(cros_label)
        else:
            # No pool specified use any machines with the following label.
            meta_hosts = VERSION_PREFIX + self._build
        test_obj = self._afe.create_job(
            control_file=test.text,
            name='/'.join([self._build, self._tag, test.name]),
            control_type=test.test_type.capitalize(),
            meta_hosts=[meta_hosts],
            dependencies=job_deps)

        setattr(test_obj, 'test_name', test.name)

        return test_obj


    def run_and_wait(self, record, add_experimental=True):
        """
        Synchronously run tests in |self.tests|.

        Schedules tests against a device running image |self._build|, and
        then polls for status, using |record| to print status when each
        completes.

        Tests returned by self.stable_tests() will always be run, while tests
        in self.unstable_tests() will only be run if |add_experimental| is true.

        @param record: callable that records job status.
                 prototype:
                   record(status, subdir, name, reason)
        @param add_experimental: schedule experimental tests as well, or not.
        """
        try:
            record('INFO', None, 'Start %s' % self._tag)
            self.schedule(add_experimental)
            try:
                for result in self.wait_for_results():
                    # |result| will be a tuple of a maximum of 4 entries and a
                    # minimum of 3. We use the first 3 for START and END
                    # entries so we separate those variables out for legible
                    # variable names, nothing more.
                    status = result[0]
                    test_name = result[2]
                    record('START', None, test_name)
                    record(*result)
                    record('END %s' % status, None, test_name)
            except Exception as e:
                logging.error(e)
                record('FAIL', None, self._tag,
                       'Exception waiting for results')
        except Exception as e:
            logging.error(e)
            record('FAIL', None, self._tag,
                   'Exception while scheduling suite')


    def schedule(self, add_experimental=True):
        """
        Schedule jobs using |self._afe|.

        frontend.Job objects representing each scheduled job will be put in
        |self._jobs|.

        @param add_experimental: schedule experimental tests as well, or not.
        """
        for test in self.stable_tests():
            logging.debug('Scheduling %s', test.name)
            self._jobs.append(self._create_job(test))

        if add_experimental:
            # TODO(cmasone): ensure I can log results from these differently.
            for test in self.unstable_tests():
                logging.debug('Scheduling %s', test.name)
                self._jobs.append(self._create_job(test))
        if self._results_dir:
            self._record_scheduled_jobs()


    def _record_scheduled_jobs(self):
        """
        Record scheduled job ids as keyvals, so they can be referenced later.
        """
        for job in self._jobs:
            job_id_owner = '%s-%s' % (job.id, job.owner)
            utils.write_keyval(self._results_dir, {job.test_name: job_id_owner})


    def _status_is_relevant(self, status):
        """
        Indicates whether the status of a given test is meaningful or not.

        @param status: frontend.TestStatus object to look at.
        @return True if this is a test result worth looking at further.
        """
        return not (status.test_name.startswith('SERVER_JOB') or
                    status.test_name.startswith('CLIENT_JOB'))


    def _collate_aborted(self, current_value, entry):
        """
        reduce() over a list of HostQueueEntries for a job; True if any aborted.

        Functor that can be reduced()ed over a list of
        HostQueueEntries for a job.  If any were aborted
        (|entry.aborted| exists and is True), then the reduce() will
        return True.

        Ex:
            entries = self._afe.run('get_host_queue_entries', job=job.id)
            reduce(self._collate_aborted, entries, False)

        @param current_value: the current accumulator (a boolean).
        @param entry: the current entry under consideration.
        @return the value of |entry.aborted| if it exists, False if not.
        """
        return current_value or ('aborted' in entry and entry['aborted'])


    def wait_for_results(self):
        """
        Wait for results of all tests in all jobs in |self._jobs|.

        Currently polls for results every 5s.  When all results are available,
        @return a list of tuples, one per test: (status, subdir, name, reason)
        """
        while self._jobs:
            for job in list(self._jobs):
                if not self._afe.get_jobs(id=job.id, finished=True):
                    continue

                self._jobs.remove(job)

                entries = self._afe.run('get_host_queue_entries', job=job.id)
                if reduce(self._collate_aborted, entries, False):
                    yield('ABORT', None, job.name)
                else:
                    statuses = self._tko.get_status_counts(job=job.id)
                    for s in filter(self._status_is_relevant, statuses):
                        yield(s.status, None, s.test_name, s.reason)
            time.sleep(5)


    @staticmethod
    def find_and_parse_tests(cf_getter, predicate, add_experimental=False):
        """
        Function to scan through all tests and find eligible tests.

        Looks at control files returned by _cf_getter.get_control_file_list()
        for tests that pass self._predicate().

        @param cf_getter: a control_file_getter.ControlFileGetter used to list
               and fetch the content of control files
        @param predicate: a function that should return True when run over a
               ControlData representation of a control file that should be in
               this Suite.
        @param add_experimental: add tests with experimental attribute set.

        @return list of ControlData objects that should be run, with control
                file text added in |text| attribute.
        """
        tests = {}
        files = cf_getter.get_control_file_list()
        for file in files:
            text = cf_getter.get_control_file_contents(file)
            try:
                found_test = control_data.parse_control_string(text,
                                                            raise_warnings=True)
                if not add_experimental and found_test.experimental:
                    continue

                found_test.text = text
                found_test.path = file
                tests[file] = found_test
            except control_data.ControlVariableException, e:
                logging.warn("Skipping %s\n%s", file, e)
            except Exception, e:
                logging.error("Bad %s\n%s", file, e)

        return [test for test in tests.itervalues() if predicate(test)]
