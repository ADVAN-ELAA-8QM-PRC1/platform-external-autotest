# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from distutils import version
import logging
import urllib2
import HTMLParser
import cStringIO

from autotest_lib.client.common_lib import global_config
from autotest_lib.client.common_lib.cros import retry
# TODO(cmasone): redo this class using requests module; http://crosbug.com/30107


CONFIG = global_config.global_config
# This file is generated at build time and specifies, per suite and per test,
# the DEPENDENCIES list specified in each control file.  It's a dict of dicts:
# {'bvt':   {'/path/to/autotest/control/site_tests/test1/control': ['dep1']}
#  'suite': {'/path/to/autotest/control/site_tests/test2/control': ['dep2']}
#  'power': {'/path/to/autotest/control/site_tests/test1/control': ['dep1'],
#            '/path/to/autotest/control/site_tests/test3/control': ['dep3']}
# }
DEPENDENCIES_FILE = 'test_suites/dependency_info'


class MarkupStripper(HTMLParser.HTMLParser):
    """HTML parser that strips HTML tags, coded characters like &amp;

    Works by, basically, not doing anything for any tags, and only recording
    the content of text nodes in an internal data structure.
    """
    def __init__(self):
        self.reset()
        self.fed = []


    def handle_data(self, d):
        """Consume content of text nodes, store it away."""
        self.fed.append(d)


    def get_data(self):
        """Concatenate and return all stored data."""
        return ''.join(self.fed)


def _get_image_storage_server():
    return CONFIG.get_config_value('CROS', 'image_storage_server', type=str)


def _get_dev_server_list():
    return CONFIG.get_config_value('CROS', 'dev_server', type=list, default=[])


def _get_crash_server_list():
    return CONFIG.get_config_value('CROS', 'crash_server', type=list,
        default=[])


def remote_devserver_call(method):
    """A decorator to use with remote devserver calls.

    This decorator converts urllib2.HTTPErrors into DevServerExceptions with
    any embedded error info converted into plain text.
    """
    @retry.retry(urllib2.URLError, timeout_min=30)
    def wrapper(*args, **kwargs):
        """This wrapper actually catches the HTTPError."""
        try:
            return method(*args, **kwargs)
        except urllib2.HTTPError as e:
            error_markup = e.read()
            strip = MarkupStripper()
            try:
                strip.feed(error_markup.decode('utf_32'))
            except UnicodeDecodeError:
                strip.feed(error_markup)
            raise DevServerException(strip.get_data())

    return wrapper


class DevServerException(Exception):
    """Raised when the dev server returns a non-200 HTTP response."""
    pass



class DevServer(object):
    """Base class for all DevServer-like server stubs.

    This is the base class for interacting with all Dev Server-like servers.
    A caller should instantiate a sub-class of DevServer with:

    host = SubClassServer.resolve(build)
    server = SubClassServer(host)
    """
    def __init__(self, devserver):
        self._devserver = devserver


    def url(self):
        """Returns the url for this devserver."""
        return self._devserver


    @staticmethod
    def _devserver_up(devserver):
        """Returns True if the |devserver| is responding to calls."""
        call = DevServer._build_call(devserver, 'index')

        @remote_devserver_call
        def make_call():
            urllib2.urlopen(call)

        try:
            make_call()
            return True
        except (DevServerException, urllib2.URLError):
            return False


    @staticmethod
    def _build_call(host, method, **kwargs):
        """Build a URL to |host| that calls |method|, passing |kwargs|.

        Builds a URL that calls |method| on the dev server defined by |host|,
        passing a set of key/value pairs built from the dict |kwargs|.

        @param host: a string that is the host basename e.g. http://server:90.
        @param method: the dev server method to call.
        @param kwargs: a dict mapping arg names to arg values.
        @return the URL string.
        """
        argstr = '&'.join(map(lambda x: "%s=%s" % x, kwargs.iteritems()))
        return "%(host)s/%(method)s?%(argstr)s" % dict(
                host=host, method=method, argstr=argstr)


    def build_call(self, method, **kwargs):
        """
        Builds a devserver RPC string that can be invoked using urllib.open.
        """
        return self._build_call(self._devserver, method, **kwargs)


    @classmethod
    def build_all_calls(cls, method, **kwargs):
        """Builds a list of URLs that makes RPC calls on all devservers.

        Build a URL that calls |method| on the dev server, passing a set
        of key/value pairs built from the dict |kwargs|.

        @param method: the dev server method to call.
        @param kwargs: a dict mapping arg names to arg values
        @return the URL string
        """
        calls = []
        # Note we use cls.servers as servers is class specific.
        for server in cls.servers():
            if cls._devserver_up(server):
                calls.append(cls._build_call(server, method, **kwargs))

        return calls


    @staticmethod
    def servers():
        """Returns a list of servers that can serve as this type of server."""
        raise NotImplementedError()


    @classmethod
    def resolve(cls, build):
        """"Resolves a build to a devserver instance."""
        devservers = cls.servers()
        while devservers:
            hash_index = hash(build) % len(devservers)
            devserver = devservers.pop(hash_index)
            if cls._devserver_up(devserver):
                return cls(devserver)
        else:
            logging.error('All devservers are currently down!!!')
            raise DevServerException('All devservers are currently down!!!')


