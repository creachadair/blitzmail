##
## An implementation of the BlitzMail protocol
##
## Copyright (C) 2004-2006 Michael J. Fromberger, All Rights Reserved.
##
## Starting in around 1987, Dartmouth College in Hanover, NH, USA
## developed its own home-grown e-mail system called BlitzMail.  This
## system has evolved since that time, and although it lacks some of
## the features of more modern e-mail systems, it has some practical
## benefits that have maintained its almost universal use on the
## Dartmouth campus.  A few other locations have also adopted
## BlitzMail, including Reed College in Oregon.
##
## BlitzMail is a client-server architecture, in which each user's
## e-mail is stored on a central server and accessed through client
## software that speaks the BlitzMail protocol.  Recent versions of
## the BlitzMail server software also support IMAP/SSL and POP
## interfaces.  This library is a Python implementation of the native
## BlitzMail protocol.
##
## The components of this package include:
## session   -- the main interface to the BlitzMail service.
## berror    -- exception classes.
## bfold     -- classes for handling folders on the server.
## blist     -- classes for handling mailing lists on the server.
## bmesg     -- classes for handling message summaries.
## bwarn     -- classes for handling server notifications.
## bulls     -- an interface to the BlitzMail bulletin service.
## notify    -- a package supporting a server-push notify service.
##
from session import *
from bulls import *
from berror import *
