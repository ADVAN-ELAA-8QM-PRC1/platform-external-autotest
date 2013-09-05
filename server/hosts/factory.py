"""Provides a factory method to create a host object."""


from autotest_lib.client.common_lib import error, global_config
from autotest_lib.server import autotest, utils as server_utils
from autotest_lib.server.hosts import site_factory, cros_host, ssh_host, serial
from autotest_lib.server.hosts import logfile_monitor


DEFAULT_FOLLOW_PATH = '/var/log/kern.log'
DEFAULT_PATTERNS_PATH = 'console_patterns'
SSH_ENGINE = global_config.global_config.get_config_value('AUTOSERV',
                                                          'ssh_engine',
                                                          type=str)
# for tracking which hostnames have already had job_start called
_started_hostnames = set()


def create_host(
    hostname, auto_monitor=False, follow_paths=None, pattern_paths=None,
    netconsole=False, **args):
    """Create a host object.

    This method mixes host classes that are needed into a new subclass
    and creates a instance of the new class.

    @param hostname: A string representing the host name of the device.
    @param auto_monitor: A boolean value, if True, will try to mix
                         SerialHost in. If the host supports use as SerialHost,
                         will not mix in LogfileMonitorMixin anymore.
                         If the host doesn't support it, will
                         fall back to direct demesg logging and mix
                         LogfileMonitorMixin in.
    @param follow_paths: A list, passed to LogfileMonitorMixin,
                         remote paths to monitor.
    @param pattern_paths: A list, passed to LogfileMonitorMixin,
                          local paths to alert pattern definition files.
    @param netconsole: A boolean value, if True, will mix NetconsoleHost in.
    @param args: Args that will be passed to the constructor of
                 the new host class.

    @returns: A host object which is an instance of the newly created
              host class.
    """

    # TODO(fdeng): this method should should dynamically discover
    # and allocate host types, crbug.com/273843
    classes = [cros_host.CrosHost]
    # by default assume we're using SSH support
    if SSH_ENGINE == 'paramiko':
        from autotest_lib.server.hosts import paramiko_host
        classes.append(paramiko_host.ParamikoHost)
    elif SSH_ENGINE == 'raw_ssh':
        classes.append(ssh_host.SSHHost)
    else:
        raise error.AutoServError("Unknown SSH engine %s. Please verify the "
                                  "value of the configuration key 'ssh_engine' "
                                  "on autotest's global_config.ini file." %
                                  SSH_ENGINE)

    # by default mix in run_test support
    classes.append(autotest.AutotestHostMixin)

    # if the user really wants to use netconsole, let them
    if netconsole:
        classes.append(netconsole.NetconsoleHost)

    if auto_monitor:
        # use serial console support if it's available
        conmux_args = {}
        for key in ("conmux_server", "conmux_attach"):
            if key in args:
                conmux_args[key] = args[key]
        if serial.SerialHost.host_is_supported(hostname, **conmux_args):
            classes.append(serial.SerialHost)
        else:
            # no serial available, fall back to direct dmesg logging
            if follow_paths is None:
                follow_paths = [DEFAULT_FOLLOW_PATH]
            else:
                follow_paths = list(follow_paths) + [DEFAULT_FOLLOW_PATH]

            if pattern_paths is None:
                pattern_paths = [DEFAULT_PATTERNS_PATH]
            else:
                pattern_paths = (
                    list(pattern_paths) + [DEFAULT_PATTERNS_PATH])

            logfile_monitor_class = logfile_monitor.NewLogfileMonitorMixin(
                follow_paths, pattern_paths)
            classes.append(logfile_monitor_class)

    elif follow_paths:
        logfile_monitor_class = logfile_monitor.NewLogfileMonitorMixin(
            follow_paths, pattern_paths)
        classes.append(logfile_monitor_class)

    # do any site-specific processing of the classes list
    site_factory.postprocess_classes(classes, hostname,
                                     auto_monitor=auto_monitor, **args)

    hostname, args['user'], args['password'], args['port'] = \
            server_utils.parse_machine(hostname, ssh_user, ssh_pass, ssh_port)
    args['ssh_verbosity_flag'] = ssh_verbosity_flag
    args['ssh_options'] = ssh_options


    # create a custom host class for this machine and return an instance of it
    host_class = type("%s_host" % hostname, tuple(classes), {})
    host_instance = host_class(hostname, **args)

    # call job_start if this is the first time this host is being used
    if hostname not in _started_hostnames:
        host_instance.job_start()
        _started_hostnames.add(hostname)

    return host_instance
