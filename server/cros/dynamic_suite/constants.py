# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


# Job keyvals for finding debug symbols when processing crash dumps.
JOB_BUILD_KEY = 'build'
JOB_SUITE_KEY = 'suite'

# Job attribute and label names
EXPERIMENTAL_PREFIX = 'experimental_'
FW_VERSION_PREFIX = 'fw-version:'
JOB_REPO_URL = 'job_repo_url'
VERSION_PREFIX = 'cros-version:'
BOARD_PREFIX = 'board:'

# Bug filing
ISSUE_OPEN = 'open'
ISSUE_CLOSED = 'closed'
ISSUE_DUPLICATE = 'Duplicate'
ISSUE_MERGEDINTO = 'mergedInto'
ISSUE_STATE = 'state'
ISSUE_STATUS = 'status'

# Timings
ARTIFACT_FINISHED_TIME = 'artifact_finished_time'
DOWNLOAD_STARTED_TIME = 'download_started_time'
PAYLOAD_FINISHED_TIME = 'payload_finished_time'

# Reimage type names
# Please be very careful in changing or adding to these, as one needs to
# maintain backwards compatibility.
REIMAGE_TYPE_OS = 'os'
REIMAGE_TYPE_FIRMWARE = 'firmware'
