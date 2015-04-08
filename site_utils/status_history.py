# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import common
from autotest_lib.client.common_lib import global_config
from autotest_lib.client.common_lib import time_utils
from autotest_lib.site_utils.suite_scheduler import constants


# Values used to describe the diagnosis of a DUT.  These values are
# used to indicate both DUT status after a job or task, and also
# diagnosis of whether the DUT was working at the end of a given
# time interval.
#
# UNUSED:  Used when there are no events recorded in a given
#     time interval.
# UNKNOWN:  For an individual event, indicates that the DUT status
#     is unchanged from the previous event.  For a time interval,
#     indicates that the DUT's status can't be determined from the
#     DUT's history.
# WORKING:  Indicates that the DUT was working normally after the
#     event, or at the end of the time interval.
# BROKEN:  Indicates that the DUT needed manual repair after the
#     event, or at the end of the time interval.
#
UNUSED = 0
UNKNOWN = 1
WORKING = 2
BROKEN = 3


def parse_time(time_string):
    """Parse time according to a canonical form.

    The "canonical" form is the form in which date/time
    values are stored in the database.

    @param time_string Time to be parsed.
    """
    return int(time_utils.to_epoch_time(time_string))


class _JobEvent(object):
    """Information about an event in host history.

    This remembers the relevant data from a single event in host
    history.  An event is any change in DUT state caused by a job
    or special task.  The data captured are the start and end times
    of the event, the URL of logs to the job or task causing the
    event, and a diagnosis of whether the DUT was working or failed
    afterwards.

    This class is an adapter around the database model objects
    describing jobs and special tasks.  This is an abstract
    superclass, with concrete subclasses for `HostQueueEntry` and
    `SpecialTask` objects.

    @property start_time  Time the job or task began execution.
    @property end_time    Time the job or task finished execution.
    @property job_url     URL to the logs for the event's job.
    @property diagnosis   Working status of the DUT after the event.

    """

    get_config_value = global_config.global_config.get_config_value
    _LOG_URL_PATTERN = get_config_value('CROS', 'log_url_pattern')

    @classmethod
    def get_log_url(cls, afe_hostname, logdir):
        """Return a URL to job results.

        The URL is constructed from a base URL determined by the
        global config, plus the relative path of the job's log
        directory.

        @param afe_hostname Hostname for autotest frontend
        @param logdir Relative path of the results log directory.

        @return A URL to the requested results log.

        """
        return cls._LOG_URL_PATTERN % (afe_hostname, logdir)


    def __init__(self, start_time, end_time):
        self.start_time = parse_time(start_time)
        if end_time:
            self.end_time = parse_time(end_time)
        else:
            self.end_time = None


    def __cmp__(self, other):
        """Compare two jobs by their start time.

        This is a standard Python `__cmp__` method to allow sorting
        `_JobEvent` objects by their times.

        @param other The `_JobEvent` object to compare to `self`.

        """
        return self.start_time - other.start_time


    @property
    def job_url(self):
        """Return the URL for this event's job logs."""
        raise NotImplemented()


    @property
    def diagnosis(self):
        """Return the status of the DUT after this event.

        The diagnosis is interpreted as follows:
          UNKNOWN - The DUT status was the same before and after
              the event.
          WORKING - The DUT appeared to be working after the event.
          BROKEN - The DUT likely required manual intervention
              after the event.

        @return A valid diagnosis value.

        """
        raise NotImplemented()


class _SpecialTaskEvent(_JobEvent):
    """`_JobEvent` adapter for special tasks.

    This class wraps the standard `_JobEvent` interface around a row
    in the `afe_special_tasks` table.

    """

    @classmethod
    def get_tasks(cls, afe, host_id, start_time, end_time):
        """Return special tasks for a host in a given time range.

        Return a list of `_SpecialTaskEvent` objects representing all
        special tasks that ran on the given host in the given time
        range.  The list is ordered as it was returned by the query
        (i.e. unordered).

        @param afe         Autotest frontend
        @param host_id     Database host id of the desired host.
        @param start_time  Start time of the range of interest.
        @param end_time    End time of the range of interest.

        @return A list of `_SpecialTaskEvent` objects.

        """
        filter_start = time_utils.epoch_time_to_date_string(start_time)
        filter_end = time_utils.epoch_time_to_date_string(end_time)
        tasks = afe.get_special_tasks(
                host_id=host_id,
                time_started__gte=filter_start,
                time_started__lte=filter_end,
                is_complete=1)
        return [cls(afe.server, t) for t in tasks]


    def __init__(self, afe_hostname, afetask):
        self._afe_hostname = afe_hostname
        self._afetask = afetask
        super(_SpecialTaskEvent, self).__init__(
                afetask.time_started, afetask.time_finished)


    @property
    def job_url(self):
        logdir = ('hosts/%s/%s-%s' %
                  (self._afetask.host.hostname, self._afetask.id,
                   self._afetask.task.lower()))
        return _SpecialTaskEvent.get_log_url(self._afe_hostname, logdir)


    @property
    def diagnosis(self):
        if self._afetask.success:
            return WORKING
        elif self._afetask.task == 'Repair':
            return BROKEN
        else:
            return UNKNOWN


