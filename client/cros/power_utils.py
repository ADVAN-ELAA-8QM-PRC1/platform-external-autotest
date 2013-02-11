# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import logging, os, re, shutil, tempfile
from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error

def get_x86_cpu_arch():
    """Identify CPU architectural type.

    Intel's processor naming conventions is a mine field of inconsistencies.
    Armed with that, this method simply tries to identify the architecture of
    systems we care about.

    TODO(tbroch) grow method to cover processors numbers outlined in:
        http://www.intel.com/content/www/us/en/processors/processor-numbers.html
        perhaps returning more information ( brand, generation, features )

    Returns:
      String, explicitly (Atom, Core, Celeron) or None
    """
    cpuinfo = utils.read_file('/proc/cpuinfo')

    if re.search(r'Intel.*Atom.*[NZ][2-6]', cpuinfo):
        return 'Atom'
    if re.search(r'Intel.*Celeron.*8[14567][07]', cpuinfo):
        return 'Celeron'
    if re.search(r'Intel.*Core.*i[357]-[23][0-9][0-9][0-9]', cpuinfo):
        return 'Core'

    logging.info(cpuinfo)
    return None


def has_rapl_support():
    """Identify if platform supports Intels RAPL subsytem.

    Returns:
        Boolean, True if RAPL supported, False otherwise.
    """
    cpu_arch = get_x86_cpu_arch()
    if cpu_arch and ((cpu_arch is 'Celeron') or (cpu_arch is 'Core')):
        return True
    return False


def call_powerd_dbus_method(method_name, args=''):
    """
    Calls a dbus method exposed by powerd.

    Arguments:
      method_name: name of the dbus method.
      args: string containing args to dbus method call.
    """
    destination = 'org.chromium.PowerManager'
    path = '/org/chromium/PowerManager'
    interface = 'org.chromium.PowerManager'
    command = ('dbus-send --type=method_call --system ' + \
               '--dest=%s %s %s.%s %s') % (destination, path, interface, \
               method_name, args)
    utils.system_output(command)


class BacklightException(Exception):
    """Class for Backlight exceptions."""


class Backlight(object):
    """Class for control of built-in panel backlight."""
    bl_cmd = 'backlight-tool'

    # Default brightness is based on expected average use case.
    # See http://www.chromium.org/chromium-os/testing/power-testing for more
    # details.
    default_brightness_percent = 40


    def __init__(self):
        """Constructor.

        attributes:
        _init_level: integer of backlight level when object instantiated.
        """
        self._init_level = self.get_level()


    def set_level(self, level):
        """Set backlight level to the given brightness.
        Args:
          level: integer of brightness to set

        Raises:
          error.TestFail: if 'cmd' returns non-zero exit status
        """
        cmd = '%s --set_brightness %d' % (self.bl_cmd, level)
        try:
            utils.system(cmd)
        except error.CmdError:
            raise error.TestFail('Setting level with backlight-tool')


    def set_percent(self, percent):
        """Set backlight level to the given brightness percent.

        Args:
          percent: float between 0 and 100

        Raises:
          error.TestFail: if 'cmd' returns non-zero exit status
        """
        cmd = '%s --set_brightness_percent %f' % (self.bl_cmd, percent)
        try:
            utils.system(cmd)
        except error.CmdError:
            raise error.TestFail('Setting percent with backlight-tool')


    def set_resume_level(self, level):
        """Set backlight level on resume to the given brightness.
        Args:
          level: integer of brightness to set

        Raises:
          error.TestFail: if 'cmd' returns non-zero exit status
        """
        cmd = '%s --set_resume_brightness %d' % (self.bl_cmd, level)
        try:
            utils.system(cmd)
        except error.CmdError:
            raise error.TestFail('Setting resume level with backlight-tool')


    def set_resume_percent(self, percent):
        """Set backlight level on resume to the given brightness percent.

        Args:
          percent: float between 0 and 100

        Raises:
          error.TestFail: if 'cmd' returns non-zero exit status
        """
        cmd = '%s --set_resume_brightness_percent %f' % (self.bl_cmd, percent)
        try:
            utils.system(cmd)
        except error.CmdError:
            raise error.TestFail('Setting resume percent with backlight-tool')


    def set_default(self):
        """Set backlight to CrOS default.
        """
        self.set_percent(self.default_brightness_percent)


    def get_level(self):
        """Get backlight level currently.

        Returns integer of current backlight level.

        Raises:
          error.TestFail: if 'cmd' returns non-zero exit status
        """
        cmd = '%s --get_brightness' % self.bl_cmd
        try:
            return int(utils.system_output(cmd).rstrip())
        except error.CmdError:
            raise error.TestFail('Getting level with backlight-tool')


    def get_max_level(self):
        """Get maximum backight level.

        Returns integer of maximum backlight level.

        Raises:
          error.TestFail: if 'cmd' returns non-zero exit status
        """
        cmd = '%s --get_max_brightness' % self.bl_cmd
        try:
            return int(utils.system_output(cmd).rstrip())
        except error.CmdError:
            raise error.TestFail('Getting max level with backlight-tool')


    def restore(self):
        """Restore backlight to initial level when instance created."""
        self.set_level(self._init_level)


