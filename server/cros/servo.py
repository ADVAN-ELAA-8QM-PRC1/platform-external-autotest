# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# Expects to be run in an environment with sudo and no interactive password
# prompt, such as within the Chromium OS development chroot.

import logging
import time
import xmlrpclib
import subprocess

class Servo:
    """Manages control of a Servo board.

    Servo is a board developed by hardware group to aide in the debug and
    control of various partner devices. Servo's features include the simulation
    of pressing the power button, closing the lid, and pressing Ctrl-d. This
    class manages setting up and communicating with a servo demon (servod)
    process. It provides both high-level functions for common servo tasks and
    low-level functions for directly setting and reading gpios.
    """

    _server = None
    _servod = None

    # Power button press delays in seconds.
    LONG_DELAY = 8
    SHORT_DELAY = 0.1
    NORMAL_TRANSITION_DELAY = 1.2
    # Maximum number of times to re-read power button on release.
    RELEASE_RETRY_MAX = 5

    # Delays to deal with computer transitions.
    SLEEP_DELAY = 6
    BOOT_DELAY = 10
    RECOVERY_INSTALL_DELAY = 300

    # Servo-specific delays.
    MAX_SERVO_STARTUP_DELAY = 10
    SERVO_SEND_SIGNAL_DELAY = 0.5

    def __init__(self, servo_host=None, servo_port=None,
                 xml_config=['servo.xml'], servo_vid=None, servo_pid=None,
                 servo_serial=None, cold_reset=False):
        """Sets up the servo communication infrastructure.

        Args:
          servo_host: Host the servod process should listen on.
          servo_port: Port the servod process should listen on.
          xml_config: A list of configuration XML files for servod.
          servo_vid: USB vendor id of servo.
          servo_pid: USB product id of servo.
          servo_serial: USB serial id in device descriptor to host to
            distinguish and control multiple servos.  Note servo's EEPROM must
            be programmed to use this feature.
          cold_reset: If True, cold reset device and boot during init,
                      otherwise perform init with device running.
        """
        # launch servod
        self._servod = None

        if not servo_port:
            servo_port = 9999
        # TODO(tbroch) In case where servo h/w is not connected to the host
        # running the autotest server, servod will need to be launched by
        # another means (udev likely).  For now we can assume servo_host ==
        # localhost as one hueristic way of determining this.
        if not servo_host or servo_host == 'localhost':
            servo_host = 'localhost'
            self._launch_servod(servo_host, servo_port, xml_config, servo_vid,
                                servo_pid, servo_serial)
        else:
            logging.info('servod should already be running on host = %s',
                         servo_host)

        self._do_cold_reset = cold_reset
        self._connect_servod(servo_host, servo_port)


    def initialize_dut(self):
        """Initializes a dut for testing purposes."""
        if self._do_cold_reset:
            self._init_seq_cold_reset_devmode()
        else:
            self._init_seq()


    def power_long_press(self):
        """Simulate a long power button press."""
        self.power_key(Servo.LONG_DELAY)


    def power_normal_press(self):
        """Simulate a normal power button press."""
        self.power_key()


    def power_short_press(self):
        """Simulate a short power button press."""
        self.power_key(Servo.SHORT_DELAY)


    def power_key(self, secs=NORMAL_TRANSITION_DELAY):
        """Simulate a power button press.

        Args:
          secs: Time in seconds to simulate the keypress.
        """
        self.set_nocheck('pwr_button', 'press')
        time.sleep(secs)
        self.set_nocheck('pwr_button', 'release')
        # TODO(tbroch) Different systems have different release times on the
        # power button that this loop addresses.  Longer term we may want to
        # make this delay platform specific.
        retry = 1
        while True:
            value = self.get('pwr_button')
            if value == 'release' or retry > Servo.RELEASE_RETRY_MAX:
                break
            logging.info('Waiting for pwr_button to release, retry %d.' % retry)
            retry += 1
            time.sleep(Servo.SHORT_DELAY)


    def lid_open(self):
        """Simulate opening the lid."""
        self.set_nocheck('lid_open', 'yes')


    def lid_close(self):
        """Simulate closing the lid.

        Waits 6 seconds to ensure the device is fully asleep before returning.
        """
        self.set_nocheck('lid_open', 'no')
        time.sleep(Servo.SLEEP_DELAY)


    def _press_and_release_keys(self, m1, m2, press_secs=None):
        """Simulate button presses."""
        if press_secs is None:
            press_secs = Servo.SERVO_SEND_SIGNAL_DELAY

        self.set_nocheck('kbd_en', 'on')
        self.set_nocheck('kbd_m1', m1)
        self.set_nocheck('kbd_m2', m2)
        time.sleep(press_secs)
        self.set_nocheck('kbd_en', 'off')


    def ctrl_d(self):
        """Simulate Ctrl-d simultaneous button presses."""
        self._press_and_release_keys('d', 'ctrl')


    def d_key(self):
        """Simulate Enter key button press."""
        self._press_and_release_keys('d', 'none')


    def ctrl_key(self):
        """Simulate Enter key button press."""
        self._press_and_release_keys('none', 'ctrl')


    def enter_key(self):
        """Simulate Enter key button press."""
        self._press_and_release_keys('enter', 'none')


    def refresh_key(self):
        """Simulate Refresh key (F3) button press."""
        self._press_and_release_keys('none', 'refresh')


    def imaginary_key(self):
        """Simulate imaginary key button press.

        Maps to a key that doesn't physically exist.
        """
        self._press_and_release_keys('none', 'unused')


    def enable_recovery_mode(self):
        """Enable recovery mode on device."""
        self.set('rec_mode', 'on')


    def disable_recovery_mode(self):
        """Disable recovery mode on device."""
        self.set('rec_mode', 'off')


    def enable_development_mode(self):
        """Enable development mode on device."""
        self.set('dev_mode', 'on')


    def disable_development_mode(self):
        """Disable development mode on device."""
        self.set('dev_mode', 'off')

    def enable_usb_hub(self, host=False):
        """Enable Servo's USB/ethernet hub.

        This is equivalent to plugging in the USB devices attached to Servo to
        the host (if |host| is True) or dut (if |host| is False).
        For host=False, requires that the USB out on the servo board is
        connected to a USB in port on the target device. Servo's USB ports are
        labeled DUT_HUB_USB1 and DUT_HUB_USB2. Servo's ethernet port is also
        connected to this hub. Servo's USB port DUT_HUB_IN is the output of the
        hub.
        """
        self.set('dut_hub_pwren', 'on')
        if host:
          self.set('usb_mux_oe1', 'on')
          self.set('usb_mux_sel1', 'servo_sees_usbkey')
        else:
          self.set('dut_hub_sel', 'dut_sees_hub')

        self.set('dut_hub_on', 'yes')


    def disable_usb_hub(self):
        """Disable Servo's USB/ethernet hub.

        This is equivalent to unplugging the USB devices attached to Servo.
        """
        self.set('dut_hub_on', 'no')


    def boot_devmode(self):
        """Boot a dev-mode device that is powered off."""
        self.power_normal_press()
        self.pass_devmode()


    def pass_devmode(self):
        """Pass through boot screens in dev-mode."""
        time.sleep(Servo.BOOT_DELAY)
        self.ctrl_d()
        time.sleep(Servo.BOOT_DELAY)


    def cold_reset(self):
        """Perform a cold reset of the EC.

        Has the side effect of shutting off the device.  Device is guaranteed
        to be off at the end of this call.
        """
        self.set('cold_reset', 'on')
        time.sleep(Servo.SERVO_SEND_SIGNAL_DELAY)


    def warm_reset(self):
        """Perform a warm reset of the device.

        Has the side effect of restarting the device.
        """
        self.set('warm_reset', 'on')
        time.sleep(Servo.SERVO_SEND_SIGNAL_DELAY)
        self.set('warm_reset', 'off')


    def get(self, gpio_name):
        """Get the value of a gpio from Servod."""
        assert gpio_name
        return self._server.get(gpio_name)


    def set(self, gpio_name, gpio_value):
        """Set and check the value of a gpio using Servod."""
        self.set_nocheck(gpio_name, gpio_value)
        assert gpio_value == self.get(gpio_name), \
            'Servo failed to set %s to %s' % (gpio_name, gpio_value)


    def set_nocheck(self, gpio_name, gpio_value):
        """Set the value of a gpio using Servod."""
        assert gpio_name and gpio_value
        logging.info('Setting %s to %s' % (gpio_name, gpio_value))
        self._server.set(gpio_name, gpio_value)


    def _init_seq_cold_reset_devmode(self):
        """Cold reset, init device, and boot in dev-mode."""
        self.cold_reset()
        self._init_seq()
        self.set('dev_mode', 'on')
        self.boot_devmode()


    def __del__(self):
        """Kill the Servod process."""
        if not self._servod:
            return

        # kill servod one way or another
        try:
            # won't work without superuser privileges
            self._servod.terminate()
        except:
            # should work without superuser privileges
            assert subprocess.call(['sudo', 'kill', str(self._servod.pid)])


    def _launch_servod(self, servo_host, servo_port, xml_config, servo_vid,
                       servo_pid, servo_serial):
        """Launch the servod process.

        Args:
          servo_host: Host to start servod listening on.
          servo_port: Port to start servod listening on.
          xml_config: A list of XML configuration files for servod.
          servo_vid: USB vendor id of servo.
          servo_pid: USB product id of servo.
          servo_serial: USB serial id in device descriptor to host to
            distinguish and control multiple servos.  Note servo's EEPROM must
            be programmed to use this feature.
        """
        cmdlist = ['sudo', 'servod']
        for config in xml_config:
            cmdlist += ['-c', str(config)]
        if servo_host is not None:
            cmdlist.append('--host=%s' % str(servo_host))
        if servo_port is not None:
            cmdlist.append('--port=%s' % str(servo_port))
        if servo_vid is not None:
            cmdlist.append('--vendor=%s' % str(servo_vid))
        if servo_pid is not None:
            cmdlist.append('--product=%s' % str(servo_pid))
        if servo_serial is not None:
            cmdlist.append('--serialname=%s' % str(servo_serial))
        logging.info('starting servod w/ cmd :: %s' % ' '.join(cmdlist))
        self._servod = subprocess.Popen(cmdlist, 0, None, None, None,
                                        subprocess.PIPE)
        # wait for servod to initialize
        timeout = Servo.MAX_SERVO_STARTUP_DELAY
        while ('Listening' not in self._servod.stderr.readline() and
               self._servod.returncode is None and timeout > 0):
            time.sleep(1)
            timeout -= 1
        assert self._servod.returncode is None and timeout


    def _init_seq(self):
        """Initiate starting state for servo."""
        self.set('tx_dir', 'input')
        self.set('lid_open', 'yes')
        self.set('rec_mode', 'off')


    def _connect_servod(self, servo_host, servo_port):
        """Connect to the Servod process with XMLRPC.

        Args:
          servo_port: Port the Servod process is listening on.
        """
        remote = 'http://%s:%s' % (servo_host, servo_port)
        self._server = xmlrpclib.ServerProxy(remote)
        try:
            self._server.echo("ping-test")
        except:
            logging.error('Connection to servod failed')
            raise