class _TestJobEvent(_JobEvent):
    """`_JobEvent` adapter for regular test jobs.

    This class wraps the standard `_JobEvent` interface around a row
    in the `afe_host_queue_entries` table.

    """

    @classmethod
    def get_hqes(cls, afe, host_id, start_time, end_time):
        """Return HQEs for a host in a given time range.

        Return a list of `_TestJobEvent` objects representing all the
        HQEs of all the jobs that ran on the given host in the given
        time range.  The list is ordered as it was returned by the
        query (i.e. unordered).

        @param afe         Autotest frontend
        @param host_id     Database host id of the desired host.
        @param start_time  Start time of the range of interest.
        @param end_time    End time of the range of interest.

        @return A list of `_TestJobEvent` objects.

        """
        filter_start = time_utils.epoch_time_to_date_string(start_time)
        filter_end = time_utils.epoch_time_to_date_string(end_time)
        hqelist = afe.get_host_queue_entries(
                host_id=host_id,
                start_time=filter_start,
                end_time=filter_end,
                complete=1)
        return [cls(afe.server, hqe) for hqe in hqelist]


    def __init__(self, afe_hostname, hqe):
        self._afe_hostname = afe_hostname
        self._hqe = hqe
        super(_TestJobEvent, self).__init__(
                hqe.started_on, hqe.finished_on)


    @property
    def job_url(self):
        logdir = '%s-%s' % (self._hqe.job.id, self._hqe.job.owner)
        return _TestJobEvent.get_log_url(self._afe_hostname, logdir)


    @property
    def diagnosis(self):
        if self._hqe.finished_on is not None:
            return WORKING
        else:
            return UNKNOWN


class HostJobHistory(object):
    """Class to query and remember DUT execution history.

    This class is responsible for querying the database to determine
    the history of a single DUT in a time interval of interest, and
    for remembering the query results for reporting.

    @property hostname    Host name of the DUT.
    @property start_time  Start of the requested time interval.
    @property end_time    End of the requested time interval.
    @property host        Database host object for the DUT.
    @property history     A list of jobs and special tasks that
                          ran on the DUT in the requested time
                          interval, ordered in reverse, from latest
                          to earliest.

    """

    @classmethod
    def get_host_history(cls, afe, hostname, start_time, end_time):
        """Create a HostJobHistory instance for a single host.

        Simple factory method to construct host history from a
        hostname.  Simply looks up the host in the AFE database, and
        passes it to the class constructor.

        @param afe         Autotest frontend
        @param hostname    Name of the host.
        @param start_time  Start time for the history's time
                           interval.
        @param end_time    End time for the history's time interval.

        @return A new HostJobHistory instance.

        """
        afehost = afe.get_hosts(hostname=hostname)[0]
        return cls(afe, afehost, start_time, end_time)


    @classmethod
    def get_multiple_histories(cls, afe, start_time, end_time,
                               board=None, pool=None):
        """Create HostJobHistory instances for a set of hosts.

        The set of hosts can be specified as "all hosts of a given
        board type", "all hosts in a given pool", or "all hosts
        of a given board and pool".

        @param afe         Autotest frontend
        @param start_time  Start time for the history's time
                           interval.
        @param end_time    End time for the history's time interval.
        @param board       All hosts must have this board type; if
                           `None`, all boards are allowed.
        @param pool        All hosts must be in this pool; if
                           `None`, all pools are allowed.

        @return A list of new HostJobHistory instances.

        """
        # If `board` or `pool` are both `None`, we could search the
        # entire database, which is more expensive than we want.
        # Our caller currently won't (can't) do this, but assert to
        # be safe.
        assert board is not None or pool is not None
        labels = []
        if board is not None:
            labels.append(constants.Labels.BOARD_PREFIX + board)
        if pool is not None:
            labels.append(constants.Labels.POOL_PREFIX + pool)
        kwargs = {'multiple_labels': labels}
        hosts = afe.get_hosts(**kwargs)
        return [cls(afe, h, start_time, end_time) for h in hosts]


    def __init__(self, afe, afehost, start_time, end_time):
        self._afe = afe
        self.hostname = afehost.hostname
        self.start_time = start_time
        self.end_time = end_time
        self._host = afehost
        # Don't spend time filling in the history until it's needed.
        self._history = None


    def __iter__(self):
        self._get_history()
        return self._history.__iter__()


    def _get_history(self):
        if self._history is not None:
            return
        newtasks = _SpecialTaskEvent.get_tasks(
                self._afe, self._host.id, self.start_time, self.end_time)
        newhqes = _TestJobEvent.get_hqes(
                self._afe, self._host.id, self.start_time, self.end_time)
        newhistory = newtasks + newhqes
        newhistory.sort(reverse=True)
        self._history = newhistory


    def _extract_prefixed_label(self, prefix):
        label = [l for l in self._host.labels
                    if l.startswith(prefix)][0]
        return label[len(prefix) : ]


    def get_host_board(self):
        """Return the board name for this history's DUT."""
        prefix = constants.Labels.BOARD_PREFIX
        return self._extract_prefixed_label(prefix)


    def get_host_pool(self):
        """Return the pool name for this history's DUT."""
        prefix = constants.Labels.POOL_PREFIX
        return self._extract_prefixed_label(prefix)


    def last_diagnosis(self):
        """Return the diagnosis of whether the DUT is working.

        This searches the DUT's job history from most to least
        recent, looking for jobs that indicate whether the DUT
        was working.  Return a tuple of `(diagnosis, job)`.

        The `diagnosis` entry in the tuple is one of these values:
          * UNUSED - The job history is empty.
          * UNKNOWN - All jobs in the history returned _UNKNOWN
              status.
          * WORKING - The DUT is working.
          * BROKEN - The DUT likely requires manual intervention.

        The `job` entry in the tuple is the job that led to the
        diagnosis.  The job will be `None` if the diagnosis is
        `UNUSED` or `UNKNOWN`.

        @return A tuple with the DUT's diagnosis and the job that
                determined it.

        """
        self._get_history()
        if not self._history:
            return UNUSED, None
        for job in self:
            status = job.diagnosis
            if status != UNKNOWN:
                return job.diagnosis, job
        return UNKNOWN, None