class KbdBacklightException(Exception):
    """Class for KbdBacklight exceptions."""


class KbdBacklight(object):
    """Class for control of keyboard backlight.

    Example code:
        kblight = power_utils.KbdBacklight()
        kblight.set(10)
        print "kblight % is %.f" % kblight.get()

    Public methods:
        set: Sets the keyboard backlight to a percent.
        get: Get current keyboard backlight percentage.

    Private functions:
        _get_max: Retrieve maximum integer setting of keyboard backlight

    Private attributes:
        _path: filepath to keyboard backlight controls in sysfs
        _max: cached value of 'max_brightness' integer

    TODO(tbroch): deprecate direct sysfs access if/when these controls are
    integrated into a userland tool such as backlight-tool in power manager.
    """
    DEFAULT_PATH = "/sys/class/leds/chromeos::kbd_backlight"

    def __init__(self, path=DEFAULT_PATH):
        if not os.path.exists(path):
            raise KbdBacklightException('Unable to find path "%s"' % path)
        self._path = path
        self._max = None


    def _get_max(self):
        """Get maximum absolute value of keyboard brightness.

        Returns:
            integer, maximum value of keyboard brightness
        """
        if self._max is None:
            self._max = int(utils.read_one_line(os.path.join(self._path,
                                                             'max_brightness')))
        return self._max


    def get(self):
        """Get current keyboard brightness setting.

        Returns:
            float, percentage of keyboard brightness.
        """
        current = int(utils.read_one_line(os.path.join(self._path,
                                                       'brightness')))
        return (current * 100 ) / self._get_max()


    def set(self, percent):
        """Set keyboard backlight percent.

        Args:
            percent: percent to set keyboard backlight to.
        """
        value = int((percent * self._get_max()) / 100)
        cmd = "echo %d > %s" % (value, os.path.join(self._path, 'brightness'))
        utils.system(cmd)


class BacklightController(object):
    """Class to simulate control of backlight via keyboard or Chrome UI.

    Public methods:
      increase_brightness: Increase backlight by one adjustment step.
      decrease_brightness: Decrease backlight by one adjustment step.
      set_brightness_to_max: Increase backlight to max by calling
          increase_brightness()
      set_brightness_to_min: Decrease backlight to min or zero by calling
          decrease_brightness()

    Private attributes:
      _max_num_steps: maximum number of backlight adjustment steps between 0 and
                      max brightness.

    Private methods:
      _call_powerd_dbus_method: executes dbus method call to power manager.
    """

    def __init__(self):
        self._max_num_steps = 16


    def decrease_brightness(self, allow_off=False):
        """
        Decrease brightness by one step, as if the user pressed the brightness
        down key or button.

        Arguments
          allow_off: Boolean flag indicating whether the brightness can be
                     reduced to zero.
                     Set to true to simulate brightness down key.
                     set to false to simulate Chrome UI brightness down button.
        """
        call_powerd_dbus_method('DecreaseScreenBrightness',
                                'boolean:%s' % \
                                    ('true' if allow_off else 'false'))


    def increase_brightness(self):
        """
        Increase brightness by one step, as if the user pressed the brightness
        up key or button.
        """
        call_powerd_dbus_method('IncreaseScreenBrightness')


    def set_brightness_to_max(self):
        """
        Increases the brightness using powerd until the brightness reaches the
        maximum value. Returns when it reaches the maximum number of brightness
        adjustments
        """
        num_steps_taken = 0
        while num_steps_taken < self._max_num_steps:
            self.increase_brightness()
            num_steps_taken += 1


    def set_brightness_to_min(self, allow_off=False):
        """
        Decreases the brightness using powerd until the brightness reaches the
        minimum value (zero or the minimum nonzero value). Returns when it
        reaches the maximum number of brightness adjustments.

        Arguments
          allow_off: Boolean flag indicating whether the brightness can be
                     reduced to zero.
                     Set to true to simulate brightness down key.
                     set to false to simulate Chrome UI brightness down button.
        """
        num_steps_taken = 0
        while num_steps_taken < self._max_num_steps:
            self.decrease_brightness(allow_off)
            num_steps_taken += 1


