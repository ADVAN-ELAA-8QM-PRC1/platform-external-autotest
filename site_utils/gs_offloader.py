#!/usr/bin/python
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

__help__ = """Script to archive old Autotest results to Google Storage.

Uses gsutil to archive files to the configured Google Storage bucket. Upon
successful copy, the local results directory is deleted.
"""

__author__ = 'dalecurtis@google.com (Dale Curtis)'

import logging
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import threading
import Queue

from optparse import OptionParser

import common

import is_job_complete
from autotest_lib.client.common_lib import global_config
from autotest_lib.scheduler import email_manager

# Google Storage bucket URI to store results in.
GS_URI = 'gs://chromeos-autotest-results/'

# Set this to True to enable rsync otherwise results are offloaded to GS.
USE_RSYNC = False
RSYNC_HOST_PATH = 'chromeos-sam1:/usr/local/autotest/results/'

# Nice setting for process, the higher the number the lower the priority.
NICENESS = 10

# Setting timeout to 3 hours.
TIMEOUT = 3 * 60 * 60

# Sleep time per loop.
SLEEP_TIME_SECS = 5

# Location of Autotest results on disk.
RESULTS_DIR = '/usr/local/autotest/results'

# Hosts sub-directory that contains cleanup, verify and repair jobs.
HOSTS_SUB_DIR = 'hosts'

LOG_FILENAME_FORMAT = ('/usr/local/autotest/logs/'
                       'gs_offloader_log_%Y%m%d_%H%M%S.txt')
LOGGING_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'

CLEAN_CMD = 'find %s -iname chrome_20[0-9][0-9]\* -exec rm {} \;'

NOTIFY_ADDRESS = global_config.global_config.get_config_value(
    'SCHEDULER', 'notify_email', default='')

ERROR_EMAIL_SUBJECT_FORMAT = 'GS Offloader notifications from %s'
ERROR_EMAIL_MSG_FORMAT = 'Error occured when offloading %s:\n%s'


class TimeoutException(Exception):
  pass


def timeout_handler(_signum, _frame):
  """
  Called by the SIGALRM if the offloading process has timed out.

  @raise TimeoutException: Automatically raises so that the time out is caught
                           by the try/except surrounding the Popen call.
  """
  raise TimeoutException('Process Timed Out')


def get_cmd_list(dir_entry, relative_path):
  """
  Generate the cmd_list for the specified directory entry.

  @param dir_entry: Directory entry/path that which we need a cmd_list to
                    offload.
  @param relative_path: Location in google storage or rsync that we want to
                        store this directory.

  @return: A command list to be executed by Popen.
  """
  if USE_RSYNC:
    dest_path = os.path.join(RSYNC_HOST_PATH, relative_path)
    logging.debug('Using rsync for offloading %s to %s.', dir_entry,
                  dest_path)
    return ['rsync', '-a', dir_entry, dest_path]
  else:
    dest_path = os.path.join(GS_URI, relative_path)
    logging.debug('Using google storage for offloading %s to %s.',
                  dir_entry, dest_path)
    return ['gsutil', '-m', 'cp', '-eR', '-a', 'project-private', dir_entry,
            dest_path]


def offload_hosts_sub_dir(queue):
  """
  Loop over the hosts/ sub directory and offload all the Cleanup, Verify and
  Repair Jobs.

  This will delete the job folders inside each host directory.

  @param queue The work queue to place uploading tasks onto.
  """
  logging.debug('Offloading Cleanup, Verify and Repair jobs from'
                'results/hosts/')
  # Store these results in gs://chromeos-autotest-results/hosts
  for host_entry in os.listdir(HOSTS_SUB_DIR):
    # Inside a host directory.
    # Store these results in gs://chromeos-autotest-results/hosts/{host_name}
    host_path = os.path.join(HOSTS_SUB_DIR, host_entry)
    if not os.path.isdir(host_path):
      continue
    for job_entry in os.listdir(host_path):
      # Offload all the verify, clean and repair jobs for this host.
      dir_path = os.path.join(host_path, job_entry)
      if not os.path.isdir(dir_path):
        continue
      job_id = os.path.basename(dir_path).split('-')[0]
      if not is_job_complete.is_special_task_complete(job_id):
        logging.debug('Special Task %s is not yet complete; skipping.',
                      dir_path)
        continue
      logging.debug('Processing %s', dir_path)
      queue.put((dir_path, dir_path))


def offload_dir(dir_entry, dest_path=''):
  """
  Offload the specified directory entry to the Google storage or the RSYNC host,
  but timeout if it takes too long.

  @param dir_entry: Directory entry to offload.
  @param dest_path: Location in google storage or rsync that we want to store
                    this directory.
  """
  try:
    error = False
    signal.alarm(TIMEOUT)
    stdout_file = tempfile.TemporaryFile('w+')
    stderr_file = tempfile.TemporaryFile('w+')
    process = subprocess.Popen(get_cmd_list(dir_entry, dest_path),
                               stdout=stdout_file, stderr=stderr_file)
    process.wait()
    signal.alarm(0)
    if process.returncode == 0:
      shutil.rmtree(dir_entry)
    else:
      error = True
  except TimeoutException:
    process.terminate()
    logging.error('Offloading %s timed out after waiting %d seconds.',
                  dir_entry, TIMEOUT)
    error = True
  finally:
    signal.alarm(0)
    if error:
      # Rewind the log files for stdout and stderr and log their contents.
      stdout_file.seek(0)
      stderr_file.seek(0)
      stderr = stderr_file.read()

      # The second to last line of stderr has the main error message we're
      # interested in.
      try:
        error_msg = stderr.split('\n')[-2]
      except IndexError:
        # In case stderr does not meet our expected format, send out the whole
        # message.
        error_msg = stderr

      email_subject = ERROR_EMAIL_SUBJECT_FORMAT % socket.gethostname()
      email_msg = ERROR_EMAIL_MSG_FORMAT % (dir_entry, error_msg)
      email_manager.manager.send_email(NOTIFY_ADDRESS, email_subject,
                                       email_msg)
      logging.error(email_msg)
      logging.error('Stdout:\n%s \nStderr:\n%s', stdout_file.read(),
                    stderr)

    stdout_file.close()
    stderr_file.close()


