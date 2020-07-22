##
## Name:     __init__.py
## Purpose:  BlitzMail notification protocol client package
##
## Copyright (C) 2004-2006 Michael J. Fromberger, All Rights Reserved.
##

from session import *
from client import *
try:
    from notifyd import *
except ImportError as e:
    pass

# Here there be dragons
