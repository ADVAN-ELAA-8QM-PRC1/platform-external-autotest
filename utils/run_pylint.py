#!/usr/bin/python -u
"""
Wrapper to patch pylint library functions to suit autotest.

This script is invoked as part of the presubmit checks for autotest python
files. It runs pylint on a list of files that it obtains either through
the command line or from an environment variable set in pre-upload.py.

Example:
run_pylint.py filename.py
"""

import os, re, sys, fnmatch


# Do a basic check to see if pylint is even installed.
try:
    import pylint
    from pylint.__pkginfo__ import version as pylint_version
except ImportError:
    print ("Unable to import pylint, it may need to be installed."
           " Run 'sudo aptitude install pylint' if you haven't already.")
    sys.exit(1)

major, minor, release = pylint_version.split('.')
pylint_version = float("%s.%s" % (major, minor))

# some files make pylint blow up, so make sure we ignore them
BLACKLIST = ['/contrib/*', '/frontend/afe/management.py']

# patch up the logilab module lookup tools to understand autotest_lib.* trash
import logilab.common.modutils
_ffm = logilab.common.modutils.file_from_modpath
def file_from_modpath(modpath, path=None, context_file=None):
    """
    Wrapper to eliminate autotest_lib from modpath.

    @param modpath: name of module splitted on '.'
    @param path: optional list of paths where module should be searched for.
    @param context_file: path to file doing the importing.
    @return The path to the module as returned by the parent method invocation.
    @raises: ImportError if these is no such module.
    """
    if modpath[0] == "autotest_lib":
        return _ffm(modpath[1:], path, context_file)
    else:
        return _ffm(modpath, path, context_file)
logilab.common.modutils.file_from_modpath = file_from_modpath


import pylint.lint
from pylint.checkers import base, imports, variables

# need to put autotest root dir on sys.path so pylint will be happy
autotest_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, autotest_root)

# patch up pylint import checker to handle our importing magic
ROOT_MODULE = 'autotest_lib.'
COMMON_MODULE = 'common'


def patch_modname(modname):
    """
    Patches modname so we can make sense of autotest_lib modules.

    @param modname: name of a module, contains '.'
    @return modified modname string.
    """
    if modname.startswith(ROOT_MODULE) or modname.startswith(ROOT_MODULE[:-1]):
        modname = modname[len(ROOT_MODULE):]
    return modname


def patch_consumed_list(to_consume=None, consumed=None):
    """
    Patches consumed modules list.

    Prevents pylint from flagging 'common' as an unused import if we're
    importing from autotest_lib. to_consume and consumed are dictionaries pylint
    uses to record what 'names' (functions/modules/classes) it sees in a given
    scope. When a name is referenced it's moved from one dictionary to the other
    and after all visitors of the ast have been visited the entries left in
    to_consume are reported by pylint as unused.

    @param modname: name of a module, contains '.'
    @param to_consume: a dictionary of names pylint needs to see referenced.
    @param consumed: a dictionary of names that pylint has seen referenced.
    @return modified modname string.
    """
    if (to_consume is not None and
          consumed is not None and
          COMMON_MODULE in to_consume):
        consumed[COMMON_MODULE] = to_consume[COMMON_MODULE]
        del to_consume[COMMON_MODULE]


class CustomImportsChecker(imports.ImportsChecker):
    """Modifies stock imports checker to suit autotest."""
    def visit_from(self, node):
        node.modname = patch_modname(node.modname)
        return super(CustomImportsChecker, self).visit_from(node)


class CustomVariablesChecker(variables.VariablesChecker):
    """Modifies stock variables checker to suit autotest."""

    def visit_module(self, node):
        """
        Unflag 'import common'.

        _to_consume eg: [({to reference}, {referenced}, 'scope type')]
        Enteries are appended to this list as we drill deeper in scope.
        If we ever come across an 'import common' we immediately move it
        to the consumed list.

        @param node: node of the ast we're currently checking.
        """
        super(CustomVariablesChecker, self).visit_module(node)
        scoped_names = self._to_consume.pop()
        patch_consumed_list(scoped_names[0],scoped_names[1])
        self._to_consume.append(scoped_names)

    def visit_from(self, node):
        """Patches modnames so pylints understands autotest_lib."""
        node.modname = patch_modname(node.modname)
        return super(CustomVariablesChecker, self).visit_from(node)


class CustomDocStringChecker(base.DocStringChecker):
    """Modifies stock docstring checker to suit Autotest doxygen style."""

    def _check_docstring(self, node_type, node):
        """
        Teaches pylint to look for @param with each argument in the
        function/method signature.

        @param node_type: type of the node we're currently checking.
        @param node: node of the ast we're currently checking.
        """
        super(CustomDocStringChecker, self)._check_docstring(node_type, node)
        docstring = node.doc
        if (docstring is not None and
               (node_type is 'method' or
                node_type is 'function')):
            args = node.argnames()
            old_msg = self.linter._messages['C0111'].msg
            for arg in args:
                arg_docstring_rgx = '.*@param '+arg+'.*'
                line = re.search(arg_docstring_rgx, node.doc)
                if not line and arg is not 'self':
                    self.linter._messages['C0111'].msg = ('Docstring needs '
                                                          '"@param '+arg+':"')
                    self.add_message('C0111', node=node)
            self.linter._messages['C0111'].msg = old_msg

