# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Validators to verify if events conform to specified criteria."""


'''
How to add a new validator/gesture:
(1) Implement a new validator class inheriting BaseValidator,
(2) add proper method in mtb.Mtb class,
(3) add the new validator in test_conf, and
        'from validators import the_new_validator'
    in alphabetical order, and
(4) add the validator in relevant gestures; add a new gesture if necessary.

The validator template is as follows:

class XxxValidator(BaseValidator):
    """Validator to check ...

    Example:
        To check ...
          XxxValidator('<= 0.05, ~ +0.05', fingers=2)
    """

    def __init__(self, criteria_str, mf=None, fingers=1):
        name = self.__class__.__name__
        super(X..Validator, self).__init__(criteria_str, mf, name)
        self.fingers = fingers

    def check(self, packets, variation=None):
        """Check ..."""
        self.init_check(packets)
        xxx = self.packets.xxx()
        self.print_msg(...)
        return (self.fc.mf.grade(...), self.msg_list)


Note that it is also possible to instantiate a validator as
          XxxValidator('<= 0.05, ~ +0.05', slot=0)

    Difference between fingers and slot:
      . When specifying 'fingers', e.g., fingers=2, the purpose is to pass
        the information about how many fingers there are in the gesture. In
        this case, the events in a specific slot is usually not important.
        An example is to check how many fingers there are when making a click:
            PhysicalClickValidator('== 0', fingers=2)
      . When specifying 'slot', e.g., slot=0, the purpose is pass the slot
        number to the validator to examine detailed events in that slot.
        An example of such usage:
            LinearityValidator('<= 0.03, ~ +0.07', slot=0)
'''


import copy
import numpy as n
import os
import re

import firmware_log
import fuzzy
import mtb

from collections import namedtuple

from common_util import print_and_exit
from firmware_constants import AXIS, GV, MTB, VAL


# Define the ratio of points taken at both ends of a line for edge tests.
END_PERCENTAGE = 0.1

# Define other constants below.
VALIDATOR = 'Validator'


show_spec_v2 = False


def validate(packets, gesture, variation):
    """Validate a single gesture."""
    if packets is None:
        return (None, None)

    msg_list = []
    score_list = []
    vlogs = []
    for validator in gesture.validators:
        vlog = validator.check(packets, variation)
        if vlog is None:
            continue
        vlogs.append(copy.deepcopy(vlog))
        score = vlog.score

        if score is not None:
            score_list.append(score)
            # save the validator messages
            msg_validator_name = '%s' % vlog.name
            msg_criteria = '    criteria_str: %s' % vlog.criteria
            msg_score = 'score: %f' % score
            msg_list.append(os.linesep)
            msg_list.append(msg_validator_name)
            msg_list += vlog.details
            msg_list.append(msg_criteria)
            msg_list.append(msg_score)

    return (score_list, msg_list, vlogs)


def get_short_name(validator_name):
    """Get the short name of the validator.

    E.g, the short name of LinearityValidator is Linearity.
    """
    return validator_name.split(VALIDATOR)[0]


def get_validator_name(short_name):
    """Convert the short_name to its corresponding validator name.

    E.g, the validator_name of Linearity is LinearityValidator.
    """
    return short_name + VALIDATOR


def get_base_name_and_segment(validator_name):
    """Get the base name and segment of a validator.

    Examples:
        Ex 1: Linearity(BothEnds)Validator
            return ('Linearity', 'BothEnds')
        Ex 2: NoGapValidator
            return ('NoGap', None)
    """
    if '(' in validator_name:
        result = re.search('(.*)\((.*)\)%s' % VALIDATOR, validator_name)
        return (result.group(1), result.group(2))
    else:
        return (get_short_name(validator_name), None)


def get_derived_name(validator_name, segment):
    """Get the derived name based on segment value.

    Example:
      validator_name: LinearityValidator
      segment: Middle
      derived_name: Linearity(Middle)Validator
    """
    short_name = get_short_name(validator_name)
    derived_name = '%s(%s)%s' % (short_name, segment, VALIDATOR)
    return derived_name


def init_base_validator(device):
    """Initialize the device for all the Validators to use"""
    BaseValidator._device = device


def set_show_spec_v2(flag=True):
    """Set/reset show_spec_v2 to determine whether to adopt the v2 version
    of some validators.
    """
    global show_spec_v2
    show_spec_v2 = flag


