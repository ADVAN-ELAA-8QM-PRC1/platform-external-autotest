# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import datetime, logging

import common

from autotest_lib.client.common_lib import base_job
from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib import priorities
from autotest_lib.client.common_lib import time_utils
from autotest_lib.client.common_lib import utils
from autotest_lib.client.common_lib.cros import dev_server
from autotest_lib.server.cros import provision
from autotest_lib.server.cros.dynamic_suite import constants
from autotest_lib.server.cros.dynamic_suite import frontend_wrappers
from autotest_lib.server.cros.dynamic_suite import tools
from autotest_lib.server.cros.dynamic_suite.suite import Suite
from autotest_lib.tko import utils as tko_utils



"""CrOS dynamic test suite generation and execution module.

This module implements runtime-generated test suites for CrOS.
Design doc: http://goto.google.com/suitesv2

Individual tests can declare themselves as a part of one or more
suites, and the code here enables control files to be written
that can refer to these "dynamic suites" by name.  We also provide
support for reimaging devices with a given build and running a
dynamic suite across all reimaged devices.

The public API for defining a suite includes one method: reimage_and_run().
A suite control file can be written by importing this module and making
an appropriate call to this single method.  In normal usage, this control
file will be run in a 'hostless' server-side autotest job, scheduling
sub-jobs to do the needed reimaging and test running.

Example control file:

import common
from autotest_lib.server.cros import provision
from autotest_lib.server.cros.dynamic_suite import dynamic_suite

dynamic_suite.reimage_and_run(
    build=build, board=board, name='bvt', job=job, pool=pool,
    check_hosts=check_hosts, add_experimental=True, num=num,
    devserver_url=devserver_url, version_prefix=provision.CROS_VERSION_PREFIX)

This will -- at runtime -- find all control files that contain "bvt" in their
"SUITE=" clause, schedule jobs to reimage |num| or less devices in the
specified pool of the specified board with the specified build and, upon
completion of those jobs, schedule and wait for jobs that run all the tests it
discovered.

Suites can be run by using the atest command-line tool:
  atest suite create -b <board> -i <build/name> <suite>
e.g.
  atest suite create -b x86-mario -i x86-mario/R20-2203.0.0 bvt

-------------------------------------------------------------------------
Implementation details

A Suite instance represents a single test suite, defined by some predicate
run over all known control files.  The simplest example is creating a Suite
by 'name'.

create_suite_job() takes the parameters needed to define a suite run (board,
build to test, machine pool, and which suite to run), ensures important
preconditions are met, finds the appropraite suite control file, and then
schedules the hostless job that will do the rest of the work.

Note that we have more than one Dev server in our test lab architecture.
We currently load balance per-build being tested, so one and only one dev
server is used by any given run through the reimaging/testing flow.

- create_suite_job()
The primary role of create_suite_job() is to ensure that the required
artifacts for the build to be tested are staged on the dev server.  This
includes payloads required to autoupdate machines to the desired build, as
well as the autotest control files appropriate for that build.  Then, the
RPC pulls the control file for the suite to be run from the dev server and
uses it to create the suite job with the autotest frontend.

     +----------------+
     | Google Storage |                                Client
     +----------------+                                   |
               | ^                                        | create_suite_job()
 payloads/     | |                                        |
 control files | | request                                |
               V |                                        V
       +-------------+   download request    +--------------------------+
       |             |<----------------------|                          |
       | Dev Server  |                       | Autotest Frontend (AFE)  |
       |             |---------------------->|                          |
       +-------------+  suite control file   +--------------------------+
                                                          |
                                                          V
                                                      Suite Job (hostless)

- Reimage and Run
The overall process is to schedule all the tests, and then wait for the tests
to complete.

- The Reimaging Process

As an artifact of an old implementation, the number of machines to use
is called the 'sharding_factor', and the default is defined in the [CROS]
section of global_config.ini.  This can be overridden by passing a 'num=N'
parameter to create_suite_job(), which is piped through to reimage_and_run()
just like the 'build' and 'board' parameters are.  However, with provisioning,
this machine accounting hasn't been implemented nor removed.  However, 'num' is
still passed around, as it might be used one day.

A test control file can specify a list of DEPENDENCIES, which are really just
the set of labels a host needs to have in order for that test to be scheduled
on it.  In the case of a dynamic_suite, many tests in the suite may have
DEPENDENCIES specified.  All tests are scheduled with the DEPENDENCIES that
they specify, along with any suite dependencies that were specified, and the
scheduler will find and provision a host capable of running the test.

- Scheduling Suites
A Suite instance uses the labels specified in the suite dependencies to
schedule tests across all the hosts in the pool.  It then waits for all these
jobs.  As an optimization, the Dev server stages the payloads necessary to
run a suite in the background _after_ it has completed all the things
necessary for reimaging.  Before running a suite, reimage_and_run() calls out
to the Dev server and blocks until it's completed staging all build artifacts
needed to run test suites.

Step by step:
0) At instantiation time, find all appropriate control files for this suite
   that were included in the build to be tested.  To do this, we consult the
   Dev Server, where all these control files are staged.

          +------------+    control files?     +--------------------------+
          |            |<----------------------|                          |
          | Dev Server |                       | Autotest Frontend (AFE)  |
          |            |---------------------->|       [Suite Job]        |
          +------------+    control files!     +--------------------------+

1) Now that the Suite instance exists, it schedules jobs for every control
   file it deemed appropriate, to be run on the hosts that were labeled
   by the provisioning.  We stuff keyvals into these jobs, indicating what
   build they were testing and which suite they were for.

   +--------------------------+ Job for VersLabel       +--------+
   |                          |------------------------>| Host 1 | VersLabel
   | Autotest Frontend (AFE)  |            +--------+   +--------+
   |       [Suite Job]        |----------->| Host 2 |
   +--------------------------+ Job for    +--------+
       |                ^       VersLabel        VersLabel
       |                |
       +----------------+
        One job per test
        {'build': build/name,
         'suite': suite_name}

2) Now that all jobs are scheduled, they'll be doled out as labeled hosts
   finish their assigned work and become available again.

- Waiting on Suites
0) As we clean up each test job, we check to see if any crashes occurred.  If
   they did, we look at the 'build' keyval in the job to see which build's debug
   symbols we'll need to symbolicate the crash dump we just found.

1) Using this info, we tell a special Crash Server to stage the required debug
   symbols. Once that's done, we ask the Crash Server to use those symbols to
   symbolicate the crash dump in question.

     +----------------+
     | Google Storage |
     +----------------+
          |     ^
 symbols! |     | symbols?
          V     |
      +------------+  stage symbols for build  +--------------------------+
      |            |<--------------------------|                          |
      |   Crash    |                           |                          |
      |   Server   |   dump to symbolicate     | Autotest Frontend (AFE)  |
      |            |<--------------------------|       [Suite Job]        |
      |            |-------------------------->|                          |
      +------------+    symbolicated dump      +--------------------------+

2) As jobs finish, we record their success or failure in the status of the suite
   job.  We also record a 'job keyval' in the suite job for each test, noting
   the job ID and job owner.  This can be used to refer to test logs later.
3) Once all jobs are complete, status is recorded for the suite job, and the
   job_repo_url host attribute is removed from all hosts used by the suite.

"""