class CrashServer(DevServer):
    """Class of DevServer that symbolicates crash dumps."""
    @staticmethod
    def servers():
        return _get_crash_server_list()


    @remote_devserver_call
    def symbolicate_dump(self, minidump_path, build):
        """Ask the devserver to symbolicate the dump at minidump_path.

        Stage the debug symbols for |build| and, if that works, ask the
        devserver to symbolicate the dump at |minidump_path|.

        @param minidump_path: the on-disk path of the minidump.
        @param build: The build (e.g. x86-mario-release/R18-1586.0.0-a1-b1514)
                      whose debug symbols are needed for symbolication.
        @return The contents of the stack trace
        @raise DevServerException upon any return code that's not HTTP OK.
        """
        try:
            import requests
        except ImportError:
            logging.warning("Can't 'import requests' to connect to dev server.")
            return ''
        # Stage debug symbols.
        call = self.build_call('stage_debug',
                               archive_url=_get_image_storage_server() + build)
        request = requests.get(call)
        if (request.status_code != requests.codes.ok or
            request.text != 'Success'):
            error_fd = cStringIO.StringIO(request.text)
            raise urllib2.HTTPError(
                    call, request.status_code, request.text, request.headers,
                    error_fd)

        # Symbolicate minidump.
        call = self.build_call('symbolicate_dump')
        request = requests.post(
                call, files={'minidump': open(minidump_path, 'rb')})
        if request.status_code == requests.codes.OK:
            return request.text

        error_fd = cStringIO.StringIO(request.text)
        raise urllib2.HTTPError(
                call, request.status_code, request.text, request.headers,
                error_fd)