class BaseValidator(object):
    """Base class of validators."""
    aggregator = 'fuzzy.average'
    _device = None

    def __init__(self, criteria_str, mf=None, device=None, name=None):
        self.criteria_str = criteria_str
        self.fc = fuzzy.FuzzyCriteria(criteria_str, mf=mf)
        self.device = device if device else BaseValidator._device
        self.packets = None
        self.vlog = firmware_log.ValidatorLog()
        self.vlog.name = name
        self.vlog.criteria = criteria_str

    def init_check(self, packets=None):
        """Initialization before check() is called."""
        self.packets = mtb.Mtb(device=self.device, packets=packets)
        self.vlog.reset()

    def _is_direction_in_variation(self, variation, directions):
        """Is any element of directions list found in variation?"""
        for direction in directions:
            if direction in variation:
                return True
        return False

    def is_horizontal(self, variation):
        """Is the direction horizontal?"""
        return self._is_direction_in_variation(variation,
                                               GV.HORIZONTAL_DIRECTIONS)

    def is_vertical(self, variation):
        """Is the direction vertical?"""
        return self._is_direction_in_variation(variation,
                                               GV.VERTICAL_DIRECTIONS)

    def is_diagonal(self, variation):
        """Is the direction diagonal?"""
        return self._is_direction_in_variation(variation,
                                               GV.DIAGONAL_DIRECTIONS)

    def get_direction(self, variation):
        """Get the direction."""
        # TODO(josephsih): raise an exception if a proper direction is not found
        if self.is_horizontal(variation):
            return GV.HORIZONTAL
        elif self.is_vertical(variation):
            return GV.VERTICAL
        elif self.is_diagonal(variation):
            return GV.DIAGONAL

    def get_direction_in_variation(self, variation):
        """Get the direction string from the variation list."""
        if isinstance(variation, tuple):
            for var in variation:
                if var in GV.GESTURE_DIRECTIONS:
                    return var
        elif variation in GV.GESTURE_DIRECTIONS:
            return variation
        return None

    def log_details(self, msg):
        """Collect the detailed messages to be printed within this module."""
        prefix_space = ' ' * 4
        formatted_msg = '%s%s' % (prefix_space, msg)
        self.vlog.insert_details(formatted_msg)


