# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This module sets up the system for the touch device firmware test suite."""

import getopt
import logging
import os
import sys

import cros_gs
import firmware_utils
import firmware_window
import keyboard_device
import mtb
import test_conf as conf
import test_flow
import touch_device
import validators

from common_util import print_and_exit
from firmware_constants import MODE, OPTIONS
from report_html import ReportHtml
from telemetry.core import browser_options, browser_finder


def _display_test_result(report_html_name, flag_skip_html):
    """Display the test result html doc using telemetry."""
    if not flag_skip_html and os.path.isdir('/usr/local/telemetry'):
        base_url = os.path.basename(report_html_name)
        url = os.path.join('file://' + conf.docroot, base_url)
        logging.info('Navigate to the URL: %s', url)

        # Launch a browser to display the url.
        default_options = browser_options.BrowserOptions()
        default_options.browser_type = 'system'
        browser_to_create = browser_finder.FindBrowser(default_options)
        browser = browser_to_create.Create()
        browser.tabs[0].Navigate(url)
    else:
        print 'You can look up the html test result in %s' % report_html_name


class firmware_TouchMTB:
    """Set up the system for touch device firmware tests."""

    def __init__(self, options):
        self.options = options

        # Get the board name
        self.board = firmware_utils.get_board()

        # Create the touch device
        # If you are going to be testing a touchscreen, set it here
        self.touch_device = touch_device.TouchDevice(
            is_touchscreen=options[OPTIONS.TOUCHSCREEN])
        self._check_device(self.touch_device)
        validators.init_base_validator(self.touch_device)

        # Set show_spec_v2 in validators module if proper.
        # This option makes the validators module to use
        # the validators of spec v2 if available.
        if options[OPTIONS.SHOW_SPEC_V2]:
            validators.set_show_spec_v2()

        # Create the keyboard device.
        self.keyboard = keyboard_device.KeyboardDevice()
        self._check_device(self.keyboard)

        # Get the MTB parser.
        self.parser = mtb.MtbParser()

        # Get a simple x object to manipulate X properties.
        self.simple_x = firmware_utils.SimpleX('aura')

        # Create a simple gtk window.
        self._get_screen_size()
        self._get_touch_device_window_geometry()
        self._get_prompt_frame_geometry()
        self._get_result_frame_geometry()
        self.win = firmware_window.FirmwareWindow(
                size=self.screen_size,
                prompt_size=self.prompt_frame_size,
                image_size=self.touch_device_window_size,
                result_size=self.result_frame_size)

        mode = options[OPTIONS.MODE]
        if options[OPTIONS.RESUME]:
            # Use the firmware version of the real touch device for recording.
            firmware_version = self.touch_device.get_firmware_version()
            self.log_dir = options[OPTIONS.RESUME]
        elif options[OPTIONS.REPLAY]:
            # Use the firmware version of the specified logs for replay.
            self.log_dir = options[OPTIONS.REPLAY]
            fw_str, date = firmware_utils.get_fw_and_date(self.log_dir)
            _, firmware_version = fw_str.split(conf.fw_prefix)
        else:
            # Use the firmware version of the real touch device for recording.
            firmware_version = self.touch_device.get_firmware_version()
            self.log_dir = firmware_utils.create_log_dir(firmware_version, mode)

        # Create the HTML report object and the output object to print messages
        # on the window and to print the results in the report.
        self._create_report_name(mode, firmware_version)
        self.report_html = ReportHtml(self.report_html_name,
                                      self.screen_size,
                                      self.touch_device_window_size,
                                      conf.score_colors)
        self.output = firmware_utils.Output(self.log_dir,
                                            self.report_name,
                                            self.win, self.report_html)

        # Get the test_flow object which will guide through the gesture list.
        self.test_flow = test_flow.TestFlow(self.touch_device_window_geometry,
                                            self.touch_device,
                                            self.keyboard,
                                            self.win,
                                            self.parser,
                                            self.output,
                                            firmware_version,
                                            options=options)

        # Register some callback functions for firmware window
        self.win.register_callback('expose_event',
                                   self.test_flow.init_gesture_setup_callback)

        # Register a callback function to watch keyboard input events.
        # This is required because the set_input_focus function of a window
        # is flaky maybe due to problems of the window manager.
        # Hence, we handle the keyboard input at a lower level.
        self.win.register_io_add_watch(self.test_flow.user_choice_callback,
                                       self.keyboard.system_device)

        # Stop power management so that the screen does not dim during tests
        firmware_utils.stop_power_management()

    def _check_device(self, device):
        """Check if a device has been created successfully."""
        if device.device_node is None:
            logging.error('Cannot find device_node.')
            exit(-1)

    def _create_report_name(self, mode, firmware_version):
        """Create the report names for both plain-text and html files.

        A typical html file name looks like:
            touch_firmware_report-lumpy-fw_11.25-20121016_080924.html
        """
        firmware_str = conf.fw_prefix + firmware_version
        curr_time = firmware_utils.get_current_time_str()
        fname = conf.filename.sep.join([conf.report_basename,
                                        self.board,
                                        firmware_str,
                                        mode,
                                        curr_time])
        self.report_name = os.path.join(self.log_dir, fname)
        self.report_html_name = self.report_name + conf.html_ext

    def _get_screen_size(self):
        """Get the screen size."""
        self.screen_size = self.simple_x.get_screen_size()

    def _get_touch_device_window_geometry(self):
        """Get the preferred window geometry to display mtplot."""
        display_ratio = 0.7
        self.touch_device_window_geometry = \
                self.touch_device.get_display_geometry(
                self.screen_size, display_ratio)
        self.touch_device_window_size = self.touch_device_window_geometry[0:2]

    def _get_prompt_frame_geometry(self):
        """Get the display geometry of the prompt frame."""
        (_, wint_height, _, _) = self.touch_device_window_geometry
        screen_width, screen_height = self.simple_x.get_screen_size()
        win_x = 0
        win_y = 0
        win_width = screen_width
        win_height = screen_height - wint_height
        self.winp_geometry = (win_x, win_y, win_width, win_height)
        self.prompt_frame_size = (win_width, win_height)

    def _get_result_frame_geometry(self):
        """Get the display geometry of the test result frame."""
        (wint_width, wint_height, _, _) = self.touch_device_window_geometry
        screen_width, _ = self.simple_x.get_screen_size()
        win_width = screen_width - wint_width
        win_height = wint_height
        self.result_frame_size = (win_width, win_height)

    def main(self):
        """A helper to enter gtk main loop."""
        # Enter the window event driven mode.
        fw.win.main()

        # Resume the power management.
        firmware_utils.start_power_management()

        # Release simple x before launching the Chrome browser to display the
        # html test result.
        del self.simple_x
        flag_skip_html = self.options[OPTIONS.SKIP_HTML]
        try:
            _display_test_result(self.report_html_name, flag_skip_html)
        except Exception, e:
            print 'Warning: cannot display the html result file: %s\n' % e
            print ('You can access the html result file: "%s"\n' %
                   self.report_html_name)
        finally:
            print 'You can upload all data in the latest result directory:'
            print '  $ DISPLAY=:0 OPTIONS="-u latest" python main.py\n'
            print ('You can also upload any test result directory, e.g., '
                   '"20130702_063631-fw_1.23-manual", in "%s"' %
                   conf.log_root_dir)
            print ('  $ DISPLAY=:0 OPTIONS="-u 20130702_063631-fw_11.23-manual"'
                   ' python main.py\n')


