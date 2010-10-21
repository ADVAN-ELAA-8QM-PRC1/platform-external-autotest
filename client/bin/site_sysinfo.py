import os, shutil, re, logging

from autotest_lib.client.common_lib import utils
from autotest_lib.client.bin import base_sysinfo
from autotest_lib.client.bin import chromeos_constants


logfile = base_sysinfo.logfile
command = base_sysinfo.command


class logdir(base_sysinfo.loggable):
    def __init__(self, directory):
        super(logdir, self).__init__(directory, log_in_keyval=False)
        self.dir = directory


    def __repr__(self):
        return "site_sysinfo.logdir(%r)" % self.dir


    def __eq__(self, other):
        if isinstance(other, logdir):
            return self.dir == other.dir
        elif isinstance(other, loggable):
            return False
        return NotImplemented


    def __ne__(self, other):
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result


    def __hash__(self):
        return hash(self.dir)


    def run(self, logdir):
        if os.path.exists(self.dir):
            if self.dir.startswith('/'):
                dest_dir = os.path.join(logdir, self.dir[1:])
            else:
                dest_dir = os.path.join(logdir, self.dir)
            utils.system("mkdir -p %s" % dest_dir)
            utils.system("cp -pr %s/* %s" % (self.dir, dest_dir))


class site_sysinfo(base_sysinfo.base_sysinfo):
    def __init__(self, job_resultsdir):
        super(site_sysinfo, self).__init__(job_resultsdir)

        # add in some extra command logging
        self.test_loggables.add(command(
            "ls -l /boot", "boot_file_list"))
        self.test_loggables.add(logdir("/home/chronos/user/crash"))
        self.test_loggables.add(logdir("/home/chronos/user/log"))
        self.test_loggables.add(logdir("/tmp"))
        self.test_loggables.add(logdir("/var/log"))
        self.test_loggables.add(logdir("/var/spool/crash"))
        self.test_loggables.add(logfile("/home/chronos/.Google/"
                                        "Google Talk Plugin/gtbplugin.log"))


    def log_test_keyvals(self, test_sysinfodir):
        keyval = super(site_sysinfo, self).log_test_keyvals(test_sysinfodir)

        lsb_lines = utils.system_output(
            "cat /etc/lsb-release",
            ignore_status=True).splitlines()
        lsb_dict = dict(item.split("=") for item in lsb_lines)

        for lsb_key in lsb_dict.keys():
            # Special handling for build number
            if lsb_key == "CHROMEOS_RELEASE_DESCRIPTION":
                keyval["CHROMEOS_BUILD"] = (
                    lsb_dict[lsb_key].rstrip(")").split(" ")[3])
            keyval[lsb_key] = lsb_dict[lsb_key]

        # return the updated keyvals
        return keyval