class LinearityValidator1(BaseValidator):
    """Validator to verify linearity.

    Example:
        To check the linearity of the line drawn in slot 1:
          LinearityValidator1('<= 0.03, ~ +0.07', slot=1)
    """
    # Define the partial group size for calculating Mean Squared Error
    MSE_PARTIAL_GROUP_SIZE = 1

    def __init__(self, criteria_str, mf=None, device=None, slot=0,
                 segments=VAL.WHOLE):
        self._segments = segments
        self.slot = slot
        name = get_derived_name(self.__class__.__name__, segments)
        super(LinearityValidator1, self).__init__(criteria_str, mf, device,
                                                  name)

    def _simple_linear_regression(self, ax, ay):
        """Calculate the simple linear regression and returns the
           sum of squared residuals.

        It calculates the simple linear regression line for the points
        in the middle segment of the line. This exclude the points at
        both ends of the line which sometimes have wobbles. Then it
        calculates the fitting errors of the points at the specified segments
        against the computed simple linear regression line.
        """
        # Compute the simple linear regression line for the middle segment
        # whose purpose is to avoid wobbles on both ends of the line.
        mid_segment = self.packets.get_segments_x_and_y(ax, ay, VAL.MIDDLE,
                                                        END_PERCENTAGE)
        if not self._calc_simple_linear_regression_line(*mid_segment):
            return 0

        # Compute the fitting errors of the specified segments.
        if self._segments == VAL.BOTH_ENDS:
            bgn_segment = self.packets.get_segments_x_and_y(ax, ay, VAL.BEGIN,
                                                            END_PERCENTAGE)
            end_segment = self.packets.get_segments_x_and_y(ax, ay, VAL.END,
                                                            END_PERCENTAGE)
            bgn_error = self._calc_simple_linear_regression_error(*bgn_segment)
            end_error = self._calc_simple_linear_regression_error(*end_segment)
            return max(bgn_error, end_error)
        else:
            target_segment = self.packets.get_segments_x_and_y(ax, ay,
                    self._segments, END_PERCENTAGE)
            return self._calc_simple_linear_regression_error(*target_segment)

    def _calc_simple_linear_regression_line(self, ax, ay):
        """Calculate the simple linear regression line.

           ax: array x
           ay: array y
           This method tries to find alpha and beta in the formula
                ay = alpha + beta . ax
           such that it has the least sum of squared residuals.

           Reference:
           - Simple linear regression:
             http://en.wikipedia.org/wiki/Simple_linear_regression
           - Average absolute deviation (or mean absolute deviation) :
             http://en.wikipedia.org/wiki/Average_absolute_deviation
        """
        # Convert the int list to the float array
        self._ax = 1.0 * n.array(ax)
        self._ay = 1.0 * n.array(ay)

        # If there are less than 2 data points, it is not a line at all.
        asize = self._ax.size
        if asize <= 2:
            return False

        Sx = self._ax.sum()
        Sy = self._ay.sum()
        Sxx = n.square(self._ax).sum()
        Sxy = n.dot(self._ax, self._ay)
        Syy = n.square(self._ay).sum()
        Sx2 = Sx * Sx
        Sy2 = Sy * Sy

        # compute Mean of x and y
        Mx = self._ax.mean()
        My = self._ay.mean()

        # Compute beta and alpha of the linear regression
        self._beta = 1.0 * (asize * Sxy - Sx * Sy) / (asize * Sxx - Sx2)
        self._alpha = My - self._beta * Mx
        return True

    def _calc_simple_linear_regression_error(self, ax, ay):
        """Calculate the fitting error based on the simple linear regression
        line characterized by the equation parameters alpha and beta.
        """
        # Convert the int list to the float array
        ax = 1.0 * n.array(ax)
        ay = 1.0 * n.array(ay)

        asize = ax.size
        partial = min(asize, max(1, self.MSE_PARTIAL_GROUP_SIZE))

        # spmse: squared root of partial mean squared error
        spmse = n.square(ay - self._alpha - self._beta * ax)
        spmse.sort()
        spmse = spmse[asize - partial : asize]
        spmse = n.sqrt(n.average(spmse))
        return spmse

    def check(self, packets, variation=None):
        """Check if the packets conforms to specified criteria."""
        self.init_check(packets)
        resolution_x, resolution_y = self.device.get_resolutions()
        (list_x, list_y) = self.packets.get_x_y(self.slot)
        # Compute average distance (fitting error) in pixels, and
        # average deviation on touch device in mm.
        if self.is_vertical(variation):
            ave_distance = self._simple_linear_regression(list_y, list_x)
            deviation = ave_distance / resolution_x
        else:
            ave_distance = self._simple_linear_regression(list_x, list_y)
            deviation = ave_distance / resolution_y

        self.log_details('ave fitting error: %.2f px' % ave_distance)
        msg_device = 'deviation slot%d: %.2f mm'
        self.log_details(msg_device % (self.slot, deviation))
        self.vlog.score = self.fc.mf.grade(deviation)
        return self.vlog