def upload_to_gs(log_dir):
    """Upload the gesture event files specified in log_dir to Google cloud
    storage server.

    @param log_dir: the log directory of which the gesture event files are
            to be uploaded to Google cloud storage server
    """
    # Set up gsutil package.
    # The board argument is used to locate the proper bucket directory
    gs = cros_gs.CrosGs(firmware_utils.get_board())

    log_path = os.path.join(conf.log_root_dir, log_dir)
    if not os.path.isdir(log_path):
        print_and_exit('Error: the log path "%s" does not exist.' % log_path)

    print 'Uploading "%s" to %s ...\n' % (log_path, gs.bucket)
    try:
        gs.upload(log_path)
    except Exception, e:
        msg = 'Error in uploading event files in %s: %s.'
        print_and_exit(msg % (log_path, e))


def _usage_and_exit():
    """Print the usage of this program."""
    print 'Usage: $ DISPLAY=:0 [OPTIONS="options"] python %s\n' % sys.argv[0]
    print 'options:'
    print '  -h, --%s' % OPTIONS.HELP
    print '        show this help'
    print '  -i, --%s iterations' % OPTIONS.ITERATIONS
    print '        specify the number of iterations'
    print '  -m, --%s mode' % OPTIONS.MODE
    print '        specify the gesture playing mode'
    print '        mode could be one of the following options'
    print '            calibration: conducting pressure calibration'
    print '            complete: all gestures including those in ' \
                                'both manual mode and robot mode'
    print '            manual: all gestures minus gestures in robot mode'
    print '            robot: using robot to perform gestures automatically'
    print '            robot_int: using robot with finger interaction'
    print '            robot_sim: robot simulation, for developer only'
    print '  --%s' % OPTIONS.SHOW_SPEC_V2
    print '        Show the results derived with the validator spec v2.'
    print '  --%s log_dir' % OPTIONS.REPLAY
    print '        Replay the gesture files and get the test results.'
    print '        log_dir is a log sub-directory in %s' % conf.log_root_dir
    print '  --%s log_dir' % OPTIONS.RESUME
    print '        Resume recording the gestures files in the log_dir.'
    print '        log_dir is a log sub-directory in %s' % conf.log_root_dir
    print '  -s, --%s' % OPTIONS.SIMPLIFIED
    print '        Use one variation per gesture'
    print '  --%s' % OPTIONS.SKIP_HTML
    print '        Do not show the html test result.'
    print '  -t, --%s' % OPTIONS.TOUCHSCREEN
    print '        Use the touchscreen instead of a touchpad'
    print '  -u, --%s log_dir' % OPTIONS.UPLOAD
    print '        Upload the gesture event files in the specified log_dir '
    print '        to Google cloud storage server.'
    print '        It uploads results that you already have from a previous run'
    print '        without re-running the test.'
    print '        log_dir could be either '
    print '        (1) a directory in %s' % conf.log_root_dir
    print '        (2) a full path, or'
    print '        (3) the default "latest" directory in %s if omitted' % \
                   conf.log_root_dir
    print
    print 'Example:'
    print '  # Use the robot to perform 3 iterations of the robot gestures.'
    print '  $ DISPLAY=:0 OPTIONS="-m robot_sim -i 3" python main.py\n'
    print '  # Perform 1 iteration of the manual gestures.'
    print '  $ DISPLAY=:0 OPTIONS="-m manual" python main.py\n'
    print '  # Perform 1 iteration of all manual and robot gestures.'
    print '  $ DISPLAY=:0 OPTIONS="-m complete" python main.py\n'
    print '  # Perform pressure calibration.'
    print '  $ DISPLAY=:0 OPTIONS="-m calibration" python main.py\n'
    print '  # Replay the gesture files in the latest log directory.'
    print '  $ DISPLAY=:0 OPTIONS="--replay latest" python main.py\n'
    example_log_dir = '20130226_040802-fw_1.2-manual'
    print '  # Replay the gesture files in %s/%s' % (conf.log_root_dir,
                                                     example_log_dir)
    print '  $ DISPLAY=:0 OPTIONS="--replay %s" python main.py\n' % \
            example_log_dir

    print '  # Resume recording the gestures in the latest log directory.'
    print '  $ DISPLAY=:0 OPTIONS="--resume latest" python main.py\n'
    print '  # Resume recording the gestures in %s/%s.' % (conf.log_root_dir,
                                                           example_log_dir)
    print '  $ DISPLAY=:0 OPTIONS="--resume %s" python main.py\n' % \
            example_log_dir
    print '  # Show the results derived with the new validator spec.'
    print '  $ DISPLAY=:0 OPTIONS="--show_spec_v2" python main.py\n'

    print ('  # Upload the gesture event files specified in the log_dir '
             'to Google cloud storage server.')
    print ('  $ DISPLAY=:0 OPTIONS="-u 20130701_020120-fw_11.23-complete" '
           'python main.py\n')
    print ('  # Upload the gesture event files in the "latest" directory '
           'to Google cloud storage server.')
    print '  $ DISPLAY=:0 OPTIONS="-u latest" python main.py\n'

    sys.exit(1)