DEFAULT_TRY_JOB_TIMEOUT_MINS = tools.try_job_timeout_mins()

# Relevant CrosDynamicSuiteExceptions are defined in client/common_lib/error.py.

class SuiteSpec(object):
    """
    This class contains the info that defines a suite run.

    Currently required:
    @var build: the build to install e.g.
                  x86-alex-release/R18-1655.0.0-a1-b1584.
    @var board: which kind of devices to reimage.
    @var devserver: An instance of the devserver to use with this suite.
    @var name: a value of the SUITE control file variable to search for.
    @var job: an instance of client.common_lib.base_job representing the
                currently running suite job.

    Currently supported optional fields:
    @var pool: specify the pool of machines to use for scheduling purposes.
               Default: None
    @var num: the maximum number of devices to reimage.
              Default in global_config
    @var check_hosts: require appropriate hosts to be available now.
    @var add_experimental: schedule experimental tests as well, or not.
                           Default: True
    @var dependencies: map of test names to dependency lists.
                       Initially {'': []}.
    @param suite_dependencies: A string with a comma separated list of suite
                               level dependencies, which act just like test
                               dependencies and are appended to each test's
                               set of dependencies at job creation time.
    @param predicate: Optional argument. If present, should be a function
                      mapping ControlData objects to True if they should be
                      included in suite. If argument is absent, suite
                      behavior will default to creating a suite of based
                      on the SUITE field of control files.
    """
    def __init__(self, build=None, board=None, name=None, job=None,
                 pool=None, num=None, check_hosts=True,
                 add_experimental=True, file_bugs=False,
                 file_experimental_bugs=False, max_runtime_mins=24*60,
                 timeout=24, timeout_mins=None, firmware_reimage=False,
                 suite_dependencies=[], version_prefix=None,
                 bug_template={}, devserver_url=None,
                 priority=priorities.Priority.DEFAULT, predicate=None,
                 wait_for_results=True, job_retry=False, **dargs):
        """
        Vets arguments for reimage_and_run() and populates self with supplied
        values.

        Currently required args:
        @param build: the build to install e.g.
                      x86-alex-release/R18-1655.0.0-a1-b1584.
        @param board: which kind of devices to reimage.
        @param name: a value of the SUITE control file variable to search for.
        @param job: an instance of client.common_lib.base_job representing the
                    currently running suite job.
        @param devserver_url: url to the selected devserver.

        Currently supported optional args:
        @param pool: specify the pool of machines to use for scheduling purposes
                     Default: None
        @param num: the maximum number of devices to reimage.
                    Default in global_config
        @param check_hosts: require appropriate hosts to be available now.
        @param add_experimental: schedule experimental tests as well, or not.
                                 Default: True
        @param file_bugs: File bugs when tests in this suite fail.
                          Default: False
        @param file_experimental_bugs: File bugs when experimental tests in
                                       this suite fail.
                                       Default: False
        @param max_runtime_mins: Max runtime in mins for each of the sub-jobs
                                 this suite will run.
        @param timeout: Max lifetime in hours for each of the sub-jobs that
                        this suite run.
        @param firmware_reimage: True if we should use FW_VERSION_PREFIX as
                                 the version_prefix.
                                 False if we should use CROS_VERSION_PREFIX as
                                 the version_prefix.
                                 (This flag has now been deprecated in favor of
                                  version_prefix.)
        @param suite_dependencies: A list of strings of suite level
                                   dependencies, which act just like test
                                   dependencies and are appended to each test's
                                   set of dependencies at job creation time.
                                   A string of comma seperated labels is
                                   accepted for backwards compatibility.
        @param bug_template: A template dictionary specifying the default bug
                             filing options for failures in this suite.
        @param version_prefix: A version prefix from provision.py that the
                               tests should be scheduled with.
        @param priority: Integer priority level.  Higher is more important.
        @param predicate: Optional argument. If present, should be a function
                          mapping ControlData objects to True if they should be
                          included in suite. If argument is absent, suite
                          behavior will default to creating a suite of based
                          on the SUITE field of control files.
        @param wait_for_results: Set to False to run the suite job without
                                 waiting for test jobs to finish. Default is
                                 True.
        @param job_retry: Set to True to enable job-level retry. Default is
                          False.

        @param **dargs: these arguments will be ignored.  This allows us to
                        deprecate and remove arguments in ToT while not
                        breaking branch builds.
        """
        required_keywords = {'build': str,
                             'board': str,
                             'name': str,
                             'job': base_job.base_job,
                             'devserver_url': str}
        for key, expected in required_keywords.iteritems():
            value = locals().get(key)
            if not value or not isinstance(value, expected):
                raise error.SuiteArgumentException(
                    "reimage_and_run() needs %s=<%r>" % (key, expected))
        self.board = 'board:%s' % board
        self.devserver = dev_server.ImageServer(devserver_url)
        self.build = self.devserver.translate(build)
        self.name = name
        self.job = job
        if pool:
            self.pool = 'pool:%s' % pool
        else:
            self.pool = pool
        self.num = num
        self.check_hosts = check_hosts
        self.skip_reimage = skip_reimage
        self.add_experimental = add_experimental
        self.file_bugs = file_bugs
        self.file_experimental_bugs = file_experimental_bugs
        self.dependencies = {'': []}
        self.max_runtime_mins = max_runtime_mins
        self.timeout = timeout
        self.timeout_mins = timeout_mins or timeout * 60
        self.firmware_reimage = firmware_reimage
        if isinstance(suite_dependencies, str):
            self.suite_dependencies = [dep.strip(' ') for dep
                                       in suite_dependencies.split(',')]
        else:
            self.suite_dependencies = suite_dependencies
        self.bug_template = bug_template
        self.version_prefix = version_prefix
        self.priority = priority
        self.predicate = predicate
        self.wait_for_results = wait_for_results
        self.job_retry = job_retry