class LinearityValidator2(BaseValidator):
    """A new validator to verify linearity based on x-t and y-t

    Example:
        To check the linearity of the line drawn in slot 1:
          LinearityValidator2('<= 0.03, ~ +0.07', slot=1)
    """
    # Define the partial group size for calculating Mean Squared Error
    MSE_PARTIAL_GROUP_SIZE = 1

    def __init__(self, criteria_str, mf=None, device=None, slot=0,
                 segments=VAL.WHOLE):
        self._segments = segments
        self.slot = slot
        name = get_derived_name(self.__class__.__name__, segments)
        super(LinearityValidator2, self).__init__(criteria_str, mf, device,
                                                  name)

    def _calc_residuals(self, line, list_t, list_y):
        """Calculate the residuals of the points in list_t, list_y against
        the line.

        @param line: the regression line of list_t and list_y
        @param list_t: a list of time instants
        @param list_y: a list of x/y coordinates

        This method returns the list of residuals, where
            residual[i] = line[t_i] - y_i
        where t_i is an element in list_t and
              y_i is a corresponding element in list_y.

        We calculate the vertical distance (y distance) here because the
        horizontal axis, list_t, always represent the time instants, and the
        vertical axis, list_y, could be either the coordinates in x or y axis.
        """
        return [float(line(t) - y) for t, y in zip(list_t, list_y)]

    def _do_simple_linear_regression(self, list_t, list_y):
        """Calculate the simple linear regression line and returns the
        sum of squared residuals.

        @param list_t: the list of time instants
        @param list_y: the list of x or y coordinates of touch contacts

        It calculates the residuals (fitting errors) of the points at the
        specified segments against the computed simple linear regression line.

        Reference:
        - Simple linear regression:
          http://en.wikipedia.org/wiki/Simple_linear_regression
        - numpy.polyfit(): used to calculate the simple linear regression line.
          http://docs.scipy.org/doc/numpy/reference/generated/numpy.polyfit.html
        """
        # At least 2 points to determine a line.
        if len(list_t) < 2 or len(list_y) < 2:
            return []

        # Calculate the simple linear regression line.
        degree = 1
        regress_line = n.poly1d(n.polyfit(list_t, list_y, degree))

        # Compute the fitting errors of the specified segments.
        if self._segments == VAL.BOTH_ENDS:
            begin_segment = self.packets.get_segments_x_and_y(
                    list_t, list_y, VAL.BEGIN, END_PERCENTAGE)
            end_segment = self.packets.get_segments_x_and_y(
                    list_t, list_y, VAL.END, END_PERCENTAGE)
            begin_error = self._calc_residuals(regress_line, *begin_segment)
            end_error = self._calc_residuals(regress_line, *end_segment)
            return begin_error + end_error
        else:
            target_segment = self.packets.get_segments_x_and_y(
                    list_t, list_y, self._segments, END_PERCENTAGE)
            return self._calc_residuals(regress_line, *target_segment)

    def _calc_errors_single_axis(self, list_t, list_y):
        """Calculate various errors for axis-time.

        @param list_t: the list of time instants
        @param list_y: the list of x or y coordinates of touch contacts
        """
        # It is fine if axis-time is a horizontal line.
        errors_px = self._do_simple_linear_regression(list_t, list_y)
        if not errors_px:
            return (0, 0)

        # Calculate the max errors
        max_err_px = max(map(abs, errors_px))

        # Calculate the root mean square errors
        e2 = [e * e for e in errors_px]
        rms_err_px = (float(sum(e2)) / len(e2)) ** 0.5

        return (max_err_px, rms_err_px)

    def _calc_errors_all_axes(self, list_t, list_x, list_y):
        """Calculate various errors for all axes."""
        # Calculate max error and average squared error
        (max_err_x_px, rms_err_x_px) = self._calc_errors_single_axis(
                list_t, list_x)
        (max_err_y_px, rms_err_y_px) = self._calc_errors_single_axis(
                list_t, list_y)

        # Convert the unit from pixels to mms
        self.max_err_x_mm, self.max_err_y_mm = self.device.pixel_to_mm(
                (max_err_x_px, max_err_y_px))
        self.rms_err_x_mm, self.rms_err_y_mm = self.device.pixel_to_mm(
                (rms_err_x_px, rms_err_y_px))

    def check(self, packets, variation=None):
        """Check if the packets conforms to specified criteria."""
        self.init_check(packets)
        points, list_t= self.packets.get_points_and_time_for_slot(self.slot)
        list_x = [p.x for p in points]
        list_y = [p.y for p in points]

        # Calculate various errors
        self._calc_errors_all_axes(list_t, list_x, list_y)

        self.log_details('max_err: (%.2f, %.2f) mm' %
                         (self.max_err_x_mm, self.max_err_y_mm))
        self.log_details('rms_err: (%.2f, %.2f) mm' %
                         (self.rms_err_x_mm, self.rms_err_y_mm))

        self.vlog.metrics = [
                firmware_log.Metric('max_err_x_mm', self.max_err_x_mm),
                firmware_log.Metric('max_err_y_mm', self.max_err_y_mm),
                firmware_log.Metric('rms_err_x_mm', self.rms_err_x_mm),
                firmware_log.Metric('rms_err_y_mm', self.rms_err_y_mm),
        ]

        # Calculate the score based on the max error
        max_err = max(self.max_err_x_mm, self.max_err_y_mm)
        self.vlog.score = self.fc.mf.grade(max_err)
        return self.vlog


def LinearityValidator(*args, **kwargs):
    """A wrapper determining the class that is actually used based on
    show_spec_v2 option.
    """
    return (LinearityValidator2(*args, **kwargs) if show_spec_v2 else
            LinearityValidator1(*args, **kwargs))