def _parsing_error(msg):
    """Print the usage and exit when encountering parsing error."""
    print 'Error: %s' % msg
    _usage_and_exit()


def _parse_options():
    """Parse the options.

    Note that the options are specified with environment variable OPTIONS,
    because pyauto seems not compatible with command line options.
    """
    # Set the default values of options.
    options = {OPTIONS.ITERATIONS: 1,
               OPTIONS.MODE: MODE.MANUAL,
               OPTIONS.REPLAY: None,
               OPTIONS.RESUME: None,
               OPTIONS.SHOW_SPEC_V2: False,
               OPTIONS.SIMPLIFIED: False,
               OPTIONS.SKIP_HTML: False,
               OPTIONS.TOUCHSCREEN: False,
               OPTIONS.UPLOAD: None,
    }

    # Get the command line options or get the options from environment OPTIONS
    options_list = sys.argv[1:] or os.environ.get('OPTIONS', '').split()
    if not options_list:
        return options

    short_opt = 'hi:m:stu:'
    long_opt = [OPTIONS.HELP,
                OPTIONS.ITERATIONS + '=',
                OPTIONS.MODE + '=',
                OPTIONS.REPLAY + '=',
                OPTIONS.RESUME + '=',
                OPTIONS.SHOW_SPEC_V2,
                OPTIONS.SIMPLIFIED,
                OPTIONS.SKIP_HTML,
                OPTIONS.TOUCHSCREEN,
                OPTIONS.UPLOAD + '=',
    ]
    try:
        opts, args = getopt.getopt(options_list, short_opt, long_opt)
    except getopt.GetoptError, err:
        _parsing_error(str(err))

    for opt, arg in opts:
        if opt in ('-h', '--%s' % OPTIONS.HELP):
            _usage_and_exit()
        elif opt in ('-i', '--%s' % OPTIONS.ITERATIONS):
            if arg.isdigit():
                options[OPTIONS.ITERATIONS] = int(arg)
            else:
                _usage_and_exit()
        elif opt in ('-m', '--%s' % OPTIONS.MODE):
            arg = arg.lower()
            if arg in MODE.GESTURE_PLAY_MODE:
                options[OPTIONS.MODE] = arg
            else:
                print 'Warning: -m should be one of %s' % MODE.GESTURE_PLAY_MODE
        elif opt in ('--%s' % OPTIONS.REPLAY, '--%s' % OPTIONS.RESUME):
            log_dir = os.path.join(conf.log_root_dir, arg)
            if os.path.isdir(log_dir):
                # opt could be either '--replay' or '--resume'.
                # We would like to strip off the '-' on the left hand side.
                options[opt.lstrip('-')] = log_dir
            else:
                print 'Error: the log directory "%s" does not exist.' % log_dir
                _usage_and_exit()
        elif opt in ('--%s' % OPTIONS.SHOW_SPEC_V2,):
            options[OPTIONS.SHOW_SPEC_V2] = True
        elif opt in ('-s', '--%s' % OPTIONS.SIMPLIFIED):
            options[OPTIONS.SIMPLIFIED] = True
        elif opt in ('--%s' % OPTIONS.SKIP_HTML,):
            options[OPTIONS.SKIP_HTML] = True
        elif opt in ('-t', '--%s' % OPTIONS.TOUCHSCREEN):
            options[OPTIONS.TOUCHSCREEN] = True
        elif opt in ('-u', '--%s' % OPTIONS.UPLOAD):
            upload_to_gs(arg)
            sys.exit()
        else:
            msg = 'This option "%s" is not supported.' % opt
            _parsing_error(opt)

    print 'Note: the %s mode is used.' % options[OPTIONS.MODE]
    return options


if __name__ == '__main__':
    options = _parse_options()
    fw = firmware_TouchMTB(options)
    fw.main()