class ImageServer(DevServer):
    """Class for DevServer that handles image-related RPCs."""
    @staticmethod
    def servers():
        return _get_dev_server_list()


    @classmethod
    def devserver_url_for_servo(cls, build):
        """Returns the devserver url for use with servo recovery.

        @param board:  The board type to be recovered.
        """
        # To simplify manual steps on the server side, we ignore the
        # board type and hard-code the server as first in the list.
        #
        # TODO(jrbarnette) Once we have automated selection of the
        # build for recovery, we should revisit this.
        return cls.servers()[0]


    class ArtifactUrls(object):
        """A container for URLs of staged artifacts.

        Attributes:
            full_payload: URL for downloading a staged full release update
            mton_payload: URL for downloading a staged M-to-N release update
            nton_payload: URL for downloading a staged N-to-N release update

        """
        def __init__(self, full_payload=None, mton_payload=None,
                     nton_payload=None):
            self.full_payload = full_payload
            self.mton_payload = mton_payload
            self.nton_payload = nton_payload


    @remote_devserver_call
    def trigger_download(self, image, synchronous=True):
        """Tell the devserver to download and stage |image|.

        Tells the devserver to fetch |image| from the image storage server
        named by _get_image_storage_server().

        If |synchronous| is True, waits for the entire download to finish
        staging before returning. Otherwise only the artifacts necessary
        to start installing images onto DUT's will be staged before returning.
        A caller can then call finish_download to guarantee the rest of the
        artifacts have finished staging.

        @param image: the image to fetch and stage.
        @param synchronous: if True, waits until all components of the image are
               staged before returning.

        @raise DevServerException upon any return code that's not HTTP OK.

        """
        call = self.build_call(
                'download', archive_url=_get_image_storage_server() + image)
        response = urllib2.urlopen(call)
        was_successful = response.read() == 'Success'
        if was_successful and synchronous:
            self.finish_download(image)
        elif not was_successful:
            raise DevServerException("trigger_download for %s failed;"
                                     "HTTP OK not accompanied by 'Success'." %
                                     image)


    @remote_devserver_call
    def finish_download(self, image):
        """Tell the devserver to finish staging |image|.

        If trigger_download is called with synchronous=False, it will return
        before all artifacts have been staged. This method contacts the
        devserver and blocks until all staging is completed and should be
        called after a call to trigger_download.

        @param image: the image to fetch and stage.
        @raise DevServerException upon any return code that's not HTTP OK.
        """
        call = self.build_call('wait_for_status',
                               archive_url=_get_image_storage_server() + image)
        if urllib2.urlopen(call).read() != 'Success':
            raise DevServerException("finish_download for %s failed;"
                                     "HTTP OK not accompanied by 'Success'." %
                                     image)


    @remote_devserver_call
    def trigger_test_image_download(self, image_dir):
        """Tell the devserver to download and stage a Chrome OS test image.

        Tells the devserver to fetch a test image from |image_dir| on the image
        storage server named by _get_image_storage_server(). The call is
        synchronous.

        @param image_dir: the directory from which to fetch the image

        @raise DevServerException upon any return code that's not HTTP OK.

        """
        call = self.build_call(
                'stage_images',
                archive_url=_get_image_storage_server() + image_dir,
                image_types='test')
        response = urllib2.urlopen(call)
        was_successful = response.read() == 'Success'
        if not was_successful:
            raise DevServerException(
                "trigger_download of test image from %s failed; "
                "HTTP OK not accompanied by 'Success'." %
                image_dir)


    def get_delta_payload_url(self, payload_type, board, release, branch):
        """Returns a URL to a staged delta payload.

        @param payload_type: either 'mton' or 'nton'
        @param board: the board the payload corresponds to (e.g. 'x86-alex')
        @param release: the payload target release version (e.g. '2673.0.0')
        @param branch: the payload target release branch (e.g. 'R22')

        @return A fully qualified URL that can be used for downloading the
                payload.

        @raise DevServerException if payload type argument is invalid.

        """
        if payload_type not in ('mton', 'nton'):
            raise DevServerException('invalid delta payload type: %s' %
                                     payload_type)
        url_pattern = CONFIG.get_config_value(
                'CROS', 'delta_payload_url_pattern', type=str)
        return url_pattern % (self.url(), board, branch, release, branch,
                              release, payload_type)


    def get_full_payload_url(self, board, release, branch):
        """Returns a URL to a staged full payload.

        @param board: the board the payload corresponds to (e.g. 'x86-alex')
        @param release: the payload target release version (e.g. '2673.0.0')
        @param branch: the payload target release branch (e.g. 'R22')

        @return A fully qualified URL that can be used for downloading the
                payload.

        """
        url_pattern = CONFIG.get_config_value(
                'CROS', 'full_payload_url_pattern', type=str)
        return url_pattern % (self.url(), board, branch, release)


    def get_test_image_url(self, board, release, branch):
        """Returns a URL to a staged test image.

        @param board: the board to which the image corresponds (e.g. 'x86-alex')
        @param release: the image release version (e.g. '2673.0.0')
        @param branch: the image release branch (e.g. 'R22')

        @return A fully qualified URL that can be used for downloading the
                image.

        """
        url_pattern = CONFIG.get_config_value(
                'CROS', 'test_image_url_pattern', type=str)
        return url_pattern % (self.url(), board, branch, release)


    @remote_devserver_call
    def list_control_files(self, build):
        """Ask the devserver to list all control files for |build|.

        @param build: The build (e.g. x86-mario-release/R18-1586.0.0-a1-b1514)
                      whose control files the caller wants listed.
        @return None on failure, or a list of control file paths
                (e.g. server/site_tests/autoupdate/control)
        @raise DevServerException upon any return code that's not HTTP OK.
        """
        call = self.build_call('controlfiles', build=build)
        response = urllib2.urlopen(call)
        return [line.rstrip() for line in response]


    @remote_devserver_call
    def get_control_file(self, build, control_path):
        """Ask the devserver for the contents of a control file.

        @param build: The build (e.g. x86-mario-release/R18-1586.0.0-a1-b1514)
                      whose control file the caller wants to fetch.
        @param control_path: The file to fetch
                             (e.g. server/site_tests/autoupdate/control)
        @return The contents of the desired file.
        @raise DevServerException upon any return code that's not HTTP OK.
        """
        call = self.build_call('controlfiles', build=build,
                               control_path=control_path)
        return urllib2.urlopen(call).read()


    @remote_devserver_call
    def get_dependencies_file(self, build):
        """Ask the dev server for the contents of the suite dependencies file.

        Ask the dev server at |self._dev_server| for the contents of the
        pre-processed suite dependencies file (at DEPENDENCIES_FILE)
        for |build|.

        @param build: The build (e.g. x86-mario-release/R21-2333.0.0)
                      whose dependencies the caller is interested in.
        @return The contents of the dependencies file, which should eval to
                a dict of dicts, as per site_utils/suite_preprocessor.py.
        @raise DevServerException upon any return code that's not HTTP OK.
        """
        call = self.build_call('controlfiles',
                               build=build, control_path=DEPENDENCIES_FILE)
        return urllib2.urlopen(call).read()


    @classmethod
    @remote_devserver_call
    def get_latest_build(cls, target, milestone=''):
        """Ask all the devservers for the latest build for a given target.

        @param target: The build target, typically a combination of the board
                       and the type of build e.g. x86-mario-release.
        @param milestone:  For latest build set to '', for builds only in a
                           specific milestone set to a str of format Rxx
                           (e.g. R16). Default: ''. Since we are dealing with a
                           webserver sending an empty string, '', ensures that
                           the variable in the URL is ignored as if it was set
                           to None.
        @return A string of the returned build e.g. R20-2226.0.0.
        @raise DevServerException upon any return code that's not HTTP OK.
        """
        calls = cls.build_all_calls('latestbuild', target=target,
                                    milestone=milestone)
        latest_builds = []
        for call in calls:
            latest_builds.append(urllib2.urlopen(call).read())

        return max(latest_builds, key=version.LooseVersion)