def skip_reimage(g):
    """
    Pulls the SKIP_IMAGE value out of a global variables dictionary.
    @param g: The global variables dictionary.
    @return:  Value associated with SKIP-IMAGE
    """
    return False


def reimage_and_run(**dargs):
    """
    Backward-compatible API for dynamic_suite.

    Will re-image a number of devices (of the specified board) with the
    provided build, and then run the indicated test suite on them.
    Guaranteed to be compatible with any build from stable to dev.

    @param dargs: Dictionary containing the arguments listed below.

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
    @param num: the maximum number of devices to reimage.
                Default in global_config
    @param check_hosts: require appropriate hosts to be available now.
    @param add_experimental: schedule experimental tests as well, or not.
                             Default: True
    @param file_bugs: automatically file bugs on test failures.
                      Default: False
    @param suite_dependencies: A string with a comma separated list of suite
                               level dependencies, which act just like test
                               dependencies and are appended to each test's
                               set of dependencies at job creation time.
    @param devserver_url: url to the selected devserver.
    @param predicate: Optional argument. If present, should be a function
                      mapping ControlData objects to True if they should be
                      included in suite. If argument is absent, suite
                      behavior will default to creating a suite of based
                      on the SUITE field of control files.
    @param job_retry: A bool value indicating whether jobs should be retired
                      on failure. If True, the field 'JOB_RETRIES' in control
                      files will be respected. If False, do not retry.

    @raises AsynchronousBuildFailure: if there was an issue finishing staging
                                      from the devserver.
    @raises MalformedDependenciesException: if the dependency_info file for
                                            the required build fails to parse.
    """
    suite_spec = SuiteSpec(**dargs)

    # Horrible hacks to handle backwards compatibility, overall goal here is
    # reimage_firmware == True -> Firmware
    # reimage_firmware == False AND version_prefix == None -> OS
    # reimage_firmware == False AND version_prefix != None -> version_prefix
    # and once we've set version_prefix right, ignore that reimage_firmware
    # has ever existed...
    # Remove all this code and reimage_firmware once R31 falls off stable.
    if suite_spec.firmware_reimage:
        suite_spec.version_prefix = provision.FW_VERSION_PREFIX
        logging.warning("reimage_and_run |firmware_reimage=True| argument "
                "has been deprecated. Please use "
                "|version_prefix=provision.FW_VERSION_PREFIX| instead.")
    elif not suite_spec.version_prefix:
        suite_spec.version_prefix = provision.CROS_VERSION_PREFIX

    suite_spec.firmware_reimage = False
    # </backwards_compatibility_hacks>

    # version_prefix+build should make it into each test as a DEPENDENCY.  The
    # easiest way to do this is to tack it onto the suite_dependencies.
    if suite_spec.version_prefix:
        dependency = provision.join(suite_spec.version_prefix, suite_spec.build)
        suite_spec.suite_dependencies.append(dependency)

    afe = frontend_wrappers.RetryingAFE(timeout_min=30, delay_sec=10,
                                        user=suite_spec.job.user, debug=False)
    tko = frontend_wrappers.RetryingTKO(timeout_min=30, delay_sec=10,
                                        user=suite_spec.job.user, debug=False)

    try:
        my_job_id = int(tko_utils.get_afe_job_id(dargs['job'].tag))
        logging.debug('Determined own job id: %d', my_job_id)
    except ValueError:
        my_job_id = None
        logging.warning('Could not determine own job id.')

    if suite_spec.predicate is None:
        predicate = Suite.name_in_tag_predicate(suite_spec.name)
    else:
        predicate = suite_spec.predicate

    _perform_reimage_and_run(suite_spec, afe, tko,
                             predicate, suite_job_id=my_job_id)

    logging.debug('Returning from dynamic_suite.reimage_and_run.')


