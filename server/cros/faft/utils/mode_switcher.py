# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import time


class _BaseFwBypasser(object):
    """Base class that controls bypass logic for firmware screens."""

    def __init__(self, servo, faft_config):
        self.servo = servo
        self.faft_config = faft_config


    def bypass_dev_mode(self):
        """Bypass the dev mode firmware logic to boot internal image."""
        raise NotImplementedError


    def bypass_dev_boot_usb(self):
        """Bypass the dev mode firmware logic to boot USB."""
        raise NotImplementedError


    def bypass_rec_mode(self):
        """Bypass the rec mode firmware logic to boot USB."""
        raise NotImplementedError


    def trigger_dev_to_rec(self):
        """Trigger to the rec mode from the dev screen."""
        raise NotImplementedError


    def trigger_rec_to_dev(self):
        """Trigger to the dev mode from the rec screen."""
        raise NotImplementedError


    def trigger_dev_to_normal(self):
        """Trigger to the normal mode from the dev screen."""
        raise NotImplementedError


class _CtrlDBypasser(_BaseFwBypasser):
    """Controls bypass logic via Ctrl-D combo."""

    def bypass_dev_mode(self):
        """Bypass the dev mode firmware logic to boot internal image."""
        time.sleep(self.faft_config.firmware_screen)
        self.servo.ctrl_d()


    def bypass_dev_boot_usb(self):
        """Bypass the dev mode firmware logic to boot USB."""
        time.sleep(self.faft_config.firmware_screen)
        self.servo.ctrl_u()


    def bypass_rec_mode(self):
        """Bypass the rec mode firmware logic to boot USB."""
        self.servo.switch_usbkey('host')
        time.sleep(self.faft_config.usb_plug)
        self.servo.switch_usbkey('dut')


    def trigger_dev_to_rec(self):
        """Trigger to the rec mode from the dev screen."""
        time.sleep(self.faft_config.firmware_screen)

        # Pressing Enter for too long triggers a second key press.
        # Let's press it without delay
        self.servo.enter_key(press_secs=0)

        # For Alex/ZGB, there is a dev warning screen in text mode.
        # Skip it by pressing Ctrl-D.
        if self.faft_config.need_dev_transition:
            time.sleep(self.faft_config.legacy_text_screen)
            self.servo.ctrl_d()


    def trigger_rec_to_dev(self):
        """Trigger to the dev mode from the rec screen."""
        time.sleep(self.faft_config.firmware_screen)
        self.servo.ctrl_d()
        time.sleep(self.faft_config.confirm_screen)
        if self.faft_config.rec_button_dev_switch:
            logging.info('RECOVERY button pressed to switch to dev mode')
            self.servo.toggle_recovery_switch()
        else:
            logging.info('ENTER pressed to switch to dev mode')
            self.servo.enter_key()


    def trigger_dev_to_normal(self):
        """Trigger to the normal mode from the dev screen."""
        time.sleep(self.faft_config.firmware_screen)
        self.servo.enter_key()
        time.sleep(self.faft_config.confirm_screen)
        self.servo.enter_key()


def _create_fw_bypasser(servo, faft_config):
    """Creates a proper firmware bypasser.

    @param servo: A servo object controlling the servo device.
    @param faft_config: A FAFT config object, which describes the type of
                        firmware bypasser.
    """
    bypasser_type = faft_config.fw_bypasser_type
    if bypasser_type == 'ctrl_d_bypasser':
        logging.info('Create a CtrlDBypasser')
        return _CtrlDBypasser(servo, faft_config)
    else:
        raise NotImplementedError('Not supported fw_bypasser_type: %s',
                                  bypasser_type)