class PowerPrefChanger(object):
    """
    Class to temporarily change powerd prefs. Construct with a dict of
    pref_name/value pairs (e.g. {'disable_idle_suspend':0}). Destructor (or
    reboot) will restore old prefs automatically."""

    _PREFDIR = '/var/lib/power_manager'
    _TEMPDIR = '/tmp/autotest_powerd_prefs'

    def __init__(self, prefs):
        shutil.copytree(self._PREFDIR, self._TEMPDIR)
        for name, value in prefs.iteritems():
            utils.write_one_line('%s/%s' % (self._TEMPDIR, name), value)
        utils.system('mount --bind %s %s' % (self._TEMPDIR, self._PREFDIR))
        utils.restart_job('powerd')


    def __del__(self):
        utils.system('umount %s' % self._PREFDIR, ignore_status=True)
        shutil.rmtree(self._TEMPDIR)
        utils.restart_job('powerd')


class Registers(object):
    """Class to examine PCI and MSR registers."""

    def __init__(self):
        self._cpu_id = 0
        self._rdmsr_cmd = 'iotools rdmsr'
        self._mmio_read32_cmd = 'iotools mmio_read32'
        self._rcba = 0xfed1c000

        self._pci_read32_cmd = 'iotools pci_read32'
        self._mch_bar = None
        self._dmi_bar = None

    def _init_mch_bar(self):
        if self._mch_bar != None:
            return
        # MCHBAR is at offset 0x48 of B/D/F 0/0/0
        cmd = '%s 0 0 0 0x48' % (self._pci_read32_cmd)
        self._mch_bar = int(utils.system_output(cmd), 16) & 0xfffffffe
        logging.debug('MCH BAR is %s', hex(self._mch_bar))

    def _init_dmi_bar(self):
        if self._dmi_bar != None:
            return
        # DMIBAR is at offset 0x68 of B/D/F 0/0/0
        cmd = '%s 0 0 0 0x68' % (self._pci_read32_cmd)
        self._dmi_bar = int(utils.system_output(cmd), 16) & 0xfffffffe
        logging.debug('DMI BAR is %s', hex(self._dmi_bar))

    def _read_msr(self, register):
        cmd = '%s %d %s' % (self._rdmsr_cmd, self._cpu_id, register)
        return int(utils.system_output(cmd), 16)

    def _read_mmio_read32(self, address):
        cmd = '%s 0x%x' % (self._mmio_read32_cmd, address)
        return int(utils.system_output(cmd), 16)

    def _read_dmi_bar(self, offset):
        self._init_dmi_bar()
        return self._read_mmio_read32(self._dmi_bar + int(offset, 16))

    def _read_mch_bar(self, offset):
        self._init_mch_bar()
        return self._read_mmio_read32(self._mch_bar + int(offset, 16))

    def _read_rcba(self, offset):
        return self._read_mmio_read32(self._rcba + int(offset, 16))

    def _shift_mask_match(self, reg_name, value, match):
        expr = match[1]
        bits = match[0].split(':')
        operator = match[2] if len(match) == 3 else '=='
        hi_bit = int(bits[0])
        if len(bits) == 2:
            lo_bit = int(bits[1])
        else:
            lo_bit = int(bits[0])

        value >>= lo_bit
        mask = (1 << (hi_bit - lo_bit + 1)) - 1
        value &= mask

        good = eval("%d %s %d" % (value, operator, expr))
        if not good:
            logging.error('FAILED: %s bits: %s value: %s mask: %s expr: %s ' +
                          'operator: %s', reg_name, bits, hex(value), mask,
                          expr, operator)
        return good

    def _verify_registers(self, reg_name, read_fn, match_list):
        errors = 0
        for k, v in match_list.iteritems():
            r = read_fn(k)
            for item in v:
                good = self._shift_mask_match(reg_name, r, item)
                if not good:
                    errors += 1
                    logging.error('Error(%d), %s: reg = %s val = %s match = %s',
                                  errors, reg_name, k, hex(r), v)
                else:
                    logging.debug('ok, %s: reg = %s val = %s match = %s',
                                  reg_name, k, hex(r), v)
        return errors

    def verify_msr(self, match_list):
        errors = 0
        for cpu_id in xrange(0, max(utils.count_cpus(), 1)):
            self._cpu_id = cpu_id
            errors += self._verify_registers('msr', self._read_msr, match_list)
        return errors

    def verify_dmi(self, match_list):
        return self._verify_registers('dmi', self._read_dmi_bar, match_list)

    def verify_mch(self, match_list):
        return self._verify_registers('mch', self._read_mch_bar, match_list)

    def verify_rcba(self, match_list):
        return self._verify_registers('rcba', self._read_rcba, match_list)
