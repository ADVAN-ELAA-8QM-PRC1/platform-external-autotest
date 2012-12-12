#!/usr/bin/python -u
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Exposes the FAFTClient interface over XMLRPC.

It launches a XMLRPC server and exposes the interface of FAFTClient object.
The FAFTClient object aggreates some useful functions of exisintg SAFT
libraries.
"""

import functools, os, shutil, sys, tempfile
from optparse import OptionParser
from SimpleXMLRPCServer import SimpleXMLRPCServer

from saft import cgpt_state, chromeos_interface, flashrom_handler
from saft import kernel_handler, saft_flashrom_util, tpm_handler
from firmware_updater import FirmwareUpdater


def allow_multiple_section_input(image_operator):
    @functools.wraps(image_operator)
    def wrapper(self, section):
        if type(section) in (tuple, list):
            for sec in section:
                image_operator(self, sec)
        else:
            image_operator(self, section)
    return wrapper


class LazyFlashromHandlerProxy:
    _loaded = False
    _obj = None

    def __init__(self, *args, **kargs):
        self._args = args
        self._kargs = kargs

    def _load(self):
        self._obj = flashrom_handler.FlashromHandler()
        self._obj.init(*self._args, **self._kargs)
        self._obj.new_image()
        self._loaded = True

    def __getattr__(self, name):
        if not self._loaded:
            self._load()
        return getattr(self._obj, name)

    def reload(self):
        self._loaded = False


class FAFTClient(object):
    """A class of FAFT client which aggregates some useful functions of SAFT.

    This class can be exposed via a XMLRPC server such that its functions can
    be accessed remotely. Method naming should fit the naming rule
    '_[categories]_[method_name]' where categories contains system, ec, bios,
    kernel, cgpt, tpm, updater, etc. Methods should be called by
    'FAFTClient.[categories].[method_name]', because _dispatch will rename
    this name to '_[categories]_[method_name]'.

    Attributes:
        _chromeos_interface: An object to encapsulate OS services functions.
        _bios_handler: An object to automate BIOS flashrom testing.
        _ec_handler: An object to automate EC flashrom testing.
        _ec_image: An object to automate EC image for autest.
        _kernel_handler: An object to provide kernel related actions.
        _tpm_handler: An object to control TPM device.
        _updater: An object to update firmware.
        _temp_path: Path of a temp directory.
        _keys_path: Path of a directory, keys/, in temp directory.
        _work_path: Path of a directory, work/, in temp directory.
    """

    def __init__(self):
        """Initialize the data attributes of this class."""
        # TODO(waihong): Move the explicit object.init() methods to the
        # objects' constructors (ChromeOSInterface, FlashromHandler,
        # KernelHandler, and TpmHandler).
        self._chromeos_interface = chromeos_interface.ChromeOSInterface(False)
        # We keep the state of FAFT test in a permanent directory over reboots.
        state_dir = '/var/tmp/faft'
        self._chromeos_interface.init(state_dir, log_file='/tmp/faft_log.txt')
        os.chdir(state_dir)

        self._bios_handler = LazyFlashromHandlerProxy(
                                saft_flashrom_util,
                                self._chromeos_interface,
                                None,
                                '/usr/share/vboot/devkeys',
                                'bios')

        self._ec_handler = None
        if not os.system("mosys ec info"):
            self._ec_handler = LazyFlashromHandlerProxy(
                                  saft_flashrom_util,
                                  self._chromeos_interface,
                                  'ec_root_key.vpubk',
                                  '/usr/share/vboot/devkeys',
                                  'ec')


        self._kernel_handler = kernel_handler.KernelHandler()
        # TODO(waihong): The dev_key_path is a new argument. We do that in
        # order not to break the old image and still be able to run.
        try:
            self._kernel_handler.init(self._chromeos_interface,
                                      dev_key_path='/usr/share/vboot/devkeys',
                                      internal_disk=True)
        except:
            # Copy the key to the current working directory.
            shutil.copy('/usr/share/vboot/devkeys/kernel_data_key.vbprivk', '.')
            self._kernel_handler.init(self._chromeos_interface,
                                      internal_disk=True)

        self._tpm_handler = tpm_handler.TpmHandler()
        self._tpm_handler.init(self._chromeos_interface)

        self._cgpt_state = cgpt_state.CgptState(
                'SHORT', self._chromeos_interface, self._system_get_root_dev())

        self._updater = FirmwareUpdater(self._chromeos_interface)


        # Initialize temporary directory path
        self._temp_path = '/var/tmp/faft/autest'
        self._keys_path = os.path.join(self._temp_path, 'keys')
        self._work_path = os.path.join(self._temp_path, 'work')


    def _dispatch(self, method, params):
        """This _dispatch method handles string conversion especially.

        Since we turn off allow_dotted_names option. So any string conversion,
        like str(FAFTClient.method), i.e. FAFTClient.method.__str__, failed
        via XML RPC call.
        """
        is_str = method.endswith('.__str__')
        if is_str:
            method = method.rsplit('.', 1)[0]

        categories = ('system', 'bios', 'ec', 'kernel',
                      'tpm', 'cgpt', 'updater')
        try:
            if method.split('.', 1)[0] in categories:
                func = getattr(self, '_%s_%s' % (method.split('.',1)[0],
                                                 method.split('.',1)[1]))
            else:
                func = getattr(self, method)
        except AttributeError:
            raise Exception('method "%s" is not supported' % method)

        if is_str:
            return str(func)
        else:
            self._chromeos_interface.log('Dispatching method %s with args %s' %
                    (str(func), str(params)))
            return func(*params)


    def _system_is_available(self):
        """Function for polling the RPC server availability.

        Returns:
            Always True.
        """
        return True


    def _system_run_shell_command(self, command):
        """Run shell command.

        Args:
            command: A shell command to be run.
        """
        self._chromeos_interface.run_shell_command(command)


    def _system_run_shell_command_get_output(self, command):
        """Run shell command and get its console output.

        Args:
            command: A shell command to be run.

        Returns:
            A list of strings stripped of the newline characters.
        """
        return self._chromeos_interface.run_shell_command_get_output(command)


    def _system_software_reboot(self):
        """Request software reboot."""
        self._chromeos_interface.run_shell_command('reboot')


    def _system_get_platform_name(self):
        """Get the platform name of the current system.

        Returns:
            A string of the platform name.
        """
        # 'mosys platform name' sometimes fails. Let's get the verbose output.
        lines = self._chromeos_interface.run_shell_command_get_output(
                '(mosys -vvv platform name 2>&1) || echo Failed')
        if lines[-1].strip() == 'Failed':
            raise Exception('Failed getting platform name: ' + '\n'.join(lines))
        return lines[-1]


    def _system_get_crossystem_value(self, key):
        """Get crossystem value of the requested key.

        Args:
            key: A crossystem key.

        Returns:
            A string of the requested crossystem value.
        """
        return self._chromeos_interface.run_shell_command_get_output(
                'crossystem %s' % key)[0]


    def _system_get_root_dev(self):
        """Get the name of root device without partition number.

        Returns:
            A string of the root device without partition number.
        """
        return self._chromeos_interface.get_root_dev()


    def _system_get_root_part(self):
        """Get the name of root device with partition number.

        Returns:
            A string of the root device with partition number.
        """
        return self._chromeos_interface.get_root_part()


    def _system_set_try_fw_b(self):
        """Set 'Try Frimware B' flag in crossystem."""
        self._chromeos_interface.cs.fwb_tries = 1


    def _system_request_recovery_boot(self):
        """Request running in recovery mode on the restart."""
        self._chromeos_interface.cs.request_recovery()


    def _system_get_dev_boot_usb(self):
        """Get dev_boot_usb value which controls developer mode boot from USB.

        Returns:
          True if enable, False if disable.
        """
        return self._chromeos_interface.cs.dev_boot_usb == '1'


    def _system_set_dev_boot_usb(self, value):
        """Set dev_boot_usb value which controls developer mode boot from USB.

        Args:
          value: True to enable, False to disable.
        """
        self._chromeos_interface.cs.dev_boot_usb = 1 if value else 0


    def _system_is_removable_device_boot(self):
        """Check the current boot device is removable.

        Returns:
            True: if a removable device boots.
            False: if a non-removable device boots.
        """
        root_part = self._chromeos_interface.get_root_part()
        return self._chromeos_interface.is_removable_device(root_part)


    def _system_create_temp_dir(self, prefix='backup_'):
        """Create a temporary directory and return the path."""
        return tempfile.mkdtemp(prefix=prefix)


    def _bios_reload(self):
        """Reload the firmware image that may be changed."""
        self._bios_handler.reload()


    def _bios_get_gbb_flags(self):
        """Get the GBB flags.

        Returns:
            An integer of the GBB flags.
        """
        return self._bios_handler.get_gbb_flags()


    def _bios_get_preamble_flags(self, section):
        """Get the preamble flags of a firmware section.

        Args:
            section: A firmware section, either 'a' or 'b'.

        Returns:
            An integer of the preamble flags.
        """
        return self._bios_handler.get_section_flags(section)


    def _bios_set_preamble_flags(self, section, flags):
        """Set the preamble flags of a firmware section.

        Args:
            section: A firmware section, either 'a' or 'b'.
            flags: An integer of preamble flags.
        """
        version = self._bios_get_version(section)
        self._bios_handler.set_section_version(section, version, flags,
                                               write_through=True)


    def _bios_get_body_sha(self, section):
        """Get SHA1 hash of BIOS RW firmware section.

        Args:
            section: A firmware section, either 'a' or 'b'.
            flags: An integer of preamble flags.
        """
        return self._bios_handler.get_section_sha(section)


    def _bios_get_sig_sha(self, section):
        """Get SHA1 hash of firmware vblock in section."""
        return self._bios_handler.get_section_sig_sha(section)


    @allow_multiple_section_input
    def _bios_corrupt_sig(self, section):
        """Corrupt the requested firmware section signature.

        Args:
            section: A firmware section, either 'a' or 'b'.
        """
        self._bios_handler.corrupt_firmware(section)


    @allow_multiple_section_input
    def _bios_restore_sig(self, section):
        """Restore the previously corrupted firmware section signature.

        Args:
            section: A firmware section, either 'a' or 'b'.
        """
        self._bios_handler.restore_firmware(section)


    @allow_multiple_section_input
    def _bios_corrupt_body(self, section):
        """Corrupt the requested firmware section body.

        Args:
            section: A firmware section, either 'a' or 'b'.
        """
        self._bios_handler.corrupt_firmware_body(section)


    @allow_multiple_section_input
    def _bios_restore_body(self, section):
        """Restore the previously corrupted firmware section body.

        Args:
            section: A firmware section, either 'a' or 'b'.
        """
        self._bios_handler.restore_firmware_body(section)


    def __bios_modify_version(self, section, delta):
        """Modify firmware version for the requested section, by adding delta.

        The passed in delta, a positive or a negative number, is added to the
        original firmware version.
        """
        original_version = self._bios_get_version(section)
        new_version = original_version + delta
        flags = self._bios_handler.get_section_flags(section)
        self._chromeos_interface.log(
                'Setting firmware section %s version from %d to %d' % (
                section, original_version, new_version))
        self._bios_handler.set_section_version(section, new_version, flags,
                                               write_through=True)


    @allow_multiple_section_input
    def _bios_move_version_backward(self, section):
        """Decrement firmware version for the requested section."""
        self.__bios_modify_version(section, -1)


    @allow_multiple_section_input
    def _bios_move_version_forward(self, section):
        """Increase firmware version for the requested section."""
        self.__bios_modify_version(section, 1)


    def _bios_get_version(self, section):
        """Retrieve firmware version of a section."""
        return self._bios_handler.get_section_version(section)


    def _bios_get_datakey_version(self, section):
        """Return firmware data key version."""
        return self._bios_handler.get_section_datakey_version(section)


    def _bios_get_kernel_subkey_version(self,section):
        """Return kernel subkey version."""
        return self._bios_handler.get_section_kernel_subkey_version(section)


    def _bios_setup_EC_image(self, ec_path):
        """Setup the new EC image for later update.

        Args:
            ec_path: The path of the EC image to be updated.
        """
        self._ec_image = flashrom_handler.FlashromHandler()
        self._ec_image.init(saft_flashrom_util,
                            self._chromeos_interface,
                            'ec_root_key.vpubk',
                            '/usr/share/vboot/devkeys',
                            'ec')
        self._ec_image.new_image(ec_path)


    def _bios_get_EC_image_sha(self):
        """Get SHA1 hash of RW firmware section of the EC autest image."""
        return self._ec_image.get_section_sha('rw')


    def _bios_update_EC_from_image(self, section, flags):
        """Update EC via software sync design.

        It copys the RW section from the EC image, which is loaded by calling
        bios_setup_EC_image(), to the EC area of the specified RW section on the
        current AP firmware.

        Args:
            section: A firmware section on current BIOS, either 'a' or 'b'.
            flags: An integer of preamble flags.
        """
        blob = self._ec_image.get_section_body('rw')
        self._bios_handler.set_section_ecbin(section, blob,
                                             write_through=True)
        self._bios_set_preamble_flags(section, flags)


    def _bios_dump_whole(self, bios_path):
        """Dump the current BIOS firmware to a file, specified by bios_path.

        Args:
            bios_path: The path of the BIOS image to be written.
        """
        self._bios_handler.dump_whole(bios_path)


    def _bios_dump_rw(self, dir_path):
        """Dump the current BIOS firmware RW to dir_path.

        VBOOTA, VBOOTB, FVMAIN, FVMAINB need to be dumped.

        Args:
            dir_path: The path of directory which contains files to be written.
        """
        if not os.path.isdir(dir_path):
            raise Exception("%s doesn't exist" % dir_path)

        VBOOTA_blob = self._bios_handler.get_section_sig('a')
        VBOOTB_blob = self._bios_handler.get_section_sig('b')
        FVMAIN_blob = self._bios_handler.get_section_body('a')
        FVMAINB_blob = self._bios_handler.get_section_body('b')

        open(os.path.join(dir_path, 'VBOOTA'), 'w').write(VBOOTA_blob)
        open(os.path.join(dir_path, 'VBOOTB'), 'w').write(VBOOTB_blob)
        open(os.path.join(dir_path, 'FVMAIN'), 'w').write(FVMAIN_blob)
        open(os.path.join(dir_path, 'FVMAINB'), 'w').write(FVMAINB_blob)


    def _bios_write_whole(self, bios_path):
        """Write the firmware from bios_path to the current system.

        Args:
            bios_path: The path of the source BIOS image.
        """
        self._bios_handler.new_image(bios_path)
        self._bios_handler.write_whole()


    def _bios_write_rw(self, dir_path):
        """Write the firmware RW from dir_path to the current system.

        VBOOTA, VBOOTB, FVMAIN, FVMAINB need to be written.

        Args:
            dir_path: The path of directory which contains the source files.
        """
        if not os.path.exists(os.path.join(dir_path, 'VBOOTA')) or \
           not os.path.exists(os.path.join(dir_path, 'VBOOTB')) or \
           not os.path.exists(os.path.join(dir_path, 'FVMAIN')) or \
           not os.path.exists(os.path.join(dir_path, 'FVMAINB')):
            raise Exception("Source firmware file(s) doesn't exist.")

        VBOOTA_blob = open(os.path.join(dir_path, 'VBOOTA'), 'rb').read()
        VBOOTB_blob = open(os.path.join(dir_path, 'VBOOTB'), 'rb').read()
        FVMAIN_blob = open(os.path.join(dir_path, 'FVMAIN'), 'rb').read()
        FVMAINB_blob = open(os.path.join(dir_path, 'FVMAINB'), 'rb').read()

        self._bios_handler.set_section_sig('a', VBOOTA_blob,
                                           write_through=True)
        self._bios_handler.set_section_sig('b', VBOOTB_blob,
                                           write_through=True)
        self._bios_handler.set_section_body('a', FVMAIN_blob,
                                            write_through=True)
        self._bios_handler.set_section_body('b', FVMAINB_blob,
                                            write_through=True)


    def _ec_get_version(self):
        """Get EC version via mosys.

        Returns:
            A string of the EC version.
        """
        return self._chromeos_interface.run_shell_command_get_output(
                'mosys ec info | sed "s/.*| //"')[0]


    def _ec_get_firmware_sha(self):
        """Get SHA1 hash of EC RW firmware section."""
        return self._ec_handler.get_section_sha('rw')


    @allow_multiple_section_input
    def _ec_corrupt_sig(self, section):
        """Corrupt the requested EC section signature.

        Args:
            section: A EC section, either 'a' or 'b'.
        """
        self._ec_handler.corrupt_firmware(section, corrupt_all=True)


    @allow_multiple_section_input
    def _ec_restore_sig(self, section):
        """Restore the previously corrupted EC section signature.

        Args:
            section: An EC section, either 'a' or 'b'.
        """
        self._ec_handler.restore_firmware(section, restore_all=True)


    @allow_multiple_section_input
    def _ec_corrupt_body(self, section):
        """Corrupt the requested EC section body.

        Args:
            section: An EC section, either 'a' or 'b'.
        """
        self._ec_handler.corrupt_firmware_body(section, corrupt_all=True)


    @allow_multiple_section_input
    def _ec_restore_body(self, section):
        """Restore the previously corrupted EC section body.

        Args:
            section: An EC section, either 'a' or 'b'.
        """
        self._ec_handler.restore_firmware_body(section, restore_all=True)


    def _ec_dump_firmware(self, ec_path):
        """Dump the current EC firmware to a file, specified by ec_path.

        Args:
            ec_path: The path of the EC image to be written.
        """
        self._ec_handler.dump_whole(ec_path)


    def _ec_set_write_protect(self, enable):
        """Enable write protect of the EC flash chip.

        Args:
            enable: True if activating EC write protect. Otherwise, False.
        """
        if enable:
            self._ec_handler.enable_write_protect()
        else:
            self._ec_handler.disable_write_protect()


    @allow_multiple_section_input
    def _kernel_corrupt_sig(self, section):
        """Corrupt the requested kernel section.

        Args:
            section: A kernel section, either 'a' or 'b'.
        """
        self._kernel_handler.corrupt_kernel(section)


    @allow_multiple_section_input
    def _kernel_restore_sig(self, section):
        """Restore the requested kernel section (previously corrupted).

        Args:
            section: A kernel section, either 'a' or 'b'.
        """
        self._kernel_handler.restore_kernel(section)


    def __kernel_modify_version(self, section, delta):
        """Modify kernel version for the requested section, by adding delta.

        The passed in delta, a positive or a negative number, is added to the
        original kernel version.
        """
        original_version = self._kernel_handler.get_version(section)
        new_version = original_version + delta
        self._chromeos_interface.log(
                'Setting kernel section %s version from %d to %d' % (
                section, original_version, new_version))
        self._kernel_handler.set_version(section, new_version)


    @allow_multiple_section_input
    def _kernel_move_version_backward(self, section):
        """Decrement kernel version for the requested section."""
        self.__kernel_modify_version(section, -1)


    @allow_multiple_section_input
    def _kernel_move_version_forward(self, section):
        """Increase kernel version for the requested section."""
        self.__kernel_modify_version(section, 1)


    def _kernel_get_version(self, section):
        """Return kernel version."""
        return self._kernel_handler.get_version(section)


    def _kernel_get_datakey_version(self, section):
        """Return kernel datakey version."""
        return self._kernel_handler.get_datakey_version(section)


    def _kernel_diff_a_b(self):
        """Compare kernel A with B.

        Returns:
            True: if kernel A is different with B.
            False: if kernel A is the same as B.
        """
        rootdev = self._chromeos_interface.get_root_dev()
        kernel_a = self._chromeos_interface.join_part(rootdev, '3')
        kernel_b = self._chromeos_interface.join_part(rootdev, '5')

        # The signature (some kind of hash) for the kernel body is stored in
        # the beginning. So compare the first 64KB (including header, preamble,
        # and signature) should be enough to check them identical.
        header_a = self._chromeos_interface.read_partition(kernel_a, 0x10000)
        header_b = self._chromeos_interface.read_partition(kernel_b, 0x10000)

        return header_a != header_b


    def _kernel_resign_with_keys(self, section, key_path=None):
        """Resign kernel with temporary key."""
        self._kernel_handler.resign_kernel(section, key_path)


    def _tpm_get_firmware_version(self):
        """Retrieve tpm firmware body version."""
        return self._tpm_handler.get_fw_version()


    def _tpm_get_firmware_datakey_version(self):
        """Retrieve tpm firmware data key version."""
        return self._tpm_handler.get_fw_body_version()


    def _cgpt_run_test_loop(self):
        """Run the CgptState test loop. The tst logic is handled in the client.

        Returns:
            0: there are more cgpt tests to execute.
            1: no more CgptState test, finished.
        """
        return self._cgpt_state.test_loop()


    def _cgpt_set_test_step(self, step):
        """Set the CgptState test step.

        Args:
            step: A test step number.
        """
        self._cgpt_state.set_step(step)


    def _cgpt_get_test_step(self):
        """Get the CgptState test step.

        Returns:
            A test step number.
        """
        return self._cgpt_state.get_step()


    def _updater_setup(self, shellball=None):
        """Setup the updater.

        Args:
            shellball: Path of provided shellball. Use default shellball
                if None,
        """
        self._updater.setup(self._chromeos_interface, shellball)


    def _updater_cleanup(self):
        self._updater.cleanup_temp_dir()


    def _updater_get_fwid(self):
        """Retrieve shellball's fwid.

        This method should be called after updater_setup.

        Returns:
            Shellball's fwid.
        """
        return self._updater.retrieve_fwid()


    def _updater_resign_firmware(self, version):
        """Resign firmware with version.

        Args:
            version: new version number.
        """
        self._updater.resign_firmware(version)


    def _updater_repack_shellball(self, append):
        """Repack shellball with new fwid.

        Args:
            append: use for new fwid naming.
        """
        self._updater.repack_shellball(append)


    def _updater_run_autoupdate(self, append):
        """Run chromeos-firmwareupdate with autoupdate mode."""
        options = ['--noupdate_ec', '--nocheck_rw_compatible']
        self._updater.run_firmwareupdate(mode='autoupdate',
                                         updater_append=append,
                                         options=options)


    def _updater_run_factory_install(self):
        """Run chromeos-firmwareupdate with factory_install mode."""
        options = ['--noupdate_ec']
        self._updater.run_firmwareupdate(mode='factory_install',
                                         options=options)


    def _updater_run_bootok(self, append):
        """Run chromeos-firmwareupdate with bootok mode."""
        self._updater.run_firmwareupdate(mode='bootok',
                                         updater_append=append)


    def _updater_run_recovery(self):
        """Run chromeos-firmwareupdate with recovery mode."""
        options = ['--noupdate_ec', '--nocheck_rw_compatible']
        self._updater.run_firmwareupdate(mode='recovery',
                                         options=options)


    def _updater_get_temp_path(self):
        """Get updater's temp directory path."""
        return self._updater.get_temp_path()


    def _updater_get_keys_path(self):
        """Get updater's keys directory path."""
        return self._updater.get_keys_path()


    def _updater_get_work_path(self):
        """Get updater's work directory path."""
        return self._updater.get_work_path()


    def cleanup(self):
        """Cleanup for the RPC server. Currently nothing."""
        pass


def main():
    parser = OptionParser(usage='Usage: %prog [options]')
    parser.add_option('--port', type='int', dest='port', default=9990,
                      help='port number of XMLRPC server')
    (options, args) = parser.parse_args()

    faft_client = FAFTClient()

    # Launch the XMLRPC server to provide FAFTClient commands.
    server = SimpleXMLRPCServer(('localhost', options.port), allow_none=True,
                                logRequests=True)
    server.register_introspection_functions()
    server.register_instance(faft_client)
    print 'XMLRPC Server: Serving FAFTClient on port %s' % options.port
    server.serve_forever()


if __name__ == '__main__':
    main()
