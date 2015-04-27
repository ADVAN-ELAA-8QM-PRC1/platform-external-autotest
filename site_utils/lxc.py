# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This module provides some tools to interact with LXC containers, for example:
  1. Download base container from given GS location, setup the base container.
  2. Create a snapshot as test container from base container.
  3. Mount a directory in drone to the test container.
  4. Run a command in the container and return the output.
  5. Cleanup, e.g., destroy the container.

This tool can also be used to set up a base container for test. For example,
  python lxc.py -s -p /tmp/container
This command will download and setup base container in directory /tmp/container.
After that command finishes, you can run lxc command to work with the base
container, e.g.,
  lxc-start -P /tmp/container -n base -d
  lxc-attach -P /tmp/container -n base
"""


import argparse
import logging
import os
import socket
import sys
import time

import common
import netifaces
from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib import global_config
from autotest_lib.client.common_lib.cros import retry
from autotest_lib.client.common_lib.cros.graphite import autotest_es
from autotest_lib.client.common_lib.cros.graphite import autotest_stats


config = global_config.global_config

# Name of the base container.
BASE = 'base'
# Naming convention of test container, e.g., test_300_1422862512_2424, where:
# 300:        The test job ID.
# 1422862512: The tick when container is created.
# 2424:       The PID of autoserv that starts the container.
TEST_CONTAINER_NAME_FMT = 'test_%s_%d_%d'
CONTAINER_AUTOTEST_DIR = '/usr/local/autotest'
# Naming convention of the result directory in test container.
RESULT_DIR_FMT = os.path.join(CONTAINER_AUTOTEST_DIR, 'results', '%s')
# Attributes to retrieve about containers.
ATTRIBUTES = ['name', 'state']

# Format for mount entry to share a directory in host with container.
# source is the directory in host, destination is the directory in container.
# readonly is a binding flag for readonly mount, its value should be `,ro`.
MOUNT_FMT = ('lxc.mount.entry = %(source)s %(destination)s none '
             'bind%(readonly)s 0 0')
# url to the base container.
CONTAINER_BASE_URL = config.get_config_value('AUTOSERV', 'container_base')
# Default directory used to store LXC containers.
DEFAULT_CONTAINER_PATH = config.get_config_value('AUTOSERV', 'container_path')

# Path to drone_temp folder in the container, which stores the control file for
# test job to run.
CONTROL_TEMP_PATH = os.path.join(CONTAINER_AUTOTEST_DIR, 'drone_tmp')

# Bash command to return the file count in a directory. Test the existence first
# so the command can return an error code if the directory doesn't exist.
COUNT_FILE_CMD = '[ -d %(dir)s ] && ls %(dir)s | wc -l'

# Command line to append content to a file
APPEND_CMD_FMT = ('echo \'%(content)s\' | sudo tee --append %(file)s'
                  '> /dev/null')

# Path to site-packates in Moblab
MOBLAB_SITE_PACKAGES = '/usr/lib64/python2.7/site-packages'
MOBLAB_SITE_PACKAGES_CONTAINER = '/usr/local/lib/python2.7/dist-packages/'

# Flag to indicate it's running in a Moblab. Due to crbug.com/457496, lxc-ls has
# different behavior in Moblab.
IS_MOBLAB = utils.is_moblab()

# Flag to indicate it's running in a VM(Ganeti instance). Due to t/16003207,
# lxc-clone does not support snapshot in Ganeti instance.
IS_VM = utils.is_vm()

# TODO(dshi): If we are adding more logic in how lxc should interact with
# different systems, we should consider code refactoring to use a setting-style
# object to store following flags mapping to different systems.
# moblab is on an old kernel, which does not support either overlayfs or aufs.
# Snapshot clone is disabled for moblab until its kernel is updated.
SUPPORT_SNAPSHOT_CLONE = not IS_MOBLAB
# overlayfs is the default clone backend storage. However it is not supported
# in Ganeti yet. Use aufs as the alternative.
SNAPSHOT_CLONE_REQUIRE_AUFS = IS_VM

# Number of seconds to wait for network to be up in a container.
NETWORK_INIT_TIMEOUT = 120
# Network bring up is slower in Moblab.
NETWORK_INIT_CHECK_INTERVAL = 2 if IS_MOBLAB else 0.1

# Type string for container related metadata.
CONTAINER_CREATE_METADB_TYPE = 'container_create'
CONTAINER_RUN_TEST_METADB_TYPE = 'container_run_test'

STATS_KEY = 'lxc.%s' % socket.gethostname().replace('.', '_')
timer = autotest_stats.Timer(STATS_KEY)

def run(cmd, sudo=True, **kwargs):
    """Runs a command on the local system.

    @param cmd: The command to run.
    @param sudo: True to run the command as root user, default to True.
    @param kwargs: Other parameters can be passed to utils.run, e.g., timeout.

    @returns: A CmdResult object.

    @raise error.CmdError: If there was a non-0 return code.
    """
    # TODO(dshi): crbug.com/459344 Set sudo to default to False when test
    # container can be unprivileged container.
    if sudo:
        cmd = 'sudo ' + cmd
    logging.debug(cmd)
    return utils.run(cmd, kwargs)


def is_in_container():
    """Check if the process is running inside a container.

    @return: True if the process is running inside a container, otherwise False.
    """
    try:
        run('cat /proc/1/cgroup | grep "/lxc/" || false')
        return True
    except error.CmdError:
        return False


def path_exists(path):
    """Check if path exists.

    If the process is not running with root user, os.path.exists may fail to
    check if a path owned by root user exists. This function uses command
    `ls path` to check if path exists.

    @param path: Path to check if it exists.

    @return: True if path exists, otherwise False.
    """
    try:
        run('ls "%s"' % path)
        return True
    except error.CmdError:
        return False


def _get_container_info_moblab(container_path, **filters):
    """Get a collection of container information in the given container path
    in a Moblab.

    TODO(crbug.com/457496): remove this method once python 3 can be installed
    in Moblab and lxc-ls command can use python 3 code.

    When running in Moblab, lxc-ls behaves differently from a server with python
    3 installed:
    1. lxc-ls returns a list of containers installed under /etc/lxc, the default
       lxc container directory.
    2. lxc-ls --active lists all active containers, regardless where the
       container is located.
    For such differences, we have to special case Moblab to make the behavior
    close to a server with python 3 installed. That is,
    1. List only containers in a given folder.
    2. Assume all active containers have state of RUNNING.

    @param container_path: Path to look for containers.
    @param filters: Key value to filter the containers, e.g., name='base'

    @return: A list of dictionaries that each dictionary has the information of
             a container. The keys are defined in ATTRIBUTES.
    """
    info_collection = []
    active_containers = run('lxc-ls --active').stdout.split()
    name_filter = filters.get('name', None)
    state_filter = filters.get('state', None)
    if filters and set(filters.keys()) - set(['name', 'state']):
        raise error.ContainerError('When running in Moblab, container list '
                                   'filter only supports name and state.')

    for name in os.listdir(container_path):
        # Skip all files and folders without rootfs subfolder.
        if (os.path.isfile(os.path.join(container_path, name)) or
            not path_exists(os.path.join(container_path, name, 'rootfs'))):
            continue
        info = {'name': name,
                'state': 'RUNNING' if name in active_containers else 'STOPPED'
               }
        if ((name_filter and name_filter != info['name']) or
            (state_filter and state_filter != info['state'])):
            continue

        info_collection.append(info)
    return info_collection


def get_container_info(container_path, **filters):
    """Get a collection of container information in the given container path.

    This method parse the output of lxc-ls to get a list of container
    information. The lxc-ls command output looks like:
    NAME      STATE    IPV4       IPV6  AUTOSTART  PID   MEMORY  RAM     SWAP
    --------------------------------------------------------------------------
    base      STOPPED  -          -     NO         -     -       -       -
    test_123  RUNNING  10.0.3.27  -     NO         8359  6.28MB  6.28MB  0.0MB

    @param container_path: Path to look for containers.
    @param filters: Key value to filter the containers, e.g., name='base'

    @return: A list of dictionaries that each dictionary has the information of
             a container. The keys are defined in ATTRIBUTES.
    """
    if IS_MOBLAB:
        return _get_container_info_moblab(container_path, **filters)

    cmd = 'lxc-ls -P %s -f -F %s' % (os.path.realpath(container_path),
                                     ','.join(ATTRIBUTES))
    output = run(cmd).stdout
    info_collection = []

    for line in output.splitlines()[2:]:
        info_collection.append(dict(zip(ATTRIBUTES, line.split())))
    if filters:
        filtered_collection = []
        for key, value in filters.iteritems():
            for info in info_collection:
                if key in info and info[key] == value:
                    filtered_collection.append(info)
        info_collection = filtered_collection
    return info_collection


def cleanup_if_fail():
    """Decorator to do cleanup if container fails to be set up.
    """
    def deco_cleanup_if_fail(func):
        """Wrapper for the decorator.

        @param func: Function to be called.
        """
        def func_cleanup_if_fail(*args, **kwargs):
            """Decorator to do cleanup if container fails to be set up.

            The first argument must be a ContainerBucket object, which can be
            used to retrieve the container object by name.

            @param func: function to be called.
            @param args: arguments for function to be called.
            @param kwargs: keyword arguments for function to be called.
            """
            bucket = args[0]
            name = utils.get_function_arg_value(func, 'name', args, kwargs)
            try:
                skip_cleanup = utils.get_function_arg_value(
                        func, 'skip_cleanup', args, kwargs)
            except (KeyError, ValueError):
                skip_cleanup = False
            try:
                return func(*args, **kwargs)
            except:
                exc_info = sys.exc_info()
                try:
                    container = bucket.get(name)
                    if container and not skip_cleanup:
                        container.destroy()
                except error.CmdError as e:
                    logging.error(e)

                try:
                    job_id = utils.get_function_arg_value(
                            func, 'job_id', args, kwargs)
                except (KeyError, ValueError):
                    job_id = ''
                autotest_es.post(use_http=True,
                                 type_str=CONTAINER_CREATE_METADB_TYPE,
                                 metadata={'drone': socket.gethostname(),
                                           'job_id': job_id,
                                           'success': False})

                # Raise the cached exception with original backtrace.
                raise exc_info[0], exc_info[1], exc_info[2]
        return func_cleanup_if_fail
    return deco_cleanup_if_fail


@retry.retry(error.CmdError, timeout_min=5)
def download_extract(url, target, extract_dir):
    """Download the file from given url and save it to the target, then extract.

    @param url: Url to download the file.
    @param target: Path of the file to save to.
    @param extract_dir: Directory to extract the content of the file to.
    """
    run('wget --timeout=300 -nv %s -O %s' % (url, target))
    run('tar -xvf %s -C %s' % (target, extract_dir))


class Container(object):
    """A wrapper class of an LXC container.

    The wrapper class provides methods to interact with a container, e.g.,
    start, stop, destroy, run a command. It also has attributes of the
    container, including:
    name: Name of the container.
    state: State of the container, e.g., ABORTING, RUNNING, STARTING, STOPPED,
           or STOPPING.

    lxc-ls can also collect other attributes of a container including:
    ipv4: IP address for IPv4.
    ipv6: IP address for IPv6.
    autostart: If the container will autostart at system boot.
    pid: Process ID of the container.
    memory: Memory used by the container, as a string, e.g., "6.2MB"
    ram: Physical ram used by the container, as a string, e.g., "6.2MB"
    swap: swap used by the container, as a string, e.g., "1.0MB"

    For performance reason, such info is not collected for now.

    The attributes available are defined in ATTRIBUTES constant.
    """

    def __init__(self, container_path, attribute_values):
        """Initialize an object of LXC container with given attribute values.

        @param container_path: Directory that stores the container.
        @param attribute_values: A dictionary of attribute values for the
                                 container.
        """
        self.container_path = os.path.realpath(container_path)

        for attribute, value in attribute_values.iteritems():
            setattr(self, attribute, value)


    def refresh_status(self):
        """Refresh the status information of the container.
        """
        containers = get_container_info(self.container_path, name=self.name)
        if not containers:
            raise error.ContainerError(
                    'No container found in directory %s with name of %s.' %
                    self.container_path, self.name)
        attribute_values = containers[0]
        for attribute, value in attribute_values.iteritems():
            setattr(self, attribute, value)


    def attach_run(self, command, bash=True):
        """Attach to a given container and run the given command.

        @param command: Command to run in the container.
        @param bash: Run the command through bash -c "command". This allows
                     pipes to be used in command. Default is set to True.

        @return: The output of the command.

        @raise error.CmdError: If container does not exist, or not running.
        """
        cmd = 'lxc-attach -P %s -n %s' % (self.container_path, self.name)
        if bash and not command.startswith('bash -c'):
            command = 'bash -c "%s"' % command
        cmd += ' -- %s' % command
        return run(cmd)


    def is_network_up(self):
        """Check if network is up in the container by curl base container url.

        @return: True if the network is up, otherwise False.
        """
        try:
            self.attach_run('curl --head %s' % CONTAINER_BASE_URL)
            return True
        except error.CmdError as e:
            logging.debug(e)
            return False


    @timer.decorate
    def start(self, wait_for_network=True):
        """Start the container.

        @param wait_for_network: True to wait for network to be up. Default is
                                 set to True.

        @raise ContainerError: If container does not exist, or fails to start.
        """
        cmd = 'lxc-start -P %s -n %s -d' % (self.container_path, self.name)
        output = run(cmd).stdout
        self.refresh_status()
        if self.state != 'RUNNING':
            raise error.ContainerError(
                    'Container %s failed to start. lxc command output:\n%s' %
                    (os.path.join(self.container_path, self.name),
                     output))

        if wait_for_network:
            logging.debug('Wait for network to be up.')
            start_time = time.time()
            utils.poll_for_condition(condition=self.is_network_up,
                                     timeout=NETWORK_INIT_TIMEOUT,
                                     sleep_interval=NETWORK_INIT_CHECK_INTERVAL)
            logging.debug('Network is up after %.2f seconds.',
                          time.time() - start_time)


    @timer.decorate
    def stop(self):
        """Stop the container.

        @raise ContainerError: If container does not exist, or fails to start.
        """
        cmd = 'lxc-stop -P %s -n %s' % (self.container_path, self.name)
        output = run(cmd).stdout
        self.refresh_status()
        if self.state != 'STOPPED':
            raise error.ContainerError(
                    'Container %s failed to be stopped. lxc command output:\n'
                    '%s' % (os.path.join(self.container_path, self.name),
                            output))


    @timer.decorate
    def destroy(self, force=True):
        """Destroy the container.

        @param force: Set to True to force to destroy the container even if it's
                      running. This is faster than stop a container first then
                      try to destroy it. Default is set to True.

        @raise ContainerError: If container does not exist or failed to destroy
                               the container.
        """
        cmd = 'lxc-destroy -P %s -n %s' % (self.container_path,
                                           self.name)
        if force:
            cmd += ' -f'
        run(cmd)


    def mount_dir(self, source, destination, readonly=False):
        """Mount a directory in host to a directory in the container.

        @param source: Directory in host to be mounted.
        @param destination: Directory in container to mount the source directory
        @param readonly: Set to True to make a readonly mount, default is False.
        """
        # Destination path in container must be relative.
        destination = destination.lstrip('/')
        # Path to the rootfs directory of the container. If the container is
        # created from base container by snapshot, base_dir should be set to
        # the path to the delta0 folder.
        base_dir = os.path.join(self.container_path, self.name, 'delta0')
        if not path_exists(base_dir):
            base_dir = os.path.join(self.container_path, self.name, 'rootfs')
        # Create directory in container for mount.
        run('mkdir -p %s' % os.path.join(base_dir, destination))
        config_file = os.path.join(self.container_path, self.name, 'config')
        mount = MOUNT_FMT % {'source': source,
                             'destination': destination,
                             'readonly': ',ro' if readonly else ''}
        run(APPEND_CMD_FMT % {'content': mount, 'file': config_file})


    def verify_autotest_setup(self, job_id):
        """Verify autotest code is set up properly in the container.

        @param job_id: ID of the job, used to format job result folder.

        @raise ContainerError: If autotest code is not set up properly.
        """
        # Test autotest code is setup by verifying a list of
        # (directory, minimum file count)
        if IS_MOBLAB:
            site_packages_path = MOBLAB_SITE_PACKAGES_CONTAINER
        else:
            site_packages_path = os.path.join(CONTAINER_AUTOTEST_DIR,
                                              'site-packages')
        directories_to_check = [
                (CONTAINER_AUTOTEST_DIR, 3),
                (RESULT_DIR_FMT % job_id, 0),
                (site_packages_path, 3)]
        for directory, count in directories_to_check:
            result = self.attach_run(command=(COUNT_FILE_CMD %
                                              {'dir': directory})).stdout
            logging.debug('%s entries in %s.', int(result), directory)
            if int(result) < count:
                raise error.ContainerError('%s is not properly set up.' %
                                           directory)


class ContainerBucket(object):
    """A wrapper class to interact with containers in a specific container path.
    """

    def __init__(self, container_path=DEFAULT_CONTAINER_PATH):
        """Initialize a ContainerBucket.

        @param container_path: Path to the directory used to store containers.
                               Default is set to AUTOSERV/container_path in
                               global config.
        """
        self.container_path = os.path.realpath(container_path)


    def get_all(self):
        """Get details of all containers.

        @return: A dictionary of all containers with detailed attributes,
                 indexed by container name.
        """
        info_collection = get_container_info(self.container_path)
        containers = {}
        for info in info_collection:
            container = Container(self.container_path, info)
            containers[container.name] = container
        return containers


    def get(self, name):
        """Get a container with matching name.

        @param name: Name of the container.

        @return: A container object with matching name. Returns None if no
                 container matches the given name.
        """
        return self.get_all().get(name, None)


    def exist(self, name):
        """Check if a container exists with the given name.

        @param name: Name of the container.

        @return: True if the container with the given name exists, otherwise
                 returns False.
        """
        return self.get(name) != None


    def destroy_all(self):
        """Destroy all containers, base must be destroyed at the last.
        """
        containers = self.get_all().values()
        for container in sorted(containers,
                                key=lambda n: 1 if n.name == BASE else 0):
            logging.info('Destroy container %s.', container.name)
            container.destroy()


    @timer.decorate
    def create_from_base(self, name):
        """Create a container from the base container.

        @param name: Name of the container.

        @return: A Container object for the created container.

        @raise ContainerError: If the container already exist.
        @raise error.CmdError: If lxc-clone call failed for any reason.
        """
        if self.exist(name):
            raise error.ContainerError('Container %s already exists.' % name)
        # TODO(crbug.com/464834): Snapshot clone is disabled until Moblab can
        # support overlayfs, which requires a newer kernel.
        snapshot = '-s' if SUPPORT_SNAPSHOT_CLONE else ''
        aufs = '-B aufs' if SNAPSHOT_CLONE_REQUIRE_AUFS else ''
        cmd = ('lxc-clone -p %s -P %s %s' %
               (self.container_path, self.container_path,
                ' '.join([BASE, name, snapshot, aufs])))
        run(cmd)
        return self.get(name)


    @cleanup_if_fail()
    def setup_base(self, name=BASE, force_delete=False):
        """Setup base container.

        @param name: Name of the base container, default to base.
        @param force_delete: True to force to delete existing base container.
                             This action will destroy all running test
                             containers. Default is set to False.
        """
        if not self.container_path:
            raise error.ContainerError(
                    'You must set a valid directory to store containers in '
                    'global config "AUTOSERV/ container_path".')

        if not os.path.exists(self.container_path):
            os.makedirs(self.container_path)

        base_path = os.path.join(self.container_path, name)
        if self.exist(name) and not force_delete:
            logging.error(
                    'Base container already exists. Set force_delete to True '
                    'to force to re-stage base container. Note that this '
                    'action will destroy all running test containers')
            return

        # Destroy existing base container if exists.
        if self.exist(name):
            # TODO: We may need to destroy all snapshots created from this base
            # container, not all container.
            self.destroy_all()

        # Download and untar the base container.
        tar_path = os.path.join(self.container_path, '%s.tar.xz' % name)
        path_to_cleanup = [tar_path, base_path]
        for path in path_to_cleanup:
            if os.path.exists(path):
                run('rm -rf "%s"' % path)
        download_extract(CONTAINER_BASE_URL, tar_path, self.container_path)
        # Remove the downloaded container tar file.
        run('rm "%s"' % tar_path)
        # Set proper file permission.
        # TODO(dshi): Change root to current user when test container can be
        # unprivileged container.
        run('sudo chown -R root "%s"' % base_path)
        run('sudo chgrp -R root "%s"' % base_path)

        # Update container config with container_path from global config.
        config_path = os.path.join(base_path, 'config')
        run('sed -i "s|container_dir|%s|g" "%s"' %
            (self.container_path, config_path))


    def get_host_ip(self):
        """Get the IP address of the host running containers on lxcbr*.

        This function gets the IP address on network interface lxcbr*. The
        assumption is that lxc uses the network interface started with "lxcbr".

        @return: IP address of the host running containers.
        """
        lxc_network = None
        for name in netifaces.interfaces():
            if name.startswith('lxcbr'):
                lxc_network = name
                break
        if not lxc_network:
            raise error.ContainerError('Failed to find network interface used '
                                       'by lxc. All existing interfaces are: '
                                       '%s' % netifaces.interfaces())
        return netifaces.ifaddresses(lxc_network)[netifaces.AF_INET][0]['addr']


    def modify_shadow_config(self, container, shadow_config):
        """Update the shadow config used in container with correct values.

        1. Disable master ssh connection in shadow config, as it is not working
           properly in container yet, and produces noise in the log.
        2. Update AUTOTEST_WEB/host and SERVER/hostname to be the IP of the host
           if any is set to localhost or 127.0.0.1. Otherwise, set it to be the
           FQDN of the config value.

        @param container: The container object to be updated in shadow config.
        @param shadow_config: Path the the shadow config file to be used in the
                              container.
        """
        # Inject "AUTOSERV/enable_master_ssh: False" in shadow config as
        # container does not support master ssh connection yet.
        container.attach_run(
                'echo $\'\n[AUTOSERV]\nenable_master_ssh: False\n\' >> %s' %
                shadow_config)

        host_ip = self.get_host_ip()
        local_names = ['localhost', '127.0.0.1']

        db_host = config.get_config_value('AUTOTEST_WEB', 'host')
        if db_host.lower() in local_names:
            new_host = host_ip
        else:
            new_host = socket.getfqdn(db_host)
        container.attach_run('echo $\'\n[AUTOTEST_WEB]\nhost: %s\n\' >> %s' %
                             (new_host, shadow_config))

        afe_host = config.get_config_value('SERVER', 'hostname')
        if afe_host.lower() in local_names:
            new_host = host_ip
        else:
            new_host = socket.getfqdn(afe_host)
        container.attach_run('echo $\'\n[SERVER]\nhostname: %s\n\' >> %s' %
                             (new_host, shadow_config))


    @timer.decorate
    @cleanup_if_fail()
    def setup_test(self, name, job_id, server_package_url, result_path,
                   control=None, skip_cleanup=False):
        """Setup test container for the test job to run.

        The setup includes:
        1. Install autotest_server package from given url.
        2. Copy over local shadow_config.ini.
        3. Mount local site-packages.
        4. Mount test result directory.

        TODO(dshi): Setup also needs to include test control file for autoserv
                    to run in container.

        @param name: Name of the container.
        @param job_id: Job id for the test job to run in the test container.
        @param server_package_url: Url to download autotest_server package.
        @param result_path: Directory to be mounted to container to store test
                            results.
        @param control: Path to the control file to run the test job. Default is
                        set to None.
        @param skip_cleanup: Set to True to skip cleanup, used to troubleshoot
                             container failures.

        @return: A Container object for the test container.

        @raise ContainerError: If container does not exist, or not running.
        """
        start_time = time.time()

        if not os.path.exists(result_path):
            raise error.ContainerError('Result directory does not exist: %s',
                                       result_path)
        result_path = os.path.abspath(result_path)

        # Create test container from the base container.
        container = self.create_from_base(name)

        # Deploy server side package
        usr_local_path = os.path.join(
                self.container_path, name,
                'rootfs' if not SUPPORT_SNAPSHOT_CLONE else 'delta0',
                'usr', 'local')
        autotest_pkg_path = os.path.join(usr_local_path,
                                         'autotest_server_package.tar.bz2')
        autotest_path = os.path.join(usr_local_path, 'autotest')
        # sudo is required so os.makedirs may not work.
        run('mkdir -p %s'% usr_local_path)

        download_extract(server_package_url, autotest_pkg_path, usr_local_path)
        # Copy over local shadow_config.ini
        shadow_config = os.path.join(common.autotest_dir, 'shadow_config.ini')
        container_shadow_config = os.path.join(autotest_path,
                                               'shadow_config.ini')
        run('cp %s %s' % (shadow_config, container_shadow_config))

        # Copy over local .ssh/config file if exists.
        ssh_config = os.path.expanduser('~/.ssh/config')
        container_ssh = os.path.join(
                self.container_path, name,
                'rootfs' if not SUPPORT_SNAPSHOT_CLONE else 'delta0',
                'root', '.ssh')
        container_ssh_config = os.path.join(container_ssh, 'config')
        if os.path.exists(ssh_config):
            run('mkdir -p %s'% container_ssh)
            run('cp "%s" "%s"' % (ssh_config, container_ssh_config))
            # Remove domain specific flags.
            run('sed -i "s/UseProxyIf=false//g" %s' % container_ssh_config)
            # TODO(dshi): crbug.com/451622 ssh connection loglevel is set to
            # ERROR in container before master ssh connection works. This is
            # to avoid logs being flooded with warning `Permanently added
            # '[hostname]' (RSA) to the list of known hosts.` (crbug.com/478364)
            # The sed command injects following at the beginning of .ssh/config
            # used in config. With such change, ssh command will not post
            # warnings.
            # Host *
            #   LogLevel Error
            run('sed -i "1s/^/Host *\\n  LogLevel ERROR\\n\\n/" %s' %
                container_ssh_config)

        # Copy over resolv.conf for DNS search path. The file is copied to
        # autotest folder so its content can be appended in /etc/resolv.conf
        # after the container is started.
        resolv_conf = '/etc/resolv.conf'
        container_resolv_conf = os.path.join(autotest_path, 'resolv.conf')
        run('cp "%s" "%s"' % (resolv_conf, container_resolv_conf))

        # Copy over control file to run the test job.
        if control:
            container_drone_temp = os.path.join(autotest_path, 'drone_tmp')
            run('mkdir -p %s'% container_drone_temp)
            container_control_file = os.path.join(
                    container_drone_temp, os.path.basename(control))
            run('cp %s %s' % (control, container_control_file))

        if IS_MOBLAB:
            site_packages_path = MOBLAB_SITE_PACKAGES
            site_packages_container_path = MOBLAB_SITE_PACKAGES_CONTAINER[1:]
        else:
            site_packages_path = os.path.join(common.autotest_dir,
                                              'site-packages')
            site_packages_container_path = os.path.join(CONTAINER_AUTOTEST_DIR,
                                                        'site-packages')
        mount_entries = [(site_packages_path, site_packages_container_path,
                          True),
                         (os.path.join(common.autotest_dir, 'puppylab'),
                          os.path.join(CONTAINER_AUTOTEST_DIR, 'puppylab'),
                          True),
                         (result_path,
                          os.path.join(RESULT_DIR_FMT % job_id),
                          False),
                        ]
        # Update container config to mount directories.
        for source, destination, readonly in mount_entries:
            container.mount_dir(source, destination, readonly)

        # Update file permissions.
        # TODO(dshi): crbug.com/459344 Skip following action when test container
        # can be unprivileged container.
        run('chown -R root "%s"' % autotest_path)
        run('chgrp -R root "%s"' % autotest_path)

        container.start(name)
        # Make sure the rsa file has right permission.
        container.attach_run('chmod 700 /root/.ssh/testing_rsa')
        container.attach_run('chmod 700 /root/.ssh/config')
        # Update resolv.conf
        container.attach_run('cat /usr/local/autotest/resolv.conf >> '
                             '/etc/resolv.conf')

        self.modify_shadow_config(
                container,
                os.path.join(CONTAINER_AUTOTEST_DIR, 'shadow_config.ini'))

        container.verify_autotest_setup(job_id)

        autotest_es.post(use_http=True,
                         type_str=CONTAINER_CREATE_METADB_TYPE,
                         metadata={'drone': socket.gethostname(),
                                   'job_id': job_id,
                                   'time_used': time.time() - start_time,
                                   'success': True})

        logging.debug('Test container %s is set up.', name)
        return container


def parse_options():
    """Parse command line inputs.

    @raise argparse.ArgumentError: If command line arguments are invalid.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('-s', '--setup', action='store_true',
                        default=False,
                        help='Set up base container.')
    parser.add_argument('-p', '--path', type=str,
                        help='Directory to store the container.',
                        default=DEFAULT_CONTAINER_PATH)
    parser.add_argument('-f', '--force_delete', action='store_true',
                        default=False,
                        help=('Force to delete existing containers and rebuild '
                              'base containers.'))
    options = parser.parse_args()
    if not options.setup and not options.force_delete:
        raise argparse.ArgumentError(
                'Use --setup to setup a base container, or --force_delete to '
                'delete all containers in given path.')
    return options


def main():
    """main script."""
    options = parse_options()
    bucket = ContainerBucket(container_path=options.path)
    if options.setup:
        bucket.setup_base(force_delete=options.force_delete)
    elif options.force_delete:
        bucket.destroy_all()


if __name__ == '__main__':
    main()