class RangeValidator(BaseValidator):
    """Validator to check the observed (x, y) positions should be within
    the range of reported min/max values.

    Example:
        To check the range of observed edge-to-edge positions:
          RangeValidator('<= 0.05, ~ +0.05')
    """

    def __init__(self, criteria_str, mf=None, device=None):
        self.name = self.__class__.__name__
        super(RangeValidator, self).__init__(criteria_str, mf, device,
                                             self.name)

    def check(self, packets, variation=None):
        """Check the left/right or top/bottom range based on the direction."""
        self.init_check(packets)
        valid_directions = [GV.CL, GV.CR, GV.CT, GV.CB]
        Range = namedtuple('Range', valid_directions)
        actual_range = Range(*self.packets.get_range())
        spec_range = Range(self.device.axis_x.min, self.device.axis_x.max,
                           self.device.axis_y.min, self.device.axis_y.max)

        direction = self.get_direction_in_variation(variation)
        if direction in valid_directions:
            actual_edge = getattr(actual_range, direction)
            spec_edge = getattr(spec_range, direction)
            short_of_range_px = abs(actual_edge - spec_edge)
        else:
            err_msg = 'Error: the gesture variation %s is not allowed in %s.'
            print_and_exit(err_msg % (variation, self.name))

        axis_spec = (self.device.axis_x if self.is_horizontal(variation)
                                        else self.device.axis_y)
        deviation_ratio = (float(short_of_range_px) /
                           (axis_spec.max - axis_spec.min))
        self.log_details('actual: %s' % str(actual_edge))
        self.log_details('spec: %s' % str(spec_edge))
        self.log_details('deviation_ratio: %f' % deviation_ratio)
        metric_name = 'short_of_range_{}_mm'.format(direction.split('_')[-1])
        short_of_range_mm = self.device.pixel_to_mm_single_axis(
                short_of_range_px, axis_spec)
        self.vlog.metrics = [firmware_log.Metric(metric_name,
                                                 short_of_range_mm)]
        self.vlog.score = self.fc.mf.grade(deviation_ratio)
        return self.vlog


class CountTrackingIDValidator(BaseValidator):
    """Validator to check the count of tracking IDs.

    Example:
        To verify if there is exactly one finger observed:
          CountTrackingIDValidator('== 1')
    """

    def __init__(self, criteria_str, mf=None, device=None):
        name = self.__class__.__name__
        super(CountTrackingIDValidator, self).__init__(criteria_str, mf,
                                                       device, name)

    def check(self, packets, variation=None):
        """Check the number of tracking IDs observed."""
        self.init_check(packets)
        # Get the count of tracking id
        count_tid = self.packets.get_number_contacts()
        self.log_details('count of trackid IDs: %d' % count_tid)
        self.vlog.score = self.fc.mf.grade(count_tid)
        return self.vlog


class StationaryFingerValidator(BaseValidator):
    """Validator to check the count of tracking IDs.

    Example:
        To verify if the stationary finger specified by the slot does not
        move larger than a specified radius:
          StationaryFingerValidator('<= 15 ~ +10')
    """

    def __init__(self, criteria_str, mf=None, device=None, slot=0):
        name = self.__class__.__name__
        super(StationaryFingerValidator, self).__init__(criteria_str, mf,
                                                        device, name)
        self.slot = slot

    def check(self, packets, variation=None):
        """Check the moving distance of the specified finger."""
        self.init_check(packets)
        # Get the count of tracking id
        distance = self.packets.get_largest_distance(self.slot)
        self.log_details('Largest distance slot%d: %d px' %
                         (self.slot, distance))
        self.vlog.score = self.fc.mf.grade(distance)
        return self.vlog


class NoGapValidator(BaseValidator):
    """Validator to make sure that there are no significant gaps in a line.

    Example:
        To verify if there is exactly one finger observed:
          NoGapValidator('<= 5, ~ +5', slot=1)
    """

    def __init__(self, criteria_str, mf=None, device=None, slot=0):
        name = self.__class__.__name__
        super(NoGapValidator, self).__init__(criteria_str, mf, device, name)
        self.slot = slot

    def check(self, packets, variation=None):
        """There should be no significant gaps in a line."""
        self.init_check(packets)
        # Get the largest gap ratio
        gap_ratio = self.packets.get_largest_gap_ratio(self.slot)
        msg = 'Largest gap ratio slot%d: %f'
        self.log_details(msg % (self.slot, gap_ratio))
        self.vlog.score = self.fc.mf.grade(gap_ratio)
        return self.vlog


