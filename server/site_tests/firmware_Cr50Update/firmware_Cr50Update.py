# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
import time

from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros import cr50_utils
from autotest_lib.server import autotest, test
from autotest_lib.server.cros import debugd_dev_tools
from autotest_lib.server.cros.faft.firmware_test import FirmwareTest


class firmware_Cr50Update(FirmwareTest):
    """
    Verify a dut can update to the given image.

    Copy the new image onto the device and clear the update state to force
    cr50-update to run. The test will fail if Cr50 does not update or if the
    update script encounters any errors.

    @param image: the location of the update image
    @param image_type: string representing the image type. If it is "dev" then
                       don't check the RO versions when comparing versions.
    """
    version = 1
    UPDATE_TIMEOUT = 20
    ERASE_NVMEM = "erase_nvmem"

    DEV_NAME = "dev_image"
    OLD_RELEASE_NAME = "old_release_image"
    RELEASE_NAME = "release_image"
    ORIGINAL_NAME = "original_image"
    RESTORE_ORIGINAL_TRIES = 3
    SUCCESS = 0
    UPSTART_SUCCESS = 1


    def initialize(self, host, cmdline_args, release_image, dev_image,
                   old_release_image="", test=""):
        """Initialize servo and process the given images"""
        self.processed_images = False

        super(firmware_Cr50Update, self).initialize(host, cmdline_args)
        if not hasattr(self, "cr50"):
            raise error.TestNAError('Test can only be run on devices with '
                                    'access to the Cr50 console')
        # Make sure ccd is disabled so it won't interfere with the update
        self.cr50.ccd_disable()

        self.rootfs_tool = debugd_dev_tools.RootfsVerificationTool()
        self.rootfs_tool.initialize(host)
        if not self.rootfs_tool.is_enabled():
            logging.debug('Removing rootfs verification.')
            # 'enable' actually disables rootfs verification
            self.rootfs_tool.enable()

        self.host = host
        self.test = test.lower()

        # A dict used to store relevant information for each image
        self.images = {}

        running_rw = cr50_utils.GetRunningVersion(self.host)[1]
        # Get the original image from the cr50 firmware directory on the dut
        self.save_original_image(cr50_utils.CR50_FILE)

        # If Cr50 is not running the image from the cr50 firmware directory,
        # then raise an error, otherwise the test will not be able to restore
        # the original state during cleanup.
        if running_rw != self.original_rw:
            raise error.TestError("Can't determine original Cr50 version. "
                                  "Running %s, but saved %s." %
                                  (running_rw, self.original_rw))

        # Process the given images in order of oldest to newest. Get the version
        # info and add them to the update order
        self.update_order = []
        if self.test != self.ERASE_NVMEM and old_release_image:
            self.add_image_to_update_order(self.OLD_RELEASE_NAME,
                                           old_release_image)
        self.add_image_to_update_order(self.RELEASE_NAME, release_image)
        self.add_image_to_update_order(self.DEV_NAME, dev_image)
        self.verify_update_order()
        self.processed_images = True
        logging.info("Update %s", self.update_order)

        # Update to the dev image
        self.run_update(self.DEV_NAME)


    def restore_original_image(self):
        """Update to the image that was running at the start of the test.

        Returns SUCCESS if the update was successful or the update error if it
        failed.
        """
        rv = self.SUCCESS
        _, running_rw, is_dev = self.cr50.get_active_version_info()
        new_rw = cr50_utils.GetNewestVersion(running_rw, self.original_rw)

        # If Cr50 is running the original image, then no update is needed.
        if new_rw is None:
            return rv

        try:
            # If a rollback is needed, update to the dev image so it can
            # rollback to the original image.
            if new_rw != self.original_rw and not is_dev:
                logging.info("Updating to dev image to enable rollback")
                self.run_update(self.DEV_NAME, use_usb_update=True)

            logging.info("Updating to the original image %s",
                         self.original_rw)
            self.run_update(self.ORIGINAL_NAME, use_usb_update=True)
        except Exception, e:
            logging.info("cleanup update from %s to %s failed", running_rw,
                          self.original_rw)
            logging.debug(e)
            rv = e
        self.cr50.ccd_enable()
        return rv


    def cleanup(self):
        """Update Cr50 to the image it was running at the start of the test"""
        logging.warning('rootfs verification is disabled')

        # Make sure keepalive is disabled
        self.cr50.ccd_enable()
        self.cr50.send_command("ccd keepalive disable")

        # Restore the original Cr50 image
        if self.processed_images:
            for i in xrange(self.RESTORE_ORIGINAL_TRIES):
                rv = self.restore_original_image()
                if rv == self.SUCCESS:
                    logging.info("Successfully restored the original image")
                    break
            if rv != self.SUCCESS:
                raise error.TestError("Could not restore the original image")

        super(firmware_Cr50Update, self).cleanup()


    def run_usb_update(self, dest, is_newer):
        """Run usb_update with the given image.

        If the new image version is newer than the one Cr50 is running, then
        the upstart option will be used. This will reboot the AP after
        usb_updater runs, so Cr50 will finish the update and jump to the new
        image.

        If the new image version is older than the one Cr50 is running, then the
        best usb_updater can do is flash the image into the inactive partition.
        To finish th update, the 'rw' command will need to be used to force a
        rollback.

        @param dest: the image location.
        @param is_newer: True if the rw version of the update image is newer
                         than the one Cr50 is running.
        """

        result = self.host.run("status trunksd")
        if 'running' in result.stdout:
            self.host.run("stop trunksd")

        # Enable CCD, so we can detect the Cr50 reboot.
        self.cr50.ccd_enable()
        if is_newer:
            # Using -u usb_updater will post a reboot request but not reboot
            # immediately.
            result = self.host.run("usb_updater -s -u %s" % dest,
                                   ignore_status=True)
            # After a posted reboot, the usb_update exit code should equal 1.
            if result.exit_status != self.UPSTART_SUCCESS:
                logging.debug(result)
                raise error.TestError("Got unexpected usb_update exit code")
            # Reset the AP to finish the Cr50 update.
            self.cr50.send_command("sysrst pulse")
        else:
            logging.info("Flashing image into inactive partition")
            # The image at 'dest' is older than the one Cr50 is running, so
            # upstart cannot be used. Without -u Cr50 will flash the image into
            # the inactive partition and reboot immediately.
            result = self.host.run("usb_updater -s %s" % dest,
                                   ignore_timeout=True,
                                   timeout=self.UPDATE_TIMEOUT)
            logging.info(result)

        # After usb_updater finishes running, Cr50 will reboot. Wait until Cr50
        # reboots before continuing. Cr50 reboot can be detected by detecting
        # when CCD stops working.
        self.cr50.wait_for_ccd_disable()


    def finish_rollback(self, image_rw, erase_nvmem):
        """Rollback to the image in the inactive partition.

        Use the cr50 'rw' command to set the reset counter high enough to
        trigger a rollback, erase nvmem if requested, and then reboot cr50 to
        finish the rollback.

        @param image_rw: the rw version of the update image.
        @param erase_nvmem: True if nvmem needs to be erased during the
                            rollback.
        """
        self.cr50.ccd_enable()
        inactive_info = self.cr50.get_inactive_version_info()
        if inactive_info[1] != image_rw:
            raise error.TestError("Image is not in inactive partition")

        logging.info("Attempting Rollback")

        # Enable CCD keepalive before turning off the DUT. It will be removed
        # after the Cr50 reboot
        self.cr50.send_command("ccd keepalive enable")

        # Shutdown the device so it won't react to any of the following commands
        self.ec.reboot("ap-off")

        # CCD may disapppear after resetting the EC. If it does, re-enable it.
        # TODO: remove this when CCD is no longer disabled after ec reset.
        try:
            self.cr50.wait_for_ccd_disable(timeout=15)
        except error.TestFail, e:
            pass
        self.cr50.ccd_enable()

        if erase_nvmem:
            logging.info("Erasing nvmem")
            self.cr50.erase_nvmem()

        self.cr50.rollback()

        # Verify the inactive partition is the active one after the rollback.
        if inactive_info != self.cr50.get_active_version_info():
            raise error.TestError("Rollback failed")

        # Verify the system boots normally after erasing nvmem
        self.check_state((self.checkers.crossystem_checker,
                          {'mainfw_type': 'normal'}))


    def run_update(self, image_name, erase_nvmem=False, use_usb_update=False):
        """Copy the image to the DUT and upate to it.

        Normal updates will use the cr50-update script to update. If a rollback
        is True, use usb_update to flash the image and then use the 'rw'
        commands to force a rollback. On rollback updates erase_nvmem can be
        used to request that nvmem be erased during the rollback.

        @param image_name: the key in the images dict that can be used to
                           retrieve the image info.
        @param erase_nvmem: True if nvmem needs to be erased during the
                            rollback.
        @param use_usb_update: True if usb_updater should be used directly
                               instead of running the update script.
        """
        self.cr50.ccd_disable()
        # Get the current update information
        image_ver, image_ver_str, image_path = self.images[image_name]

        dest, ver = cr50_utils.InstallImage(self.host, image_path)
        assert ver == image_ver, "Install failed"
        image_rw = image_ver[1]

        running_ver = cr50_utils.GetRunningVersion(self.host)
        running_ver_str = cr50_utils.GetVersionString(running_ver)

        # If the given image is older than the running one, then we will need
        # to do a rollback to complete the update.
        rollback = (cr50_utils.GetNewestVersion(running_ver[1], image_rw) !=
                    image_rw)
        logging.info("Attempting %s from %s to %s",
                     "rollback" if rollback else "update", running_ver_str,
                     image_ver_str)

        # If a rollback is needed, flash the image into the inactive partition,
        # on or use usb_update to update to the new image if it is requested.
        if use_usb_update or rollback:
            self.run_usb_update(dest, not rollback)
        # Use cr50 console commands to rollback to the old image.
        if rollback:
            self.finish_rollback(image_rw, erase_nvmem)
        # Running the usb update or rollback will enable ccd. Disable it again.
        self.cr50.ccd_disable()

        # Get the last cr50 update related message from /var/log/messages
        last_message = cr50_utils.CheckForFailures(self.host, '')

        # Clear the update state and reboot, so cr50-update will run again.
        cr50_utils.ClearUpdateStateAndReboot(self.host)

        # Verify the version has been updated and that there have been no
        # unexpected usb_updater exit codes.
        cr50_utils.VerifyUpdate(self.host, image_ver, last_message)

        logging.info("Successfully updated from %s to %s %s", running_ver_str,
                     image_name, image_ver_str)


    def add_image_to_update_order(self, image_name, image_path):
        """Process the image. Add it to the update_order list and images dict.

        Copy the image to the DUT and get version information.

        Store the image information in the images dictionary and add it to the
        update_order list.

        Args:
            image_name: string that is what the image should be called. Used as
                        the key in the images dict.
            image_path: the path for the image.

        Raises:
            TestError if the image could not be found.
        """
        tmp_file = '/tmp/%s.bin' % image_name

        if not os.path.isfile(image_path):
            raise error.TestError("Failed to locate %s" % image_name)

        _, ver = cr50_utils.InstallImage(self.host, image_path, tmp_file)
        ver_str = cr50_utils.GetVersionString(ver)

        self.update_order.append([image_name, ver[1]])
        self.images[image_name] = (ver, ver_str, image_path)
        logging.info("%s stored at %s with version %s", image_name, image_path,
                     ver_str)


    def verify_update_order(self):
        """Verify each image in the update order has a higher version than the
        last.

        The test uses the cr50 update script to update to the next image in the
        update order. If the versions are not in ascending order then the update
        won't work. Cr50 cannot update to an older version using the standard
        update process.

        Raises:
            TestError if the versions are not in ascending order.
        """
        for i, update_info in enumerate(self.update_order[1::]):
            last_name, last_rw = self.update_order[i]
            name, rw = update_info
            if cr50_utils.GetNewestVersion(last_rw, rw) != rw:
                raise error.TestError("%s is version %s. %s needs to have a "
                                      "higher version, but it has %s" %
                                      (last_name, last_rw, name, rw))


    def save_original_image(self, dut_path):
        """Save the image currently running on the DUT.

        Copy the image from the DUT to the local tmp directory and get version
        information. Store the information in the images dict.

        @param dut_path: the location of the cr50 prod image on the DUT.
        """
        name = self.ORIGINAL_NAME
        local_dest = '/tmp/%s.bin' % name

        self.host.get_file(dut_path, local_dest)

        ver = cr50_utils.GetBinVersion(self.host, dut_path)
        ver_str = cr50_utils.GetVersionString(ver)

        self.images[name] = (ver, ver_str, local_dest)
        logging.info("%s stored at %s with version %s", name, local_dest,
                     ver_str)

        self.original_rw = ver[1]


    def after_run_once(self):
        """Add log printing what iteration we just completed"""
        logging.info("Update iteration %s ran successfully", self.iteration)


    def run_once(self, host, cmdline_args, release_image, dev_image,
                 old_release_image="", test=""):
        for i, update_info in enumerate(self.update_order):
            erase_nvmem = self.test == self.ERASE_NVMEM
            self.run_update(update_info[0], erase_nvmem=erase_nvmem)