def offloading_thread(queue):
  """
  Thread that continuously pulls arguments to |offload_dir| from the queue
  and calls |offload_dir| with them.

  @param queue A thread-safe queue of arguments to |offload_dir|.
  @return NEVER!
  """
  while True:
    try:
      args = queue.get()
      offload_dir(*args)
    except Exception as e:
      logging.debug(str(e))
    finally:
      queue.task_done()


def offload_files(results_dir, process_all, process_hosts_only, threads):
  """
  Offload files to Google Storage or the RSYNC_HOST_PATH host if USE_RSYNC is
  True.

  To ensure that the offloading times out properly we utilize a SIGALRM by
  assigning a simple function, timeout_handler, to be called if the SIGALRM is
  raised. timeout_handler will raise an exception that we can catch so that we
  know the timeout has occured and can react accordingly.

  @param results_dir: The Autotest results dir to look for dirs to offload.
  @param process_all: Indicates whether or not we want to process all the
                      files in results or just the larger test job files.
  @param process_hosts_only: Indicates whether we only want to process files
                             in the hosts subdirectory.
  @param threads The number of uploading threads to kick off.
  """
  # Nice our process (carried to subprocesses) so we don't kill the system.
  os.nice(NICENESS)
  logging.debug('Set process to nice value: %d', NICENESS)
  # os.listdir returns relative paths, so change to where we need to be to avoid
  # an os.path.join on each loop.
  os.chdir(results_dir)
  logging.debug('Looking for Autotest results in %s', results_dir)
  # Only pick up directories of the form <job #>-<job user>.
  job_matcher = re.compile('^\d+-\w+')
  signal.signal(signal.SIGALRM, timeout_handler)

  # Create a work queue with a buffers space equal to the number of threads.
  # This is done so that emptying out the queue won't take long for a graceful
  # exit, and so that if we have many results, we don't consume huge amounts of
  # memory.
  queue = Queue.Queue(maxsize=threads)
  threadpool = []
  for i in range(0, threads):
    thread = threading.Thread(target=offloading_thread, args=(queue,))
    thread.start()
    threadpool.append(thread)

  while True:
    if process_hosts_only:
      # Only offload the hosts/ sub directory.
      offload_hosts_sub_dir(queue)
      continue
    # Iterate over all directories in results_dir.
    for dir_entry in os.listdir('.'):
      logging.debug('Processing %s', dir_entry)
      if dir_entry == HOSTS_SUB_DIR and process_all:
        offload_hosts_sub_dir(queue)
        continue
      if not job_matcher.match(dir_entry):
        logging.debug('Skipping dir %s', dir_entry)
        continue
      # Directory names are in the format of <job #>-<job user>. We want just
      # the job # to see if it has completed.
      job_id = os.path.basename(dir_entry).split('-')[0]
      if not is_job_complete.is_job_complete(job_id):
        logging.debug('Job %s is not yet complete; skipping.', dir_entry)
        continue
      if (job_matcher.match(dir_entry) and os.path.isdir(dir_entry)):
        # The way we collect results currently is naive and results in a lot
        # of extra data collection. Clear these for now until we can be more
        # exact about what logs we care about. crosbug.com/26784.
        # logging.debug('Cleaning %s of extra data.', dir_entry)
        # os.system(CLEAN_CMD % dir_entry)
        # TODO(scottz): Monitor offloading and make sure chrome logs are
        # no longer an issue.
        queue.put((dir_entry,))
    queue.join()
    time.sleep(SLEEP_TIME_SECS)


def parse_options():
  """
  Parse the args passed into gs_offloader.
  """
  defaults = 'Defaults:\n  Destination: %s\n  Results Path: %s' % (GS_URI,
                                                                   RESULTS_DIR)
  usage = 'usage: %prog [options]\n' + defaults
  parser = OptionParser(usage)
  parser.add_option('-a', '--all', dest='process_all', action='store_true',
                    help='Offload all files in the results directory.')
  parser.add_option('-s', '--hosts', dest='process_hosts_only',
                    action='store_true',
                    help='Offload only the special tasks result files located'
                         'in the results/hosts subdirectory')
  parser.add_option('-t', '--threads', dest='threads', type='int',
                    default=1, help='Number of threads to use.')
  options = parser.parse_args()[0]
  if options.process_all and options.process_hosts_only:
    parser.print_help()
    print ('Cannot process all files and only the hosts subdirectory. '
           'Please remove an argument.')
    sys.exit(1)
  return options


def main():
  options = parse_options()
  log_filename = time.strftime(LOG_FILENAME_FORMAT)
  logging.basicConfig(filename=log_filename, level=logging.DEBUG,
                      format=LOGGING_FORMAT)
  offload_files(RESULTS_DIR, options.process_all, options.process_hosts_only,
                options.threads)


if __name__ == '__main__':
  main()