class _BaseModeSwitcher(object):
    """Base class that controls firmware mode switching."""

    def __init__(self, faft_framework):
        self.faft_framework = faft_framework
        self.faft_client = faft_framework.faft_client
        self.servo = faft_framework.servo
        self.faft_config = faft_framework.faft_config
        self.checkers = faft_framework.checkers
        self.bypasser = _create_fw_bypasser(self.servo, self.faft_config)
        self._backup_mode = None


    def setup_mode(self, mode):
        """Setup for the requested mode.

        It makes sure the system in the requested mode. If not, it tries to
        do so.

        @param mode: A string of mode, one of 'normal', 'dev', or 'rec'.
        """
        if not self.checkers.mode_checker(mode):
            logging.info('System not in expected %s mode. Reboot into it.',
                         mode)
            if self._backup_mode is None:
                # Only resume to normal/dev mode after test, not recovery.
                self._backup_mode = 'dev' if mode == 'normal' else 'normal'
            self.reboot_to_mode(mode)


    def restore_mode(self):
        """Restores original dev mode status if it has changed."""
        if self._backup_mode is not None:
            self.reboot_to_mode(self._backup_mode)


    def reboot_to_mode(self, to_mode, from_mode=None, sync_before_boot=True,
                       wait_for_dut_up=True):
        """Reboot and execute the mode switching sequence.

        @param to_mode: The target mode, one of 'normal', 'dev', or 'rec'.
        @param from_mode: The original mode, optional, one of 'normal, 'dev',
                          or 'rec'.
        @param sync_before_boot: True to sync to disk before booting.
        @param wait_for_dut_up: True to wait DUT online again. False to do the
                                reboot and mode switching sequence only and may
                                need more operations to pass the firmware
                                screen.
        """
        logging.info('-[ModeSwitcher]-[ start reboot_to_mode(%r, %r, %r) ]-',
                     to_mode, from_mode, wait_for_dut_up)
        if sync_before_boot:
            self.faft_framework.blocking_sync()
        if to_mode == 'rec':
            self._enable_rec_mode_and_reboot(usb_state='dut')
            if wait_for_dut_up:
                self.bypasser.bypass_rec_mode()
                self.faft_framework.wait_for_client()

        elif to_mode == 'dev':
            self._enable_dev_mode_and_reboot()
            if wait_for_dut_up:
                self.bypasser.bypass_dev_mode()
                self.faft_framework.wait_for_client()

        elif to_mode == 'normal':
            self._enable_normal_mode_and_reboot()
            if wait_for_dut_up:
                self.faft_framework.wait_for_client()

        else:
            raise NotImplementedError(
                    'Not supported mode switching from %s to %s' %
                     (str(from_mode), to_mode))
        logging.info('-[ModeSwitcher]-[ end reboot_to_mode(%r, %r, %r) ]-',
                     to_mode, from_mode, wait_for_dut_up)


    def mode_aware_reboot(self, reboot_type=None, reboot_method=None,
                          sync_before_boot=True, wait_for_dut_up=True):
        """Uses a mode-aware way to reboot DUT.

        For example, if DUT is in dev mode, it requires pressing Ctrl-D to
        bypass the developer screen.

        @param reboot_type: A string of reboot type, one of 'warm', 'cold', or
                            'custom'. Default is a warm reboot.
        @param reboot_method: A custom method to do the reboot. Only use it if
                              reboot_type='custom'.
        @param sync_before_boot: True to sync to disk before booting.
        @param wait_for_dut_up: True to wait DUT online again. False to do the
                                reboot only.
        """
        if reboot_type is None or reboot_type == 'warm':
            reboot_method = self.servo.get_power_state_controller().warm_reset
        elif reboot_type == 'cold':
            reboot_method = self.servo.get_power_state_controller().reset
        elif reboot_type != 'custom':
            raise NotImplementedError('Not supported reboot_type: %s',
                                      reboot_type)

        logging.info("-[ModeSwitcher]-[ start mode_aware_reboot(%r, %s, ..) ]-",
                     reboot_type, reboot_method.__name__)
        is_normal = is_dev = False
        if sync_before_boot:
            if wait_for_dut_up:
                is_normal = self.checkers.mode_checker('normal')
                is_dev = self.checkers.mode_checker('dev')
            boot_id = self.faft_framework.get_bootid()
            self.faft_framework.blocking_sync()
        reboot_method()
        if sync_before_boot:
            self.faft_framework.wait_for_client_offline(orig_boot_id=boot_id)
        if wait_for_dut_up:
            # For encapsulating the behavior of skipping firmware screen,
            # e.g. requiring unplug and plug USB, the variants are not
            # hard coded in tests. We keep this logic in this
            # mode_aware_reboot method.
            if not is_dev:
                # In the normal/recovery boot flow, replugging USB does not
                # affect the boot flow. But when something goes wrong, like
                # firmware corrupted, it automatically leads to a recovery USB
                # boot.
                self.servo.switch_usbkey('host')
            if not is_normal:
                self.bypasser.bypass_dev_mode()
            if not is_dev:
                self.bypasser.bypass_rec_mode()
            self.faft_framework.wait_for_kernel_up()
        logging.info("-[ModeSwitcher]-[ end mode_aware_reboot(%r, %s, ..) ]-",
                     reboot_type, reboot_method.__name__)


    def _enable_rec_mode_and_reboot(self, usb_state=None):
        """Switch to rec mode and reboot.

        This method emulates the behavior of the old physical recovery switch,
        i.e. switch ON + reboot + switch OFF, and the new keyboard controlled
        recovery mode, i.e. just press Power + Esc + Refresh.

        @param usb_state: A string, one of 'dut', 'host', or 'off'.
        """
        psc = self.servo.get_power_state_controller()
        psc.power_off()
        if usb_state:
            self.servo.switch_usbkey(usb_state)
        psc.power_on(psc.REC_ON)


    def _disable_rec_mode_and_reboot(self, usb_state=None):
        """Disable the rec mode and reboot.

        It is achieved by calling power state controller to do a normal
        power on.
        """
        psc = self.servo.get_power_state_controller()
        psc.power_off()
        psc.power_on(psc.REC_OFF)


    def _enable_dev_mode_and_reboot(self):
        """Switch to developer mode and reboot."""
        raise NotImplementedError


    def _enable_normal_mode_and_reboot(self):
        """Switch to normal mode and reboot."""
        raise NotImplementedError


    # Redirects the following methods to FwBypasser
    def bypass_dev_mode(self):
        """Bypass the dev mode firmware logic to boot internal image."""
        self.bypasser.bypass_dev_mode()


    def bypass_dev_boot_usb(self):
        """Bypass the dev mode firmware logic to boot USB."""
        self.bypasser.bypass_dev_boot_usb()


    def bypass_rec_mode(self):
        """Bypass the rec mode firmware logic to boot USB."""
        self.bypasser.bypass_rec_mode()


    def trigger_dev_to_rec(self):
        """Trigger to the rec mode from the dev screen."""
        self.bypasser.trigger_dev_to_rec()


    def trigger_rec_to_dev(self):
        """Trigger to the dev mode from the rec screen."""
        self.bypasser.trigger_rec_to_dev()


    def trigger_dev_to_normal(self):
        """Trigger to the normal mode from the dev screen."""
        self.bypasser.trigger_dev_to_normal()


