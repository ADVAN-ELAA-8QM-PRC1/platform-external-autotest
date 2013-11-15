#!/usr/bin/python

"""Unit tests for the perf_uploader.py module.

"""

import json, unittest

import common
from autotest_lib.tko import models as tko_models
from autotest_lib.tko.perf_upload import perf_uploader


class test_aggregate_iterations(unittest.TestCase):
    """Tests for the aggregate_iterations function."""

    _PERF_ITERATION_DATA = {
        '1': [
            {
                'description': 'metric1',
                'value': 1,
                'stddev': 0.0,
                'units': 'units1',
                'higher_is_better': True,
                'graph':None
            },
            {
                'description': 'metric2',
                'value': 10,
                'stddev': 0.0,
                'units': 'units2',
                'higher_is_better': True,
                'graph':None,
            },
            {
                'description': 'metric3',
                'value': 100,
                'stddev': 1.7,
                'units': 'units3',
                'higher_is_better': False,
                'graph':None,
            }
        ],
        '2': [
            {
                'description': 'metric1',
                'value': 2,
                'stddev': 0.0,
                'units': 'units1',
                'higher_is_better': True,
                'graph':None,
            },
            {
                'description': 'metric2',
                'value': 20,
                'stddev': 0.0,
                'units': 'units2',
                'higher_is_better': True,
                'graph':None,
            },
            {
                'description': 'metric3',
                'value': 200,
                'stddev': 21.2,
                'units': 'units3',
                'higher_is_better': False,
                'graph':None,
            }
        ],
    }


    def setUp(self):
        """Sets up for each test case."""
        self._perf_values = []
        for iter_num, iter_data in self._PERF_ITERATION_DATA.iteritems():
            self._perf_values.append(
                    tko_models.perf_value_iteration(iter_num, iter_data))


    def test_one_iteration(self):
        """Tests that data for 1 iteration is aggregated properly."""
        result = perf_uploader._aggregate_iterations([self._perf_values[0]])
        self.assertEqual(len(result), 3, msg='Expected results for 3 metrics.')
        self.assertTrue(
            all([x in result for x in ['metric1', 'metric2', 'metric3']]),
            msg='Parsed metrics not as expected.')
        msg = 'Perf values for metric not aggregated properly.'
        self.assertEqual(result['metric1']['value'], [1], msg=msg)
        self.assertEqual(result['metric2']['value'], [10], msg=msg)
        self.assertEqual(result['metric3']['value'], [100], msg=msg)
        msg = 'Standard deviation values not retained properly.'
        self.assertEqual(result['metric1']['stddev'], 0.0, msg=msg)
        self.assertEqual(result['metric2']['stddev'], 0.0, msg=msg)
        self.assertEqual(result['metric3']['stddev'], 1.7, msg=msg)


    def test_two_iterations(self):
        """Tests that data for 2 iterations is aggregated properly."""
        result = perf_uploader._aggregate_iterations(self._perf_values)
        self.assertEqual(len(result), 3, msg='Expected results for 3 metrics.')
        self.assertTrue(
            all([x in result for x in ['metric1', 'metric2', 'metric3']]),
            msg='Parsed metrics not as expected.')
        msg = 'Perf values for metric not aggregated properly.'
        self.assertEqual(result['metric1']['value'], [1, 2], msg=msg)
        self.assertEqual(result['metric2']['value'], [10, 20], msg=msg)
        self.assertEqual(result['metric3']['value'], [100, 200], msg=msg)


