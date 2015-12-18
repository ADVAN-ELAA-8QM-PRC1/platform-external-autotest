# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""This class defines the Base Label classes."""


import logging

import common

from autotest_lib.server.cros.dynamic_suite import frontend_wrappers


class BaseLabel(object):
    """
    This class contains the scaffolding for the host-specific labels.

    @property _NAME String that is either the label returned or a prefix of a
                    generated label.
    @property _LABEL_LIST List of label classes that this label generates its
                          own labels from.  This class attribute is primarily
                          for the LabelRetriever class to figure out what
                          labels are generated from this label.  In most cases,
                          the _NAME attribute gives us what we want, but in the
                          special case where a label class is actually a
                          collection of label classes, then this attribute
                          comes into play.  For the example of
                          testbed_label.ADBDeviceLabels, that class is really a
                          collection of the adb devices' labels in that testbed
                          so _NAME won't cut it.  Instead, we use _LABEL_LIST
                          to tell LabelRetriever what list of label classes we
                          are generating and thus are able to have a
                          comprehensive list of the generated labels.
    """

    _NAME = None
    _LABEL_LIST = []

    def generate_labels(self, host):
        """
        Return the list of labels generated for the host.

        @param host: The host object to check on.  Not needed here for base case
                     but could be needed for subclasses.

        @return a list of labels applicable to the host.
        """
        return [self._NAME]


    def exists(self, host):
        """
        Checks the host if the label is applicable or not.

        This method is geared for the type of labels that indicate if the host
        has a feature (bluetooth, touchscreen, etc) and as such require
        detection logic to determine if the label should be applicable to the
        host or not.

        @param host: The host object to check on.
        """
        raise NotImplementedError('exists not implemented')


    def get(self, host):
        """
        Return the list of labels.

        @param host: The host object to check on.
        """
        if self.exists(host):
            return self.generate_labels(host)
        else:
            return []


    def get_all_labels(self):
        """
        Return all possible labels generated by this label class.

        @returns a tuple of sets, the first set is for labels that are prefixes
            like 'os:android'.  The second set is for labels that are full
            labels by themselves like 'bluetooth'.
        """
        # Another subclass takes care of prefixed labels so this is empty.
        prefix_labels = set()
        full_labels_list = (self._NAME if isinstance(self._NAME, list) else
                            [self._NAME])
        full_labels = set(full_labels_list)

        return prefix_labels, full_labels


class StringLabel(BaseLabel):
    """
    This class represents a string label that is dynamically generated.

    This label class is used for the types of label that are always
    present and will return at least one label out of a list of possible labels
    (listed in _NAME).  It is required that the subclasses implement
    generate_labels() since the label class will need to figure out which labels
    to return.

    _NAME must always be overridden by the subclass with all the possible
    labels that this label detection class can return in order to allow for
    accurate label updating.
    """

    def generate_labels(self, host):
        raise NotImplementedError('generate_labels not implemented')


    def exists(self, host):
        """Set to true since it is assumed the label is always applicable."""
        return True


class StringPrefixLabel(StringLabel):
    """
    This class represents a string label that is dynamically generated.

    This label class is used for the types of label that usually are always
    present and indicate the os/board/etc type of the host.  The _NAME property
    will be prepended with a colon to the generated labels like so:

        _NAME = 'os'
        generate_label() returns ['android']

    The labels returned by this label class will be ['os:android'].
    It is important that the _NAME attribute be overridden by the
    subclass; otherwise, all labels returned will be prefixed with 'None:'.
    """

    def get(self, host):
        """Return the list of labels with _NAME prefixed with a colon.

        @param host: The host object to check on.
        """
        if self.exists(host):
            return ['%s:%s' % (self._NAME, label)
                    for label in self.generate_labels(host)]
        else:
            return []


    def get_all_labels(self):
        """
        Return all possible labels generated by this label class.

        @returns a tuple of sets, the first set is for labels that are prefixes
            like 'os:android'.  The second set is for labels that are full
            labels by themselves like 'bluetooth'.
        """
        # Since this is a prefix label class, we only care about
        # prefixed_labels.  We'll need to append the ':' to the label name to
        # make sure we only match on prefix labels.
        full_labels = set()
        prefix_labels = set(['%s:' % self._NAME])

        return prefix_labels, full_labels


class LabelRetriever(object):
    """This class will assist in retrieving/updating the host labels."""

    def _populate_known_labels(self, label_list):
        """Create a list of known labels that is created through this class."""
        for label_instance in label_list:
            # If this instance has a list of label, recurse on that list.
            if label_instance._LABEL_LIST:
                self._populate_known_labels(label_instance._LABEL_LIST)
                continue

            prefixed_labels, full_labels = label_instance.get_all_labels()
            self.label_prefix_names.update(prefixed_labels)
            self.label_full_names.update(full_labels)


    def __init__(self, label_list):
        self._labels = label_list
        # These two sets will contain the list of labels we can safely remove
        # during the update_labels call.
        self.label_full_names = set()
        self.label_prefix_names = set()
        self._populate_known_labels(self._labels)


    def get_labels(self, host):
        """
        Retrieve the labels for the host.

        @param host: The host to get the labels for.
        """
        labels = []
        for label in self._labels:
            try:
                labels.extend(label.get(host))
            except Exception as e:
                logging.exception('error getting label %s: %s',
                                  label.__class__.__name__, e)
        return labels


    def _is_known_label(self, label):
        """
        Checks if the label is a label known to the label detection framework.

        We only delete labels that we might have created earlier.  There are
        some labels we should not be removing (e.g. pool:bvt) that we
        want to keep but won't be part of the new labels detected on the host.
        To do that we compare the passed in label to our list of known labels
        and if we get a match, we feel safe knowing we can remove the label.
        Otherwise we leave that label alone since it was generated elsewhere.

        @param label: The label to check if we want to skip or not.

        @returns True to skip (which means to keep this label, False to remove.
        """
        return (label in self.label_full_names or
                any([label.startswith(p) for p in self.label_prefix_names]))


    def update_labels(self, host):
        """
        Retrieve the labels from the host and update if needed.

        @param host: The host to update the labels for.
        """
        afe = frontend_wrappers.RetryingAFE(timeout_min=5, delay_sec=10)
        afe_host = afe.get_hosts(hostname=host.hostname)[0]
        old_labels = set(afe_host.labels)
        known_labels = set([l for l in old_labels
                            if self._is_known_label(l)])
        new_labels = set(self.get_labels(host))

        # Remove old labels.
        labels_to_remove = list(old_labels & (known_labels - new_labels))
        if labels_to_remove:
            afe_host.remove_labels(labels_to_remove)

        # Add in new labels that aren't already there.
        labels_to_add = list(new_labels - old_labels)
        if labels_to_add:
            afe_host.add_labels(labels_to_add)