def _perform_reimage_and_run(spec, afe, tko, predicate, suite_job_id=None):
    """
    Do the work of reimaging hosts and running tests.

    @param spec: a populated SuiteSpec object.
    @param afe: an instance of AFE as defined in server/frontend.py.
    @param tko: an instance of TKO as defined in server/frontend.py.
    @param predicate: A function mapping ControlData objects to True if they
                      should be included in the suite.
    @param suite_job_id: Job id that will act as parent id to all sub jobs.
                         Default: None
    """
    # We can't do anything else until the devserver has finished downloading
    # autotest.tar so that we can get the control files we should schedule.
    try:
        spec.devserver.stage_artifacts(
                spec.build, ['control_files', 'test_suites'])
    except dev_server.DevServerException as e:
        # If we can't get the control files, there's nothing to run.
        raise error.AsynchronousBuildFailure(e)

    timestamp = datetime.datetime.now().strftime(time_utils.TIME_FMT)
    utils.write_keyval(
        spec.job.resultdir,
        {constants.ARTIFACT_FINISHED_TIME: timestamp})

    suite = Suite.create_from_predicates(
        predicates=[predicate], name=spec.name,
        build=spec.build, board=spec.board, devserver=spec.devserver,
        afe=afe, tko=tko, pool=spec.pool,
        results_dir=spec.job.resultdir,
        max_runtime_mins=spec.max_runtime_mins, timeout_mins=spec.timeout_mins,
        file_bugs=spec.file_bugs,
        file_experimental_bugs=spec.file_experimental_bugs,
        suite_job_id=suite_job_id, extra_deps=spec.suite_dependencies,
        priority=spec.priority, wait_for_results=spec.wait_for_results,
        job_retry=spec.job_retry)

    # Now we get to asychronously schedule tests.
    suite.schedule(spec.job.record_entry, spec.add_experimental)

    if suite.wait_for_results:
        logging.debug('Waiting on suite.')
        suite.wait(spec.job.record_entry, spec.bug_template)
        logging.debug('Finished waiting on suite. '
                      'Returning from _perform_reimage_and_run.')
    else:
        logging.info('wait_for_results is set to False, suite job will exit '
                     'without waiting for test jobs to finish.')
