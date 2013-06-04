#!/usr/bin/python

# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
import logging

import common

import httplib2
from chromite.lib import gdata_lib

try:
  from apiclient.discovery import build as apiclient_build
  from apiclient import errors as apiclient_errors
  from oauth2client import file as oauth_client_fileio
except ImportError as e:
  apiclient_build = None
  logging.info("API client for bug filing disabled. %s", e)


class ProjectHostingApiException(Exception):
    """
    Raised when an api call fails, since the actual
    HTTP error can be cryptic.
    """


class Issue(gdata_lib.Issue):
    """
    Class representing an Issue and it's related metadata.
    """
    def __init__(self, t_issue):
        """
        Initialize |self| from tracker issue |t_issue|

        @param t_issue: The base issue we want to use to populate
                        the member variables of this object.
        """
        kwargs={}
        kwargs.update((keys, t_issue.get(keys))
                      for keys in gdata_lib.Issue.SlotDefaults.keys())

        super(Issue, self).__init__(**kwargs)

        # The value keyed under 'summary' in the tracker issue
        # is, unfortunately, not the summary but the title. The
        # actual summary is the update at index 0.
        self.summary = t_issue.get('updates')[0]
        self.comments = t_issue.get('updates')[1:]


class ProjectHostingApiClient():
    """
    Client class for interaction with the project hosting api.
    """

    # Maximum number of results we would like when qurying the tracker.
    _max_results_for_issue = 50


    def __init__(self, oauth_credentials, project_name):
        if apiclient_build is None:
            logging.error('Cannot get apiclient library.')
            return None

        storage = oauth_client_fileio.Storage(oauth_credentials)
        credentials = storage.get()
        if credentials is None or credentials.invalid:
            logging.error('Invalid credentials for ProjectHostingClient api. '
                          'Cannot file bugs.')
            return None

        http = credentials.authorize(httplib2.Http())
        self._codesite_service = apiclient_build('projecthosting',
                                                 'v2', http=http)
        self._project_name = project_name


    def _execute_request(self, request):
        """
        Executes an api request.

        @param request: An apiclient.http.HttpRequest object representing the
                        request to be executed.
        @raises: ProjectHostingApiException if we fail to execute the request.
                 This could happen if we receive an http response that is not a
                 2xx, or if the http object itself encounters an error.

        @return: A deserialized object model of the response body returned for
                 the request.
        """
        try:
            return request.execute()
        except (apiclient_errors.Error, httplib2.HttpLib2Error) as e:
            msg = 'Unable to execute your request: %s'
            raise ProjectHostingApiException(msg % e)


    def _get_field(self, field):
        """
        Gets a field from the project.

        This method directly queries the project hosting API using bugdroids1's,
        api key.

        @param field: A selector, which corresponds loosely to a field in the
                      new bug description of the crosbug frontend.
        @raises: ProjectHostingApiException, if the request execution fails.

        @return: A json formatted python dict of the specified field's options,
                 or None if we can't find the api library. This dictionary
                 represents the javascript literal used by the front end tracker
                 and can hold multiple filds.

                The returned dictionary follows a template, but it's structure
                is only loosely defined as it needs to match whatever the front
                end describes via javascript.
                For a new issue interface which looks like:

                field 1: text box
                              drop down: predefined value 1 = description
                                         predefined value 2 = description
                field 2: text box
                              similar structure as field 1

                you will get a dictionary like:
                {
                    'field name 1': {
                        'project realted config': 'config value'
                        'property': [
                            {predefined value for property 1, description},
                            {predefined value for property 2, description}
                        ]
                    },

                    'field name 2': {
                        similar structure
                    }
                    ...
                }
        """
        project = self._codesite_service.projects()
        request = project.get(projectId=self._project_name,
                              fields=field)
        return self._execute_request(request)


    def _list_updates(self, issue_id):
        """
        Retrieve all updates for a given issue including comments, changes to
        it's labels, status etc. The first element in the dictionary returned
        by this method, is by default, the 0th update on the bug; which is the
        entry that created it. All the text in a given update is keyed as
        'content', and updates that contain no text, eg: a change to the status
        of a bug, will contain the emtpy string instead.

        @param issue_id: The id of the issue we want detailed information on.
        @raises: ProjectHostingApiException, if the request execution fails.

        @return: A json formatted python dict that has an entry for each update
                 performed on this issue.
        """
        issue_comments = self._codesite_service.issues().comments()
        request = issue_comments.list(projectId=self._project_name,
                                      issueId=issue_id,
                                      maxResults=self._max_results_for_issue)
        return self._execute_request(request)


    def _list_issues(self, search_marker):
        """
        List issues containing the search marker. This method will only list
        the summary, title and id of an issue, though it searches through the
        comments. Eg: if we're searching for the marker '123', issues that
        contain a comment of '123' will appear in the output, but the string
        '123' itself may not, because the output only contains issue summaries.

        @param search_marker: The anchor string used in the search.
        @raises: ProjectHostingApiException, if the request execution fails.

        @return: A json formatted python dict of all matching issues.
        """
        issues = self._codesite_service.issues()
        request = issues.list(projectId=self._project_name,
                              q=search_marker,
                              maxResults=self._max_results_for_issue)
        return self._execute_request(request)


    def _get_property_values(self, prop_dict):
        """
        Searches a dictionary as returned by _get_field for property lists,
        then returns each value in the list. Effectively this gives us
        all the accepted values for a property. For example, in crosbug,
        'properties' map to things like Status, Labels, Owner etc, each of these
        will have a list within the issuesConfig dict.

        @param prop_dict: dictionary which contains a list of properties.
        @yield: each value in a property list. This can be a dict or any other
                type of datastructure, the caller is responsible for handling
                it correctly.
        """
        for name, property in prop_dict.iteritems():
            if isinstance(property, list):
                for values in property:
                    yield values


    def _get_cros_labels(self, prop_dict):
        """
        Helper function to isolate labels from the labels dictionary. This
        dictionary is of the form:
            {
                "label": "Cr-OS-foo",
                "description": "description"
            },
        And maps to the frontend like so:
            Labels: Cr-???
                    Cr-OS-foo = description
        where Cr-OS-foo is a conveniently predefined value for Label Cr-OS-???.

        @param prop_dict: a dictionary we expect the Cros label to be in.
        @return: A lower case product area, eg: video, factory, ui.
        """
        label = prop_dict.get('label')
        if label and 'Cr-OS-' in label:
            return label.split('Cr-OS-')[1]


    def get_areas(self):
        """
        Parse issue options and return a list of 'Cr-OS' labels.

        @return: a list of Cr-OS labels from crosbug, eg: ['kernel', 'systems']
        """
        if apiclient_build is None:
            logging.error('Missing Api-client import. Cannot get area-labels.')
            return []

        try:
            issue_options_dict = self._get_field('issuesConfig')
        except ProjectHostingApiException as e:
            logging.error('Unable to determine area labels: %s', str(e))
            return []

        # Since we can request multiple fields at once we need to
        # retrieve each one from the field options dictionary, even if we're
        # really only asking for one field.
        issue_options = issue_options_dict.get('issuesConfig')
        if issue_options is None:
            logging.error('The IssueConfig field does not contain issue '
                          'configuration as a member anymore; The project '
                          'hosting api might have changed.')
            return []

        return filter(None, [self._get_cros_labels(each)
                      for each in self._get_property_values(issue_options)
                      if isinstance(each, dict)])


    def _populate_issue_updates(self, t_issue):
        """
        Populates a tracker issue with updates.

        Any issue is useless without it's updates, since the updates will
        contain both the summary and the comments. We need at least one of
        those to successfully dedupe. The Api doesn't allow us to grab all this
        information in one shot because viewing the comments on an issue
        requires more authority than just viewing it's title.

        @param t_issue: The basic tracker issue, to populate with updates.
        @raises: ProjectHostingApiException, if request execution fails.

        @returns: A tracker issue, with it's updates.
        """
        updates = self._list_updates(t_issue['id'])
        t_issue['updates'] = [update['content'] for update in
                              self._get_property_values(updates)
                              if update.get('content')]
        return t_issue


    def get_tracker_issues_by_text(self, search_text, full_text=True,
                                  only_open=True):
        """
        Find all Tracker issues that contain the specified search text.

        @param search_text: Anchor text to use in the search.
        @param full_text: True if we would like an extensive search through
                          issue comments. If False the search will be restricted
                          to just summaries and titles.
        @param only_open: Only search over all open issues if True.

        @return: A list of issues that contain the search text, or an empty list
                 when we're either unable to list issues or none match the text.
        """
        issue_list = []
        try:
            feed = self._list_issues(search_text)
        except ProjectHostingApiException as e:
            logging.error('Unable to search for issues with marker %s: %s',
                          search_text, e)
            return issue_list

        for t_issue in self._get_property_values(feed):

            # All valid issues will have an issue id we can use to retrieve
            # more information about it. If we encounter a failure mode that
            # returns a bad Http response code but doesn't throw an exception
            # we won't find an issue id in the returned json.
            if t_issue.get('id'):

                # TODO(beeps): If this method turns into a performance bottle
                # neck yield each issue and refactor the reporter. For now
                # passing all issues allows us to detect when deduping fails
                # because multiple issues will match a given query exactly.
                try:
                    issue_list.append(
                        Issue(self._populate_issue_updates(t_issue)))
                except ProjectHostingApiException as e:
                    logging.error('Unable to list the updates of issue %s: %s',
                                   t_issue['id'], str(e))
        return issue_list
