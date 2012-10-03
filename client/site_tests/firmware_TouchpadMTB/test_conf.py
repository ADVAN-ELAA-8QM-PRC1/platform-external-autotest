# -*- coding: utf-8 -*-
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This configuration file defines the gestures to perform."""

from firmware_utils import Gesture
from validators import (CountPacketsValidator,
                        CountTrackingIDValidator,
                        DrumrollValidator,
                        LinearityValidator,
                        NoGapValidator,
                        NoReversedMotionValidator,
                        PhysicalClickValidator,
                        PinchValidator,
                        RangeValidator,
                        StationaryFingerValidator,
)

# Include some constants
execfile('firmware_constants.py', globals())


# Define which score aggregator is to be used. A score aggregator collects
# the scores from every tests and calculates the final score for the touchpad
# firmware test suite.
score_aggregator = 'fuzzy.average'


# Define the gesture list that the user needs to perform in the test suite.
gesture_list = [
    Gesture(
        name='one_finger_tracking',
        variations=((LR, RL, TB, BT, BLTR, TRBL),
                    (SLOW, NORMAL),
        ),
        prompt='Draw a {0} line {1} in {2}.',
        subprompt={
            LR: ('horizontal', 'from left edge to right edge',),
            RL: ('horizontal', 'from right edge to left edge',),
            TB: ('vertical', 'from top edge to bottom edge',),
            BT: ('vertical', 'from bottom edge to top edge',),
            BLTR: ('diagonal', 'from bottom left to top right',),
            TRBL: ('diagonal', 'from top right to bottom left',),
            SLOW: ('3 seconds',),
            NORMAL: ('1 second',),
        },
        validators=(
            CountTrackingIDValidator('== 1'),
            LinearityValidator('<= 0.03, ~ +0.07'),
            NoReversedMotionValidator('== 0, ~ +20', slots=0),
            RangeValidator('<= 0.05, ~ +0.05'),
        ),
    ),

    Gesture(
        name='two_finger_tracking',
        variations=((LR, RL, TB, BT, BLTR, TRBL),
                    (SLOW, NORMAL),
        ),
        prompt='Use two fingers to draw {0} lines {1} in {2}.',
        subprompt={
            LR: ('horizontal', 'from left edge to right edge',),
            RL: ('horizontal', 'from right edge to left edge',),
            TB: ('vertical', 'from top edge to bottom edge',),
            BT: ('vertical', 'from bottom edge to top edge',),
            BLTR: ('diagonal', 'from bottom left to top right',),
            TRBL: ('diagonal', 'from top right to bottom left',),
            SLOW: ('3 seconds',),
            NORMAL: ('1 second',),
        },
        validators=(
            CountTrackingIDValidator('== 2'),
            LinearityValidator('<= 0.03, ~ +0.07', fingers=2),
            NoReversedMotionValidator('== 0, ~ +20', slots=(0, 1)),
        ),
    ),

    Gesture(
        # also covers stationary_finger_not_affected_by_2nd_moving_finger
        name='finger_crossing',
        variations=((LR, RL, TB, BT, BLTR, TRBL),
                    (SLOW, NORMAL),
        ),
        prompt='The 1st finger touches the center of the touchpad. '
               'The 2nd finger moves {0} {1} in {2}.',
        subprompt={
            LR: ('from left to right', 'above the 1st finger'),
            RL: ('from right to left', 'below the 1st finger'),
            TB: ('from top to bottom', 'on the right to the 1st finger'),
            BT: ('from bottom to top', 'on the left to the 1st finger'),
            BLTR: ('from bottom left to top right' 'above the 1st finger',),
            TRBL: ('from top right to bottom left', 'below the 1st finger'),
            SLOW: ('3 seconds',),
            NORMAL: ('1 second',),
        },
        validators=(
            CountTrackingIDValidator('== 2'),
            NoGapValidator('<= 5, ~ +5', slot=1),
            NoReversedMotionValidator('== 0, ~ +20', slots=1),
            StationaryFingerValidator('<= 20, ~ +20', slot=0),
        ),
    ),

    Gesture(
        name='one_finger_swipe',
        variations=(BLTR, TRBL),
        prompt='Use a finger to swipe quickly {0}.',
        subprompt={
            BLTR: ('from bottom left to top right',),
            TRBL: ('from top right to bottom left',),
        },
        validators=(
            CountPacketsValidator('>= 3, ~ -3', slot=0),
            CountTrackingIDValidator('== 1'),
        ),
    ),

    Gesture(
        name='two_finger_swipe',
        variations=(TB, BT),
        prompt='Use two fingers to swipe quickly {0}.',
        subprompt={
            TB: ('from top to bottom',),
            BT: ('from bottom to top',),
        },
        validators=(
            CountPacketsValidator('>= 3, ~ -3', slot=0),
            CountPacketsValidator('>= 3, ~ -3', slot=1),
            CountTrackingIDValidator('== 2'),
        ),
    ),

    Gesture(
        name='pinch_to_zoom',
        variations=(ZOOM_IN, ZOOM_OUT),
        prompt='Use two fingers to pinch to {0} by drawing {1}.',
        subprompt={
            ZOOM_IN: ('zoom in', 'farther'),
            ZOOM_OUT: ('zoom out', 'closer'),
        },
        validators=(
            CountTrackingIDValidator('== 2'),
            PinchValidator('>= 200, ~ -100')
        ),
    ),

    Gesture(
        name='one_finger_tap',
        variations=(TL, TR, BL, BR, TS, BS, LS, RS, CENTER),
        prompt='Use one finger to make a tap on the {0} of the pad.',
        subprompt={
            TL: ('top left corner',),
            TR: ('top right corner',),
            BL: ('bottom left corner',),
            BR: ('bottom right corner',),
            TS: ('top side',),
            BS: ('bottom side',),
            LS: ('left hand side',),
            RS: ('right hand side',),
            CENTER: ('center',),
        },
        validators=(
            CountTrackingIDValidator('== 1'),
            PhysicalClickValidator('== 0', fingers=1),
            PhysicalClickValidator('== 0', fingers=2),
        ),
    ),

    Gesture(
        name='two_finger_tap',
        variations=(HORIZONTAL, VERTICAL, DIAGONAL),
        prompt='Use two fingers aligned {0} to tap 3 times.',
        subprompt={
            HORIZONTAL: ('horizontally',),
            VERTICAL: ('vertically',),
            DIAGONAL: ('diagonally',),
        },
        validators=(
            CountTrackingIDValidator('== 6'),
            PhysicalClickValidator('== 0', fingers=1),
            PhysicalClickValidator('== 0', fingers=2),
        ),
    ),

    Gesture(
        name='one_finger_physical_click',
        variations=None,
        prompt='Use one finger to make 1 physical click.',
        subprompt=None,
        validators=(
            CountTrackingIDValidator('== 1'),
            PhysicalClickValidator('== 1', fingers=1),
        ),
    ),

    Gesture(
        name='two_fingers_physical_click',
        variations=None,
        prompt='Use two fingers to make 1 physical click.',
        subprompt=None,
        validators=(
            CountTrackingIDValidator('== 2'),
            PhysicalClickValidator('== 1', fingers=2),
        ),
    ),

    Gesture(
        name='three_fingers_physical_click',
        variations=None,
        prompt='Use three fingers to make 1 physical click.',
        subprompt=None,
        validators=(
            CountTrackingIDValidator('== 3'),
            PhysicalClickValidator('== 1', fingers=3),
        ),
    ),

    Gesture(
        name='four_fingers_physical_click',
        variations=None,
        prompt='Use four fingers to make 1 physical click.',
        subprompt=None,
        validators=(
            CountTrackingIDValidator('== 4'),
            PhysicalClickValidator('== 1', fingers=4),
        ),
    ),

    Gesture(
        name='five_fingers_physical_click',
        variations=None,
        prompt='Use five fingers to make 1 physical click.',
        subprompt=None,
        validators=(
            CountTrackingIDValidator('== 5'),
            PhysicalClickValidator('== 1', fingers=5),
        ),
    ),

    Gesture(
        name='stationary_finger_not_affected_by_2nd_finger_taps',
        variations=None,
        prompt='Place your left finger on the middle of the pad. '
               'And use 2nd finger to tap around the first finger',
        subprompt=None,
        validators=(
            StationaryFingerValidator('== 0, ~ +20', slot=0),
            CountTrackingIDValidator('>= 2'),
        ),
    ),

    Gesture(
        name='fat_finger_move_with_resting_finger',
        variations=(LR, RL, TB, BT),
        prompt='With a stationary finger resting on the {0} of the pad, '
               'the 2nd FAT finger moves {1} {2} the first finger.',
        subprompt={
            LR: ('center', 'from left to right', 'below'),
            RL: ('bottom', 'from right to left', 'above'),
            TB: ('center', 'from top to bottom', 'on the right to'),
            BT: ('center', 'from bottom to top', 'on the left to'),
        },
        validators=(
            CountTrackingIDValidator('== 2'),
        ),
    ),

    Gesture(
        name='drag_edge_thumb',
        variations=(LR, RL, TB, BT),
        prompt='Drag the edge of your thumb horizontally {1} across the pad',
        subprompt={
            LR: ('from left to right',),
            RL: ('from right to left',),
        },
        validators=(
            CountTrackingIDValidator('== 1'),
        ),
    ),

    Gesture(
        # TODO(josephsih): make a special two-finger pen to perform this
        # gesture so that the finger distance remains the same every time
        # this test is conducted.
        name='two_close_fingers_tracking',
        variations=(LR, TB, TLBR),
        prompt='With two fingers close together (lightly touching each other) '
               'in a two finger scrolling gesture, draw a {0} line {1}.',
        subprompt={
            LR: ('horizontal', 'from left to right',),
            TB: ('vertical', 'from right to left',),
            TLBR: ('diagonal', 'from top left to bottom right',),
        },
        validators=(
            CountTrackingIDValidator('== 2'),
        ),
    ),

    Gesture(
        name='resting_finger_plus_2nd_finger_move',
        variations=(TLBR, BRTL),
        prompt='With a stationary finger resting on the bottom left corner, '
               'the 2nd finger moves {0} in 3 seconds.',
        subprompt={
            TLBR: ('from top left to bottom right',),
            BRTL: ('from bottom right to top left',),
        },
        validators=(
            CountTrackingIDValidator('== 2'),
        ),
    ),

    Gesture(
        name='two_fat_fingers_tracking',
        variations=(LR, RL),
        prompt='Place two FAT fingers separated by about 1 cm on the pad '
            'next to each other. Move {0} with the two fingers.',
        subprompt={
            LR: ('from left to right',),
            RL: ('from right to left',),
        },
        validators=(
            CountTrackingIDValidator('== 2'),
        ),
    ),

    Gesture(
        name='first_finger_tracking_and_second_finger_taps',
        variations=(TLBR, BRTL),
        prompt='A finger moves {0} slowly in 3 seconds. Without the 1st finger '
               'leaving the pad, the 2nd finger taps gently for 3 times.',
        subprompt={
            TLBR: ('from top left to bottom right',),
            BRTL: ('from bottom right to top left',),
        },
        validators=(
            CountTrackingIDValidator('== 4'),
        ),
    ),

    Gesture(
        name='drumroll',
        variations=(SLOW, NORMAL, FAST),
        prompt='Use two fingers to make drum roll {0} for a total of '
               '5 seconds.',
        subprompt={
            SLOW: ('at about 1 tap per second',),
            NORMAL: ('at about 2 taps per second',),
            FAST: ('as fast as possible',),
        },
        validators=(
            CountTrackingIDValidator('>= 5'),
            DrumrollValidator('<= 20, ~ +30'),
        ),
        timeout = 500,
    ),

]


class FileName:
    """A dummy class to hold the attributes in a test file name."""
    pass
filename = FileName()
filename.sep = '-'
filename.ext = 'dat'
