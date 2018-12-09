#!/usr/bin/env python
##
## Name:     setup.py
## Purpose:  Install BlitzMail and Notify libraries.
##
## Copyright (C) 2004-2006 Michael J. Fromberger, All Rights Reserved.
##
## Standard usage:  python setup.py install
##
from distutils.core import setup
from os.path import join as pjoin
from session import __version__ as lib_version

setup(name = 'BlitzMail',
      version = lib_version,
      description = 'BlitzMail client library',
      long_description = """
This is an implementation of the majority of the BlitzMail protocol in
Python.  If you are not familiar with BlitzMail, you probably do not
need this, however, for more information, see:

  http://www.dartmouth.edu/softdev/
  http://www.dartmouth.edu/comp/support/library/software/email/blitzmail/

In summary, BlitzMail is an easy-to-use electronic mail system
developed at Dartmouth College in the late 1980's, which is still the
dominant e-mail system in use at the College as of this writing.  It
is also used at other sites (e.g., Dartmouth-Hitchcock Medical Center,
Reed College, Washington University, and at least two ISP's in the
Upper Connecticut River Valley).""",
      author = 'M. J. Fromberger',
      author_email = "michael.j.fromberger@gmail.com",
      url = 'http://spinning-yarns.org/michael/sw/#pyblitz',
      classifiers = ['Development Status :: 5 - Production/Stable',
                     'Intended Audience :: Developers',
                     'License :: Freeware',
                     'Operating System :: OS Independent',
                     'Programming Language :: Python',
                     'Topic :: Internet',
                     'Topic :: Software Development :: ' \
                     'Libraries :: Python Modules'],
      packages = ['BlitzMail', 'BlitzMail.notify'],
      package_dir = { 'BlitzMail': '' },
      scripts =  ['blitz2mbox', 'listedit',
                  'notify/necho'])

# Here there be dragons