base.DocStringChecker = CustomDocStringChecker
imports.ImportsChecker = CustomImportsChecker
variables.VariablesChecker = CustomVariablesChecker


def check_file(file_path, base_opts):
    """
    Invokes pylint on files after confirming that they're not black listed.

    @param base_opts: pylint base options.
    @param file_path: path to the file we need to run pylint on.
    """
    if not file_path.endswith('.py'):
        return
    for blacklist_pattern in BLACKLIST:
        if fnmatch.fnmatch(os.path.abspath(file_path),
                           '*' + blacklist_pattern):
            return
    pylint_runner = pylint.lint.Run(base_opts + [file_path], exit=False)
    if pylint_runner.linter.msg_status:
        sys.exit(pylint_runner.linter.msg_status)


def visit(arg, dirname, filenames):
    """
    Visit function invoked in check_dir.

    @param arg: arg from os.walk.path
    @param dirname: dir from os.walk.path
    @param filenames: files in dir from os.walk.path
    """
    for filename in filenames:
        check_file(os.path.join(dirname, filename), arg)


def check_dir(dir_path, base_opts):
    """
    Calls visit on files in dir_path.

    @param base_opts: pylint base options.
    @param dir_path: path to directory.
    """
    os.path.walk(dir_path, visit, base_opts)


def extend_baseopts(base_opts, new_opt):
    """
    Replaces an argument in base_opts with a cmd line argument.

    @param base_opts: original pylint_base_opts.
    @param new_opt: new cmd line option.
    """
    for args in base_opts:
        if new_opt in args:
            base_opts.remove(args)
    base_opts.append(new_opt)


def get_cmdline_options(args_list, pylint_base_opts, rcfile):
    """
    Parses args_list and extends pylint_base_opts.

    Command line arguments might include options mixed with files.
    Go through this list and filter out the options, if the options are
    specified in the pylintrc file we cannot replace them and the file
    needs to be edited. If the options are already a part of
    pylint_base_opts we replace them, and if not we append to
    pylint_base_opts.

    @param args_list: list of files/pylint args passed in through argv.
    @param pylint_base_opts: default pylint options.
    @param rcfile: text from pylint_rc.
    """
    for args in args_list:
        if args.startswith('--'):
            opt_name = args[2:].split('=')[0]
            if opt_name in rcfile and pylint_version >= 0.21:
                print ('The rcfile already contains %s.'
                       ' Please edit pylintrc instead.' % opt_name)
                sys.exit(1)
            else:
                extend_baseopts(pylint_base_opts, args)
                args_list.remove(args)

def main():
    """Main function checks each file in a commit for pylint violations."""

    # For now all error/warning/refactor/convention exceptions except W0611 are
    # disabled. W0611 raises an exception when an imported module is not used.
    # Ideally we would like to enable as much as we can, but if we did so at
    # this stage anyone who makes a tiny change to a file will be tasked with
    # cleaning all the lint in it. See chromium-os:37364.

    # Note: There are three major sources of E1101/E1103/E1120 false positives:
    # * common_lib.enum.Enum objects
    # * DB model objects (scheduler models are the worst, but Django models also
    #   generate some errors)
    pylint_rc = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             'pylintrc')
    if pylint_version >= 0.21:
        pylint_base_opts = ['--rcfile=%s' % pylint_rc,
                            '--reports=no',
                            '--disable=W,R,E,C,F',
                            '--enable=W0611,C0111,C0112',]
    else:
        all_failures = 'error,warning,refactor,convention'
        pylint_base_opts = ['--disable-msg-cat=%s' % all_failures,
                            '--reports=no',
                            '--include-ids=y',
                            '--ignore-docstrings=n',]

    # run_pylint can be invoked directly with command line arguments,
    # or through a presubmit hook which uses the arguments in pylintrc. In the
    # latter case no command line arguments are passed. If it is invoked
    # directly without any arguments, it should check all files in the cwd.
    args_list = sys.argv[1:]
    if args_list:
        get_cmdline_options(args_list,
                            pylint_base_opts,
                            open(pylint_rc).read())
    else:
        presubmit_files = os.environ.get('PRESUBMIT_FILES')
        if presubmit_files:
            args_list = presubmit_files.split('\n')
        else:
            check_dir('.', pylint_base_opts)
            return

    for source_path in args_list:
        if os.path.isdir(source_path):
            check_dir(source_path, pylint_base_opts)
        else:
            check_file(source_path, pylint_base_opts)


if __name__ == '__main__':
    main()
