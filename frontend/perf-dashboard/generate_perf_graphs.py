#!/usr/bin/env python
# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Parses perf data files and creates chrome-based graph files from that data.

This script assumes that extract_perf.py was previously run to extract perf
test data from a database and then dump it into local text data files.  This
script then parses the extracted perf data files and creates new data files that
can be directly read in by chrome's perf graphing infrastructure to display
perf graphs.

This script also generates a set of Javascript/HTML overview pages that present
birds-eye overviews of multiple perf graphs simultaneously.

Sample usage:
  python generate_perf_graphs.py -c -v

Run with -h to see the full set of command-line options.
"""

import fnmatch
import logging
import math
import optparse
import os
import re
import shutil
import simplejson
import sys

_SETTINGS = 'autotest_lib.frontend.settings'
os.environ['DJANGO_SETTINGS_MODULE'] = _SETTINGS

import common
from django.shortcuts import render_to_response

# Paths to files.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DATA_DIR = os.path.join(_SCRIPT_DIR, 'data')
_CURR_PID_FILE = os.path.join(_DATA_DIR, __file__ + '.curr_pid.txt')
_CHART_CONFIG_FILE = os.path.join(_SCRIPT_DIR, 'croschart_defaults.json')
_TEMPLATE_DIR = os.path.join(_SCRIPT_DIR, 'templates')

_GRAPH_DIR = os.path.join(_SCRIPT_DIR, '..', 'graphs')
_GRAPH_DATA_DIR = os.path.join(_GRAPH_DIR, 'data')
_COMPLETED_ID_FILE = os.path.join(_GRAPH_DATA_DIR, 'job_id_complete.txt')
_REV_NUM_FILE = os.path.join(_GRAPH_DATA_DIR, 'rev_num.txt')

# Values that can be configured through options.
# TODO(dennisjeffrey): Infer the tip-of-tree milestone dynamically once this
# issue is addressed: crosbug.com/38564.
_TOT_MILESTONE = 26
_OLDEST_MILESTONE_TO_GRAPH = 23

# Other values that can only be configured here in the code.
_SYMLINK_LIST = [
    ('report.html',   '../../../../ui/cros_plotter.html'),
    ('js',            '../../../../ui/js'),
]


def set_world_read_permissions(path):
    """Recursively sets the content of |path| to be world-readable.

     @param path: The string path.
    """
    logging.debug('Setting world-read permissions recursively on %s', path)
    os.chmod(path, 0755)
    for root, dirs, files in os.walk(path):
        for d in dirs:
            dname = os.path.join(root, d)
            if not os.path.islink(dname):
                os.chmod(dname, 0755)
        for f in files:
            fname = os.path.join(root, f)
            if not os.path.islink(fname):
                os.chmod(fname, 0755)


def remove_path(path):
  """Remove the given path (whether file or directory).

  @param path: The string path.
  """
  if os.path.isdir(path):
      shutil.rmtree(path)
      return
  try:
      os.remove(path)
  except OSError:
      pass


def symlink_force(link_name, target):
    """Create a symlink, accounting for different situations.

    @param link_name: The string name of the link to create.
    @param target: The string destination file to which the link should point.
    """
    try:
        os.unlink(link_name)
    except EnvironmentError:
        pass
    try:
        os.symlink(target, link_name)
    except OSError:
        remove_path(link_name)
        os.symlink(target, link_name)


def mean_and_standard_deviation(data):
    """Compute the mean and standard deviation of a list of numbers.

    @param data: A list of numerica values.

    @return A 2-tuple (mean, standard_deviation) computed from |data|.
    """
    n = len(data)
    if n == 0:
        return 0.0, 0.0
    mean = float(sum(data)) / n
    if n == 1:
        return mean, 0.0
    # Divide by n-1 to compute "sample standard deviation".
    variance = sum([(element - mean) ** 2 for element in data]) / (n - 1)
    return mean, math.sqrt(variance)


def get_release_from_jobname(jobname):
    """Identifies the release number components from an autotest job name.

    For example:
        'lumpy-release-R21-2384.0.0_pyauto_perf' becomes (21, 2384, 0, 0).

    @param jobname: The string name of an autotest job.

    @return The 4-tuple containing components of the build release number, or
        None if those components cannot be identifies from the |jobname|.
    """
    prog = re.compile('r(\d+)-(\d+).(\d+).(\d+)')
    m = prog.search(jobname.lower())
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)),
                int(m.group(4)))
    return None


def is_on_mainline_of_milestone(jobname, milestone):
    """Determines whether an autotest build is on mainline of a given milestone.

    @param jobname: The string name of an autotest job (containing release
        number).
    @param milestone: The integer milestone number to consider.

    @return True, if the given autotest job name is for a release number that
        is either (1) an ancestor of the specified milestone, or (2) is on the
        main branch line of the given milestone.  Returns False otherwise.
    """
    r = get_release_from_jobname(jobname)
    m = milestone
    # Handle garbage data that might exist.
    if any(item < 0 for item in r):
        raise Exception('Unexpected release info in job name: %s' % jobname)
    if m == r[0]:
        # Yes for jobs from the specified milestone itself.
        return True
    if r[0] < m and r[2] == 0 and r[3] == 0:
        # Yes for jobs from earlier milestones that were before their respective
        # branch points.
        return True
    return False


# TODO(dennisjeffrey): Determine whether or not we need all the values in the
# config file.  Remove unnecessary ones and revised necessary ones as needed.
def create_config_js_file(path, test_name):
    """Creates a configuration file used by the performance graphs.

    @param path: The string path to the directory in which to create the file.
    @param test_name: The string name of the test associated with this config
        file.
    """
    config_content = render_to_response(
        os.path.join(_TEMPLATE_DIR, 'config.js'), locals()).content
    with open(os.path.join(path, 'config.js'), 'w') as f:
        f.write(config_content)


def output_graph_data_for_entry(test_name, graph_name, job_name, platform,
                                units, better_direction, url, perf_keys,
                                chart_keys, options, summary_id_to_rev_num):
    """Outputs data for a perf test result into appropriate graph data files.

    @param test_name: The string name of a test.
    @param graph_name: The string name of the graph associated with this result.
    @param job_name: The string name of the autotest job associated with this
        test result.
    @param platform: The string name of the platform associated with this test
        result.
    @param units: The string name of the units displayed on this graph.
    @param better_direction: A String representing whether better perf results
        are those that are "higher" or "lower".
    @param url: The string URL of a webpage docuementing the current graph.
    @param perf_keys: A list of 2-tuples containing perf keys measured by the
        test, where the first tuple element is a string key name, and the second
        tuple element is the associated numeric perf value.
    @param chart_keys: A list of perf key names that need to be displayed in
        the current graph.
    @param options: An optparse.OptionParser options object.
    @param summary_id_to_rev_num: A dictionary mapping a string (representing
        a test/platform/release combination), to the next integer revision
        number to use in the graph data file.
    """
    # A string ID that is assumed to be unique across all charts.
    test_id = test_name + '__' +  graph_name

    release_num = get_release_from_jobname(job_name)
    if not release_num:
        logging.warning('Could not obtain release number for job name: %s',
                        job_name)
        return
    build_num = '%d.%d.%d.%d' % (release_num[0], release_num[1], release_num[2],
                                 release_num[3])

    # Filter out particular test runs that we explicitly do not want to
    # consider.
    # TODO(dennisjeffrey): Figure out a way to eliminate the need for these
    # special checks: crosbug.com/36685.
    if test_name == 'platform_BootPerfServer' and 'perfalerts' not in job_name:
        # Skip platform_BootPerfServer test results that do not come from the
        # "perfalerts" runs.
        return

    # Consider all releases for which this test result may need to be included
    # on a graph.
    start_release = max(release_num[0], options.oldest_milestone)
    for release in xrange(start_release, options.tot_milestone + 1):
        output_path = os.path.join(_GRAPH_DATA_DIR, 'r%d' % release, platform,
                                   test_id)
        summary_file = os.path.join(output_path, graph_name + '-summary.dat')

        # Set up the output directory if it doesn't already exist.
        if not os.path.exists(output_path):
            os.makedirs(output_path)

            # Create auxiliary files.
            create_config_js_file(output_path, test_name)
            open(summary_file, 'w').close()
            graphs = [{
              'name': graph_name,
              'units': units,
              'better_direction': better_direction,
              'info_url': url,
              'important': False,
            }]
            with open(os.path.join(output_path, 'graphs.dat'), 'w') as f:
                f.write(simplejson.dumps(graphs, indent=2))

            # Add symlinks to the plotting code.
            for slink, target in _SYMLINK_LIST:
                slink = os.path.join(output_path, slink)
                symlink_force(slink, target)

        # Write data to graph data file if it belongs in the current release.
        if is_on_mainline_of_milestone(job_name, release):
            entry = {}
            entry['traces'] = {}
            entry['ver'] = build_num

            key_to_vals = {}
            for perf_key in perf_keys:
                if perf_key[0] in chart_keys:
                    # Replace dashes with underscores so different lines show
                    # up as different colors in the graphs.
                    key = perf_key[0].replace('-', '_')
                    if key not in key_to_vals:
                        key_to_vals[key] = []
                    # There are some cases where results for
                    # platform_BootPerfServer are negative in reboot/shutdown
                    # times. Ignore these negative values.
                    if float(perf_key[1]) < 0.0:
                        continue
                    key_to_vals[key].append(perf_key[1])
            for key in key_to_vals:
                if len(key_to_vals[key]) == 1:
                    entry['traces'][key] = [key_to_vals[key][0], '0.0']
                else:
                    mean, std_dev = mean_and_standard_deviation(
                        map(float, key_to_vals[key]))
                    entry['traces'][key] = [str(mean), str(std_dev)]

            if entry['traces']:
                summary_id = '%s|%s|%s' % (test_id, platform, release)

                rev = summary_id_to_rev_num.get(summary_id, 0)
                summary_id_to_rev_num[summary_id] = rev + 1
                entry['rev'] = rev

                with open(summary_file, 'a') as f:
                    f.write(simplejson.dumps(entry) + '\n')


def process_perf_data_file(file_name, test_name, completed_ids,
                           test_name_to_charts, options, summary_id_to_rev_num):
    """Processes a single perf data file to convert into graphable format.

    @param file_name: The string name of the perf data file to process.
    @param test_name: The string name of the test associated with the file name
        to process.
    @param completed_ids: A dictionary of already-processed job IDs.
    @param test_name_to_charts: A dictionary mapping test names to a list of
        dictionaries, in which each dictionary contains information about a
        chart associated with the given test name.
    @param options: An optparse.OptionParser options object.
    @param summary_id_to_rev_num: A dictionary mapping a string (representing
        a test/platform/release combination) to an integer revision number.

    @return The number of newly-added graph data entries.
    """
    newly_added_count = 0
    with open(file_name, 'r') as fp:
        for line in fp.readlines():
            info = simplejson.loads(line.strip())
            job_id = info[0]
            job_name = info[1]
            platform = info[2]
            perf_keys = info[3]

            # Skip this job ID if it's already been processed.
            if job_id in completed_ids:
                continue

            # Scan the desired charts and see if we need to output the
            # current line info to a graph output file.
            for chart in test_name_to_charts[test_name]:
                graph_name = chart['graph_name']
                units = chart['units']
                better_direction = chart['better_direction']
                url = chart['info_url']
                chart_keys = chart['keys']

                store_entry = False
                for chart_key in chart_keys:
                    if chart_key in [x[0] for x in perf_keys]:
                        store_entry = True
                        break

                if store_entry:
                    output_graph_data_for_entry(
                        test_name, graph_name, job_name, platform,
                        units, better_direction, url, perf_keys,
                        chart_keys, options, summary_id_to_rev_num)

            # Mark this job ID as having been processed.
            with open(_COMPLETED_ID_FILE, 'a') as fp:
                fp.write(job_id + '\n')
            completed_ids[job_id] = True
            newly_added_count += 1

    return newly_added_count


def initialize_graph_dir(options):
    """Initialize/populate the directory that will serve the perf graphs.

    @param options: An optparse.OptionParser options object.
    """
    charts = simplejson.loads(open(_CHART_CONFIG_FILE, 'r').read())

    # Identify all the job IDs already processed in the graphs, so that we don't
    # add that data again.
    completed_ids = {}
    if os.path.exists(_COMPLETED_ID_FILE):
        with open(_COMPLETED_ID_FILE, 'r') as fp:
            job_ids = map(lambda x: x.strip(), fp.readlines())
            for job_id in job_ids:
                completed_ids[job_id] = True

    # Identify the next revision number to use in the graph data files for each
    # test/platform/release combination.
    summary_id_to_rev_num = {}
    if os.path.exists(_REV_NUM_FILE):
        with open(_REV_NUM_FILE, 'r') as fp:
            summary_id_to_rev_num = simplejson.loads(fp.read())

    test_name_to_charts = {}
    test_names = set()
    for chart in charts:
        if chart['test_name'] not in test_name_to_charts:
            test_name_to_charts[chart['test_name']] = []
        test_name_to_charts[chart['test_name']].append(chart)
        test_names.add(chart['test_name'])

    # Scan all database data and format/output only the new data specified in
    # the graph JSON file.
    newly_added_count = 0
    for i, test_name in enumerate(test_names):
        logging.debug('Analyzing/converting data for test %d of %d: %s',
                      i+1, len(test_names), test_name)

        test_data_dir = os.path.join(_DATA_DIR, test_name)
        if not os.path.exists(test_data_dir):
            logging.warning('No test data directory for test: %s', test_name)
            continue
        files = os.listdir(test_data_dir)
        for file_name in files:
            logging.debug('Processing perf platform data file: %s', file_name)
            newly_added_count += process_perf_data_file(
                os.path.join(test_data_dir, file_name), test_name,
                completed_ids, test_name_to_charts, options,
                summary_id_to_rev_num)

    # Store the latest revision numbers for each test/platform/release
    # combination, to be used on the next invocation of this script.
    with open(_REV_NUM_FILE, 'w') as fp:
        fp.write(simplejson.dumps(summary_id_to_rev_num, indent=2))

    logging.info('Added info for %d new jobs to the graphs!', newly_added_count)


def create_branch_platform_overview(graph_dir, branch, platform,
                                    branch_to_platform_to_test):
    """Create an overview webpage for the given branch/platform combination.

    @param graph_dir: The string directory containing the graphing files.
    @param branch: The string name of the milestone (branch).
    @param platform: The string name of the platform.
    @param branch_to_platform_to_test: A dictionary mapping branch names to
        another dictionary, which maps platform names to a list of test names.
    """
    branches = sorted(branch_to_platform_to_test.keys(), reverse=True)
    platform_to_tests = branch_to_platform_to_test[branch]
    platform_list = sorted(platform_to_tests)
    tests = []
    for test_id in sorted(platform_to_tests[platform]):
        has_data = False
        test_name = ''
        test_dir = os.path.join(graph_dir, 'data', branch, platform, test_id)
        data_file_names = fnmatch.filter(os.listdir(test_dir), '*-summary.dat')
        if len(data_file_names):
            txt_name = data_file_names[0]
            # The name of a test is of the form "X: Y", where X is the
            # autotest name and Y is the graph name.  For example:
            # "platform_BootPerfServer: seconds_from_kernel".
            test_name = (test_id[:test_id.find('__')] + ': ' +
                         txt_name[:txt_name.find('-summary.dat')])
            file_name = os.path.join(test_dir, txt_name)
            has_data = True if os.path.getsize(file_name) > 3 else False
        test_info = {
            'id': test_id,
            'name': test_name,
            'has_data': has_data
        }
        tests.append(test_info)

    # Special check for certain platforms.  Will be removed once we remove
    # all links to the old-style perf graphs.
    # TODO(dennisjeffrey): Simplify the below code once the following bug
    # is addressed to standardize the platform names: crosbug.com/38521.
    platform_converted = 'snow' if platform == 'daisy' else platform
    platform_converted_2 = ('x86-' + platform if platform in
                            ['alex', 'mario', 'zgb'] else platform)

    # Output the overview page.
    page_content = render_to_response(
        os.path.join(_TEMPLATE_DIR, 'branch_platform_overview.html'),
        locals()).content
    file_name = os.path.join(graph_dir, '%s-%s.html' % (branch, platform))
    with open(file_name, 'w') as f:
        f.write(page_content)


def create_comparison_overview(compare_type, graph_dir, test_id, test_dir,
                               branch_to_platform_to_test):
    """Create an overview webpage to compare a test by platform or by branch.

    @param compare_type: The string type of comaprison graph this is, either
        "platform" or "branch".
    @param graph_dir: The string directory containing the graphing files.
    @param test_id: The string unique ID for a test result.
    @param test_dir: The string directory name containing the test data.
    @param branch_to_platform_to_test: A dictionary mapping branch names to
        another dictionary, which maps platform names to a list of test names.
    """
    branches = sorted(branch_to_platform_to_test.keys())
    platforms = [x.keys() for x in branch_to_platform_to_test.values()]
    platforms = sorted(set([x for sublist in platforms for x in sublist]))

    autotest_name = test_id[:test_id.find('__')]

    text_file_names = fnmatch.filter(os.listdir(test_dir), '*-summary.dat')
    test_name = '???'
    if len(text_file_names):
        txt_name = text_file_names[0]
        test_name = txt_name[:txt_name.find('-summary.dat')]

    if compare_type == 'branch':
        outer_list_items = platforms
        inner_list_items = branches
        outer_item_type = 'platform'
    else:
        outer_list_items = reversed(branches)
        inner_list_items = platforms
        outer_item_type = 'branch'

    outer_list = []
    for outer_item in outer_list_items:
        inner_list = []
        for inner_item in inner_list_items:
            if outer_item_type == 'branch':
                branch = outer_item
                platform = inner_item
            else:
                branch = inner_item
                platform = outer_item
            has_data = False
            test_dir = os.path.join(graph_dir, 'data', branch, platform,
                                    test_id)
            if os.path.exists(test_dir):
                data_file_names = fnmatch.filter(os.listdir(test_dir),
                                                 '*-summary.dat')
                if len(data_file_names):
                    file_name = os.path.join(test_dir, data_file_names[0])
                    has_data = True if os.path.getsize(file_name) > 3 else False
            info = {
                'inner_item': inner_item,
                'outer_item': outer_item,
                'branch': branch,
                'platform': platform,
                'has_data': has_data
            }
            inner_list.append(info)
        outer_list.append(inner_list)

    # Output the overview page.
    page_content = render_to_response(
        os.path.join(_TEMPLATE_DIR, 'compare_by_overview.html'),
        locals()).content
    if compare_type == 'branch':
        file_name = os.path.join(graph_dir, test_id + '_branch.html')
    else:
        file_name = os.path.join(graph_dir, test_id + '_platform.html')
    with open(file_name, 'w') as f:
        f.write(page_content)


def generate_overview_pages(graph_dir, options):
    """Create static overview webpages for all the perf graphs.

    @param graph_dir: The string directory containing all the graph data.
    @param options: An optparse.OptionParser options object.
    """
    # Identify all the milestone names for which we want overview pages.
    branches_dir = os.path.join(graph_dir, 'data')
    branches = os.listdir(branches_dir)
    branches = sorted(branches)
    branches = [x for x in branches
                if os.path.isdir(os.path.join(branches_dir, x)) and
                int(x[1:]) >= options.oldest_milestone]

    unique_tests = set()
    unique_test_to_dir = {}
    branch_to_platform_to_test = {}

    for branch in branches:
        platforms_dir = os.path.join(branches_dir, branch)
        if not os.path.isdir(platforms_dir):
            continue
        platforms = os.listdir(platforms_dir)

        platform_to_tests = {}
        for platform in platforms:
            tests_dir = os.path.join(platforms_dir, platform)
            tests = os.listdir(tests_dir)

            for test in tests:
                test_dir = os.path.join(tests_dir, test)
                unique_tests.add(test)
                unique_test_to_dir[test] = test_dir

            platform_to_tests[platform] = tests

        branch_to_platform_to_test[branch] = platform_to_tests

    for branch in branch_to_platform_to_test:
        platforms = branch_to_platform_to_test[branch]
        for platform in platforms:
            # Create overview page for this branch/platform combination.
            create_branch_platform_overview(
                graph_dir, branch, platform, branch_to_platform_to_test)

    # Make index.html a symlink to the most recent branch.
    latest_branch = branches[-1]
    first_plat_for_branch = sorted(
        branch_to_platform_to_test[latest_branch].keys())[0]
    symlink_force(
        os.path.join(graph_dir, 'index.html'),
        '%s-%s.html' % (latest_branch, first_plat_for_branch))

    # Now create overview pages for each test that compare by platform and by
    # branch.
    for test_id in unique_tests:
        for compare_type in ['branch', 'platform']:
            create_comparison_overview(
                compare_type, graph_dir, test_id, unique_test_to_dir[test_id],
                branch_to_platform_to_test)


def cleanup():
    """Cleans up when this script is done."""
    if os.path.isfile(_CURR_PID_FILE):
        os.remove(_CURR_PID_FILE)


def main():
    """Main function."""
    parser = optparse.OptionParser()
    parser.add_option('-t', '--tot-milestone', metavar='MSTONE', type='int',
                      default=_TOT_MILESTONE,
                      help='Tip-of-tree (most recent) milestone number. '
                           'Defaults to milestone %default (R%default).')
    parser.add_option('-o', '--oldest-milestone', metavar='MSTONE', type='int',
                      default=_OLDEST_MILESTONE_TO_GRAPH,
                      help='Oldest milestone number to display in the graphs. '
                           'Defaults to milestone %default (R%default).')
    parser.add_option('-c', '--clean', action='store_true', default=False,
                      help='Clean/delete existing graph files and then '
                           're-create them from scratch.')
    parser.add_option('-v', '--verbose', action='store_true', default=False,
                      help='Use verbose logging.')
    options, _ = parser.parse_args()

    log_level = logging.DEBUG if options.verbose else logging.INFO
    logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s',
                        level=log_level)

    if not os.path.isdir(_DATA_DIR):
        logging.error('Could not find data directory "%s"', _DATA_DIR)
        logging.error('Did you forget to run extract_perf.py first?')
        sys.exit(1)

    common.die_if_already_running(_CURR_PID_FILE, logging)

    if options.clean:
      remove_path(_GRAPH_DIR)
      os.makedirs(_GRAPH_DATA_DIR)

    initialize_graph_dir(options)

    ui_dir = os.path.join(_GRAPH_DIR, 'ui')
    if not os.path.exists(ui_dir):
        logging.debug('Copying "ui" directory to %s', ui_dir)
        shutil.copytree(os.path.join(_SCRIPT_DIR, 'ui'), ui_dir)
    doc_dir = os.path.join(_GRAPH_DIR, 'doc')
    if not os.path.exists(doc_dir):
        logging.debug('Copying "doc" directory to %s', doc_dir)
        shutil.copytree(os.path.join(_SCRIPT_DIR, 'doc'), doc_dir)

    generate_overview_pages(_GRAPH_DIR, options)
    set_world_read_permissions(_GRAPH_DIR)

    cleanup()
    logging.info('All done!')


if __name__ == '__main__':
  main()