class test_compute_avg_stddev(unittest.TestCase):
    """Tests for the compute_avg_stddev function."""

    def setUp(self):
        """Sets up for each test case."""
        self._perf_values = {
            'metric1': {'value': [10, 20, 30], 'stddev': 0.0},
            'metric2': {'value': [2.0, 3.0, 4.0], 'stddev': 0.0},
            'metric3': {'value': [1], 'stddev': 1.7},
        }


    def test_avg_stddev(self):
        """Tests that averages and standard deviations are computed properly."""
        perf_uploader._compute_avg_stddev(self._perf_values)
        result = self._perf_values  # The input dictionary itself is modified.
        self.assertEqual(len(result), 3, msg='Expected results for 3 metrics.')
        self.assertTrue(
            all([x in result for x in ['metric1', 'metric2', 'metric3']]),
            msg='Parsed metrics not as expected.')
        msg = 'Average value not computed properly.'
        self.assertEqual(result['metric1']['value'], 20, msg=msg)
        self.assertEqual(result['metric2']['value'], 3.0, msg=msg)
        self.assertEqual(result['metric3']['value'], 1, msg=msg)
        msg = 'Standard deviation value not computed properly.'
        self.assertEqual(result['metric1']['stddev'], 10.0, msg=msg)
        self.assertEqual(result['metric2']['stddev'], 1.0, msg=msg)
        self.assertEqual(result['metric3']['stddev'], 1.7, msg=msg)


class test_json_config_file_sanity(unittest.TestCase):
    """Sanity tests for the JSON-formatted presentation config file."""

    def test_proper_json(self):
        """Verifies the file can be parsed as proper JSON."""
        try:
            with open(perf_uploader._PRESENTATION_CONFIG_FILE, 'r') as fp:
                json.load(fp)
        except:
            self.fail('Presentation config file could not be parsed as JSON.')


    def test_unique_test_names(self):
        """Verifies that each test name appears only once in the JSON file."""
        json_obj = []
        try:
            with open(perf_uploader._PRESENTATION_CONFIG_FILE, 'r') as fp:
                json_obj = json.load(fp)
        except:
            self.fail('Presentation config file could not be parsed as JSON.')

        name_set = set([x['autotest_name'] for x in json_obj])
        self.assertEqual(len(name_set), len(json_obj),
                         msg='Autotest names not unique in the JSON file.')


class test_gather_presentation_info(unittest.TestCase):
    """Tests for the gather_presentation_info function."""

    _PRESENT_INFO = {
        'test_name': {
            'master_name': 'new_master_name',
            'dashboard_test_name': 'new_test_name',
        }
    }


    def test_test_name_specified(self):
        """Verifies gathers presentation info correctly."""
        result = perf_uploader._gather_presentation_info(
                self._PRESENT_INFO, 'test_name')
        self.assertTrue(
                all([key in result for key in
                     ['test_name', 'master_name']]),
                msg='Unexpected keys in resulting dictionary: %s' % result)
        self.assertEqual(result['master_name'], 'new_master_name',
                         msg='Unexpected "master_name" value: %s' %
                             result['master_name'])
        self.assertEqual(result['test_name'], 'new_test_name',
                         msg='Unexpected "test_name" value: %s' %
                             result['test_name'])


    def test_test_name_not_specified(self):
        """Verifies gathers default presentation info if test is not there."""
        result = perf_uploader._gather_presentation_info(
                self._PRESENT_INFO, 'other_test_name')
        self.assertTrue(
                all([key in result for key in
                     ['test_name', 'master_name']]),
                msg='Unexpected keys in resulting dictionary: %s' % result)
        self.assertEqual(result['master_name'],
                         perf_uploader._DEFAULT_MASTER_NAME,
                         msg='Unexpected "master_name" value: %s' %
                             result['master_name'])
        self.assertEqual(result['test_name'], 'other_test_name',
                         msg='Unexpected "test_name" value: %s' %
                             result['test_name'])