class _PhysicalButtonSwitcher(_BaseModeSwitcher):
    """Class that switches firmware mode via physical button."""

    def _enable_dev_mode_and_reboot(self):
        """Switch to developer mode and reboot."""
        self.servo.enable_development_mode()
        self.faft_client.system.run_shell_command(
                'chromeos-firmwareupdate --mode todev && reboot')


    def _enable_normal_mode_and_reboot(self):
        """Switch to normal mode and reboot."""
        self.servo.disable_development_mode()
        self.faft_client.system.run_shell_command(
                'chromeos-firmwareupdate --mode tonormal && reboot')


class _KeyboardDevSwitcher(_BaseModeSwitcher):
    """Class that switches firmware mode via keyboard combo."""

    def _enable_dev_mode_and_reboot(self):
        """Switch to developer mode and reboot."""
        logging.info("Enabling keyboard controlled developer mode")
        # Rebooting EC with rec mode on. Should power on AP.
        # Plug out USB disk for preventing recovery boot without warning
        self._enable_rec_mode_and_reboot(usb_state='host')
        self.faft_framework.wait_for_client_offline()
        self.bypasser.trigger_rec_to_dev()


    def _enable_normal_mode_and_reboot(self):
        """Switch to normal mode and reboot."""
        logging.info("Disabling keyboard controlled developer mode")
        self._disable_rec_mode_and_reboot()
        self.faft_framework.wait_for_client_offline()
        self.bypasser.trigger_dev_to_normal()


def create_mode_switcher(faft_framework):
    """Creates a proper mode switcher.

    @param faft_framework: The main FAFT framework object.
    """
    switcher_type = faft_framework.faft_config.mode_switcher_type
    if switcher_type == 'physical_button_switcher':
        logging.info('Create a PhysicalButtonSwitcher')
        return _PhysicalButtonSwitcher(faft_framework)
    elif switcher_type == 'keyboard_dev_switcher':
        logging.info('Create a KeyboardDevSwitcher')
        return _KeyboardDevSwitcher(faft_framework)
    else:
        raise NotImplementedError('Not supported mode_switcher_type: %s',
                                  switcher_type)
