# -*- coding: utf-8 -*-
#
# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# DESCRIPTION :
#
# This is a factory test to check the functionality of the lid switch.

import dbus
import gobject
import gtk
import time

from autotest_lib.client.bin import test
from autotest_lib.client.common_lib import error, utils
from autotest_lib.client.cros import factory_setup_modules
from cros.factory.test import factory
from cros.factory.test import ui as ful
from dbus.mainloop.glib import DBusGMainLoop

_DEFAULT_TIMEOUT = 30

class TestStatus:
  WAITING = 1
  IN_PROGRESS = 2
  COMPLETE = 3

class factory_LidSwitch(test.test):
  version = 1

  _DBUS_INTERFACE = 'org.chromium.PowerManager'
  _DBUS_LID_OPENED = 'LidOpened'
  _DBUS_LID_CLOSED = 'LidClosed'
  _DBUS_MEMBER_KEYWORD = 'message'
  _MESSAGE_PASSED = 'PASSED'
  _MESSAGE_PROMPT_CLOSE =  'Close then open the lid'
  _MESSAGE_PROMPT_OPEN = 'Open the lid'
  _MESSAGE_UNKNOWN_ERROR = 'Unknown Error'
  _MESSAGE_USER_QUIT = 'Test stopped by user'
  _MESSAGE_TIME_LIMIT_REACHED = 'Time limit reached'
  _QUIT_KEY = 'Q'
  _MESSAGE_QUIT = 'Press \'%s\' to quit' % _QUIT_KEY

  def key_release_callback(self, widget, event):
    if event.keyval in [ord(self._QUIT_KEY), ord(self._QUIT_KEY.lower())]:
      self._fail = True
      self._error_message = self._MESSAGE_USER_QUIT
      gtk.main_quit()
      return True

  def dbus_event(self, *args, **kwargs):
    event = kwargs[self._DBUS_MEMBER_KEYWORD]
    if event == self._DBUS_LID_CLOSED:
      self._status = TestStatus.IN_PROGRESS
      self._prompt.set_text(self._MESSAGE_PROMPT_OPEN)
    elif event == self._DBUS_LID_OPENED:
      self._status = TestStatus.COMPLETE
      self._prompt.set_text(self._MESSAGE_PASSED)
      self._fail = False
      gtk.main_quit()
    return True

  def timer_event(self, countdown_label):
    if self._status != TestStatus.WAITING:
      return False
    if self._deadline is None:
      self._deadline = time.time() + self._timeout
    time_remaining = max(0, self._deadline - time.time())
    if time_remaining <= 0:
      self._fail = True
      self._error_message = self._MESSAGE_TIME_LIMIT_REACHED
      gtk.main_quit()
      return False

    countdown_label.set_text('%d' % time_remaining)
    countdown_label.queue_draw()
    return True

  def register_callbacks(self, window):
    window.connect('key-release-event', self.key_release_callback)
    window.add_events(gtk.gdk.KEY_RELEASE_MASK)

  def switch_service(self, service, status):
    '''Probes current status of service and turns it into status.
    Args:
      service: Service name, e.g. powerd or powerm.
      status: True/False. The intended status of that service.
    Return:
      True/False: The current status of service before switching.
      None: Can not decide current status of service.
    '''
    status_probe = utils.system_output(
        'status %s | cut -d" " -f2' % service).strip()
    if status_probe == 'start/running,':
      if not status:
        factory.log('stop %s' % service)
        utils.system('stop %s' % service)
      return True
    elif status_probe == 'stop/waiting':
      if status:
        factory.log('start %s' % service)
        utils.system('start %s' % service)
      return False
    else:
      factory.log('service %s can not be found.' % service)
      return None

  def run_once(self, timeout=_DEFAULT_TIMEOUT):

    factory.log('STARTED: %s run_once' % self.__class__)

    # Ensure powerm is running and powerd is not running for the test.

    original_powerm_status = self.switch_service('powerm', True)
    original_powerd_status = self.switch_service('powerd', False)

    self._error_message = self._MESSAGE_UNKNOWN_ERROR
    self._fail = True
    self._status = TestStatus.WAITING

    vbox = gtk.VBox(spacing=20)

    self._prompt = ful.make_label(self._MESSAGE_PROMPT_CLOSE,
                                  alignment=(0.5,0.5))
    self._prompt.set_text(self._MESSAGE_PROMPT_CLOSE)
    vbox.pack_start(self._prompt, False, False)

    self._timeout = timeout
    if self._timeout > 0:
      self._deadline = None # This is calculated on the first timer event
      countdown_widget, countdown_label = ful.make_countdown_widget()
      gobject.timeout_add(1000, self.timer_event, countdown_label)
      vbox.pack_start(countdown_widget, False, False)

    quit_label = ful.make_label(self._MESSAGE_QUIT, alignment=(0.5,0.5))
    vbox.pack_start(quit_label, False, False)

    test_widget = gtk.EventBox()
    test_widget.modify_bg(gtk.STATE_NORMAL, gtk.gdk.color_parse('black'))
    test_widget.add(vbox)

    DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    bus.add_signal_receiver(self.dbus_event,
        dbus_interface=self._DBUS_INTERFACE,
        member_keyword=self._DBUS_MEMBER_KEYWORD)

    ful.run_test_widget(
        self.job,
        test_widget,
        window_registration_callback=self.register_callbacks)

    # Switch back powerd and powerm to their original status.

    self.switch_service('powerd', original_powerd_status)
    self.switch_service('powerm', original_powerm_status)

    if self._fail:
      factory.log(self._error_message)
      raise error.TestFail(self._error_message)

    factory.log('%s run_once finished' % self.__class__)
