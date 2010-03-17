# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging, os
from autotest_lib.client.bin import test, utils
from autotest_lib.client.common_lib import error


class platform_Components(test.test):
    version = 1
    _syslog = '/var/log/messages'
    _cids = [
        'part_id_audio_codec',
        'part_id_bluetooth',
        'part_id_cpu',
        'part_id_touchpad',
        'part_id_webcam',
    ]


    def check_component(self, comp_key, comp_id):
        self._system[comp_key] = [ comp_id ]

        if not self._approved.has_key(comp_key):
            raise error.TestFail('%s missing from database' % comp_key)

        app_cids = self._approved[comp_key]

        if '*' in app_cids:
            return

        if not comp_id in app_cids:
            self._failures[comp_key] = [ comp_id ]


    def get_part_id_audio_codec(self):
        cmd = 'grep -R Codec: /proc/asound/* | head -n 1 | sed s/.\*Codec://'
        part_id = utils.system_output(cmd).strip()
        return part_id


    def get_part_id_bluetooth(self):
        cmd = ('hciconfig hci0 version | grep Manufacturer '
               '| sed s/.\*Manufacturer://')
        part_id = utils.system_output(cmd).strip()
        return part_id


    def get_part_id_cpu(self):
        cmd = 'grep -m 1 \'model name\' /proc/cpuinfo | sed s/.\*://' 
        part_id = utils.system_output(cmd).strip()
        return part_id


    def get_part_id_touchpad(self):
        cmd = ' grep -i Touchpad /proc/bus/input/devices | sed s/.\*=//'
        part_id = utils.system_output(cmd).strip('"')
        return part_id


    def get_part_id_webcam(self):
        cmd = 'grep -i -m 1 camera %s | sed s/.\*Product://' % self._syslog
        part_id = utils.system_output(cmd).strip()
        return part_id


    def run_once(self, approved_db=None):
        self._system = {}
        self._failures = {}
        if approved_db is None:
            approved_db = 'approved_components'
        db = os.path.join(self.bindir, approved_db)
        self._approved = eval(utils.read_file(db))
        logging.debug('Approved DB: %s', self._approved)

        for cid in self._cids:
            self.check_component(cid, getattr(self, 'get_' + cid)())

        logging.debug('System: %s', self._system)

        outdb = os.path.join(self.resultsdir, 'system_components')
        utils.open_write_close(outdb, str(self._system))

        if self._failures:
            raise error.TestFail(self._failures)