class NoReversedMotionValidator(BaseValidator):
    """Validator to measure the reversed motions in the specified slots.

    Example:
        To measure the reversed motions in slot 0:
          NoReversedMotionValidator('== 0, ~ +20', slots=0)
    """
    def __init__(self, criteria_str, mf=None, device=None, slots=(0,),
                 segments=VAL.MIDDLE):
        self._segments = segments
        name = get_derived_name(self.__class__.__name__, segments)
        self.slots = (slots,) if isinstance(slots, int) else slots
        parent = super(NoReversedMotionValidator, self)
        parent.__init__(criteria_str, mf, device, name)

    def _get_reversed_motions(self, slot, direction):
        """Get the reversed motions opposed to the direction in the slot."""
        return self.packets.get_reversed_motions(slot,
                                                 direction,
                                                 segment_flag=self._segments,
                                                 ratio=END_PERCENTAGE)

    def check(self, packets, variation=None):
        """There should be no reversed motions in a slot."""
        self.init_check(packets)
        sum_reversed_motions = 0
        direction = self.get_direction_in_variation(variation)
        for slot in self.slots:
            # Get the reversed motions.
            reversed_motions = self._get_reversed_motions(slot, direction)
            msg = 'Reversed motions slot%d: %s px'
            self.log_details(msg % (slot, reversed_motions))
            sum_reversed_motions += sum(map(abs, reversed_motions.values()))
        self.vlog.score = self.fc.mf.grade(sum_reversed_motions)
        return self.vlog


class CountPacketsValidator(BaseValidator):
    """Validator to check the number of packets.

    Example:
        To verify if there are enough packets received about the first finger:
          CountPacketsValidator('>= 3, ~ -3', slot=0)
    """

    def __init__(self, criteria_str, mf=None, device=None, slot=0):
        name = self.__class__.__name__
        super(CountPacketsValidator, self).__init__(criteria_str, mf, device,
                                                    name)
        self.slot = slot

    def check(self, packets, variation=None):
        """Check the number of packets in the specified slot."""
        self.init_check(packets)
        # Get the number of packets in that slot
        num_packets = self.packets.get_num_packets(self.slot)
        msg = 'Number of packets slot%d: %s'
        self.log_details(msg % (self.slot, num_packets))
        self.vlog.score = self.fc.mf.grade(num_packets)
        return self.vlog


class PinchValidator(BaseValidator):
    """Validator to check the pinch to zoom in/out.

    Example:
        To verify that the two fingers are drawing closer:
          PinchValidator('>= 200, ~ -100')
    """

    def __init__(self, criteria_str, mf=None, device=None):
        name = self.__class__.__name__
        super(PinchValidator, self).__init__(criteria_str, mf, device, name)

    def check(self, packets, variation):
        """Check the number of packets in the specified slot."""
        self.init_check(packets)
        # Get the relative motion of the two fingers
        slots = (0, 1)
        relative_motion = self.packets.get_relative_motion(slots)
        if variation == GV.ZOOM_OUT:
            relative_motion = -relative_motion
        msg = 'Relative motions of the two fingers: %.2f px'
        self.log_details(msg % relative_motion)
        self.vlog.score = self.fc.mf.grade(relative_motion)
        return self.vlog


class PhysicalClickValidator(BaseValidator):
    """Validator to check the events generated by physical clicks

    Example:
        To verify the events generated by a one-finger physical click
          PhysicalClickValidator('== 1', fingers=1)
    """

    def __init__(self, criteria_str, fingers, mf=None, device=None):
        self.criteria_str = criteria_str
        self.name = self.__class__.__name__
        super(PhysicalClickValidator, self).__init__(criteria_str, mf, device,
                                                     self.name)
        self.fingers = fingers

    def _get_expected_number(self):
        """Get the expected number of counts from the criteria string.

        E.g., criteria_str: '== 1'
        """
        try:
            expected_count = int(self.criteria_str.split('==')[-1].strip())
        except Exception, e:
            print 'Error: %s in the criteria string of %s' % (e, self.name)
            exit(-1)
        return expected_count

    def check(self, packets, variation=None):
        """Check the number of packets in the specified slot."""
        self.init_check(packets)
        # Get the number of physical clicks made with the specified number
        # of fingers.
        click_count = self.packets.get_physical_clicks(self.fingers)
        msg = 'Count of %d-finger physical clicks: %s'
        self.log_details(msg % (self.fingers, click_count))
        expected_click_count = self._get_expected_number()
        click_hit_rate = float(click_count) / expected_click_count
        metric_name = '{}f_click_hit_rate_%'.format(self.fingers)
        self.vlog.metrics = [firmware_log.Metric(metric_name, click_hit_rate)]
        self.vlog.score = self.fc.mf.grade(click_count)
        return self.vlog