class test_format_for_upload(unittest.TestCase):
    """Tests for the format_for_upload function."""

    _PERF_DATA = {
        'metric1': {
            'value': 2.7,
            'stddev': 0.2,
            'units': 'msec',
            'graph': 'graph_name',
        },
        'metric2': {
            'value': 101.35,
            'stddev': 5.78,
            'units': 'frames_per_sec',
            'graph': None,
        },
    }

    _PRESENT_INFO_DEFAULT = {
        'master_name': perf_uploader._DEFAULT_MASTER_NAME,
        'test_name': 'test_name',
    }

    _PRESENT_INFO = {
        'master_name': 'new_master_name',
        'test_name': 'new_test_name',
    }


    def setUp(self):
        self._perf_data = self._PERF_DATA


    def _verify_result_string(self, actual_result, expected_result):
        """Verifies a JSON string matches the expected result.

        This function compares JSON objects rather than strings, because of
        possible floating-point values that need to be compared using
        assertAlmostEqual().

        @param actual_result: The candidate JSON string.
        @param expected_result: The reference JSON string that the candidate
            must match.

        """
        actual = json.loads(actual_result)
        expected = json.loads(expected_result)

        fail_msg = 'Unexpected result string: %s' % actual_result
        self.assertEqual(len(actual), len(expected), msg=fail_msg)
        for idx in xrange(len(actual)):
            keys_actual = set(actual[idx].keys())
            keys_expected = set(expected[idx].keys())
            self.assertEqual(len(keys_actual), len(keys_expected),
                             msg=fail_msg)
            self.assertTrue(all([key in keys_actual for key in keys_expected]),
                            msg=fail_msg)

            self.assertEqual(
                    actual[idx]['supplemental_columns']['r_cros_version'],
                    expected[idx]['supplemental_columns']['r_cros_version'],
                    msg=fail_msg)
            self.assertEqual(
                    actual[idx]['supplemental_columns']['r_chrome_version'],
                    expected[idx]['supplemental_columns']['r_chrome_version'],
                    msg=fail_msg)
            self.assertEqual(
                    actual[idx]['bot'], expected[idx]['bot'], msg=fail_msg)
            self.assertAlmostEqual(
                    actual[idx]['value'], expected[idx]['value'], 4,
                    msg=fail_msg)
            self.assertEqual(
                    actual[idx]['units'], expected[idx]['units'], msg=fail_msg)
            self.assertEqual(
                    actual[idx]['master'], expected[idx]['master'],
                    msg=fail_msg)
            self.assertAlmostEqual(
                    actual[idx]['error'], expected[idx]['error'], 4,
                    msg=fail_msg)
            self.assertEqual(
                    actual[idx]['test'], expected[idx]['test'], msg=fail_msg)


    def test_default_presentation(self):
        """Verifies default presentation settings with empty config info."""
        result = perf_uploader._format_for_upload(
                'platform', '1200.0.0', '25.10.0.0', self._perf_data,
                self._PRESENT_INFO_DEFAULT)
        expected_result_string = (
                '[{"supplemental_columns": {"r_cros_version": "1200.0.0", '
                '"r_chrome_version": "25.10.0.0"}, "bot": "cros-platform", '
                '"value": 101.35, "units": "frames_per_sec", "master": '
                '"ChromeOSPerf", "error": 5.78, "test": "test_name/metric2"}, '
                '{"supplemental_columns": {"r_cros_version": "1200.0.0", '
                '"r_chrome_version": "25.10.0.0"}, "bot": "cros-platform", '
                '"value": 2.7, "units": "msec", "master": "ChromeOSPerf", '
                '"error": 0.2, "test": "test_name/graph_name/metric1"}]')
        self._verify_result_string(result['data'], expected_result_string)


    def test_overridden_presentation(self):
        """Verifies presentation settings can override defaults properly."""
        result = perf_uploader._format_for_upload(
                'platform', '1200.0.0', '25.10.0.0',
                self._perf_data, self._PRESENT_INFO)
        expected_result_string = (
                '[{"supplemental_columns": {"r_cros_version": "1200.0.0", '
                '"r_chrome_version": "25.10.0.0"}, "bot": "cros-platform", '
                '"value": 101.35, "units": "frames_per_sec", "master": '
                '"new_master_name", "error": 5.78, "test": '
                '"new_test_name/metric2"}, '
                '{"supplemental_columns": {"r_cros_version": "1200.0.0", '
                '"r_chrome_version": "25.10.0.0"}, "bot": "cros-platform", '
                '"value": 2.7, "units": "msec", "master": "new_master_name", '
                '"error": 0.2, "test": "new_test_name/graph_name/metric1"}]')
        self._verify_result_string(result['data'], expected_result_string)


if __name__ == '__main__':
    unittest.main()
