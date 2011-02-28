# Copyright (c) 2011 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging, os
from autotest_lib.client.bin import test, utils
from autotest_lib.client.common_lib import error

LIGHT_SENSOR_LOCATIONS = [ "/sys/class/iio/", "/sys/bus/iio/devices/" ]
LIGHT_SENSOR_FILES = [ "lux", "illuminance0_input" ]

class hardware_LightSensor(test.test):
    """
    Test the system's Light Sensor device.
    Failure to find the device likely indicates the kernel module is not loaded.
    Or it could mean the I2C probe for the device failed because of an incorrect
    I2C address or bus specification.
    The ebuild scripts should properly load the udev rules for light sensor so
    we can find its files in /sys/class/iio/ or /sys/bus/iio/devices, depending
    on the kernel version.
    """
    version = 1

    def run_once(self):
        found_light_sensor = 0
        for location in LIGHT_SENSOR_LOCATIONS:
            for file in LIGHT_SENSOR_FILES:
                path = location + "device0/" + file
                if os.path.exists(path):
                    found_light_sensor = 1
                    break
                else:
                    logging.info("Did not find light sensor reading at " + path)

            if found_light_sensor:
                break

        if not found_light_sensor:
            raise error.TestFail("No light sensor reading found.")
        else:
            logging.info("Found light sensor at " + path)

        str = utils.read_one_line(path)
        reading = int(str)
        if reading < 0:
            raise error.TestFail("Invalid light sensor reading (%s)" % str)
        logging.debug("light sensor reading is %d", reading);