class DrumrollValidator(BaseValidator):
    """Validator to check the drumroll problem.

    All points from the same finger should be within 2 circles of radius X mm
    (e.g. 2 mm)

    Example:
        To verify that the max radius of all minimal enclosing circles generated
        by alternately tapping the index and middle fingers is within 2.0 mm.
          DrumrollValidator('<= 2.0')
    """

    def __init__(self, criteria_str, mf=None, device=None):
        name = self.__class__.__name__
        super(DrumrollValidator, self).__init__(criteria_str, mf, device, name)

    def check(self, packets, variation=None):
        """The moving distance of the points in any tracking ID should be
        within the specified value.
        """
        self.init_check(packets)
        # For each tracking ID, compute the minimal enclosing circles,
        #     rocs = (radius_of_circle1, radius_of_circle2)
        # Return a list of such minimal enclosing circles of all tracking IDs.
        rocs = self.packets.get_list_of_rocs_of_all_tracking_ids()
        max_radius = max(rocs)
        self.log_details('Max radius: %.2f mm' % max_radius)
        self.vlog.metrics = [firmware_log.Metric('circle_radius_mm', roc)
                             for roc in rocs]
        self.vlog.score = self.fc.mf.grade(max_radius)
        return self.vlog


class NoLevelJumpValidator(BaseValidator):
    """Validator to check if there are level jumps

    When a user draws a horizontal line with thumb edge or a fat finger,
    the line could comprise a horizontal line segment followed by another
    horizontal line segment (or just dots) one level up or down, and then
    another horizontal line segment again at different horizontal level, etc.
    This validator is implemented to detect such level jumps.

    Such level jumps could also occur when drawing vertical or diagonal lines.

    Example:
        To verify the level jumps in a one-finger tracking gesture:
          NoLevelJumpValidator('<= 10, ~ +30', slots[0,])
        where slots[0,] represent the slots with numbers larger than slot 0.
        This kind of representation is required because when the thumb edge or
        a fat finger is used, due to the difficulty in handling it correctly
        in the touch device firmware, the tracking IDs and slot IDs may keep
        changing. We would like to analyze all such slots.
    """

    def __init__(self, criteria_str, mf=None, device=None, slots=0):
        name = self.__class__.__name__
        super(NoLevelJumpValidator, self).__init__(criteria_str, mf, device,
                                                   name)
        self.slots = slots

    def check(self, packets, variation=None):
        """Check if there are level jumps."""
        self.init_check(packets)
        # Get the displacements of the slots.
        slots = self.slots[0]
        displacements = self.packets.get_displacements_for_slots(slots)

        # Iterate through the collected tracking IDs
        jumps = []
        for tid in displacements:
            slot = displacements[tid][MTB.SLOT]
            for axis in AXIS.LIST:
                disp = displacements[tid][axis]
                jump = self.packets.get_largest_accumulated_level_jumps(disp)
                jumps.append(jump)
                msg = '  accu jump (%d %s): %d px'
                self.log_details(msg % (slot, axis, jump))

        # Get the largest accumulated level jump
        max_jump = max(jumps) if jumps else 0
        msg = 'Max accu jump: %d px'
        self.log_details(msg % (max_jump))
        self.vlog.score = self.fc.mf.grade(max_jump)
        return self.vlog


class ReportRateValidator(BaseValidator):
    """Validator to check the report rate.

    Example:
        To verify that the report rate is around 80 Hz. It gets 0 points
        if the report rate drops below 60 Hz.
          ReportRateValidator('== 80 ~ -20')
    """

    def __init__(self, criteria_str, mf=None, device=None):
        name = self.__class__.__name__
        super(ReportRateValidator, self).__init__(criteria_str, mf, device,
                                                  name)

    def check(self, packets, variation=None):
        """The Report rate should be within the specified range."""
        self.init_check(packets)
        # Get the report rate
        report_rate = self.packets.get_report_rate()
        msg = 'Report rate: %.2f Hz'
        self.log_details(msg % report_rate)
        self.vlog.score = self.fc.mf.grade(report_rate)
        return self.vlog
