#!/usr/bin/env python
##
## Name:     procnotify.py
## Purpose:  Convert new e-mail messages into BlitzMail notifies.
##
## Copyright (C) 2004-2006 Michael J. Fromberger, All Rights Reserved.
##

import dnd, os, pwd, rfc822, re, sys, time
from BlitzMail import notify
from getopt import getopt

debug = False  # Set true for debugging output


def main(args):
    global debug

    (opts, args) = getopt(
        args[1:], 'du:f:TFSI:h',
        ('debug', 'user=', 'file=', 'in=', 'to', 'from', 'subject', 'help'))

    user_name = pwd.getpwuid(os.getuid()).pw_gecos.split(',')[0]
    want_to = False
    want_from = False
    want_subject = False
    want_target = None
    input_file = sys.stdin

    # Process command-line arguments
    for (opt, arg) in opts:
        if opt in ('-u', '--user'):
            user_name = arg
        elif opt in ('-f', '--file'):
            try:
                input_file = file(arg, 'rU')
            except IOError, e:
                print >> sys.stderr, "Error opening `%s': %s" % \
                      (arg, e)
                sys.exit(1)
        elif opt in ('-T', '--to'):
            want_to = True
        elif opt in ('-F', '--from'):
            want_from = True
        elif opt in ('-S', '--subject'):
            want_subject = True
        elif opt in ('-I', '--in'):
            want_target = arg
        elif opt in ('-h', '--help'):
            print """
This program reads an e-mail message from standard input and generates
a notification for it.  Options include:

  -d, --debug     : enable debugging output (to standard error).
  -u, --user      : specify user's DND name for notification.
  -f, --file      : read input from a file instead of standard input.
  -h, --help      : this help message.
  -T, --to        : include recipient info in notification.
  -F, --from      : include sender info in notification.
  -S, --subject   : include subject header in notification.
  -I, --in        : include target information in notification.

If no username is specified, the current user's GECOS field is looked
up in the DND.  If no filename is specified, the standard input is
read.
"""
            sys.exit(0)
        elif opt in ('-d', '--debug'):
            debug = True
            print >> sys.stderr, "[debugging mode]"

    uinfo = dnd.lookup_unique(user_name, ('name', 'uid', 'notifyserv'))
    message = rfc822.Message(input_file)
    subject = message.get('subject') or None
    sender = message.getaddr('from')
    recip = message.getaddr('to')
    dtime = time.strftime('%d-%b-%y, %I:%M %p')

    note = "(%s) %s has received new mail" % (dtime, uinfo.name)
    # Add sender, if requested and available
    if want_from:
        if sender[0]:
            note += ' from %s' % re.sub('\s+', ' ', sender[0])
        elif sender[1]:
            note += ' from <%s>' % sender[1]

    # Add recipient, if requested and available
    if want_to:
        if recip[0]:
            note += ' to %s' % re.sub('\s+', ' ', recip[0])
        elif recip[1]:
            note += ' to <%s>' % recip[1]

    # Add target, if requested
    if want_target is not None:
        note += ' in "%s"' % want_target

    # Add subject line, if requested and available.
    if want_subject and subject is not None:
        note += ' about "%s"' % subject

    # Constrain length to fit within 255 characters
    if len(note) > 255:
        note = note[:252] + '...'

    if debug:
        print >> sys.stderr, \
              ">> SUMMARY OF NOTIFICATION <<\n" \
              "Subject:   %s\n" \
              "Sender:    %s\n" \
              "Timestamp: %s\n" \
              "Message:\n %s" % (subject, sender, dtime, note)

    ns = notify.NotifySession(debug=debug)
    ns.connect(uinfo.notifyserv.split('@')[0])
    ns.post_notify('mail', data=note + '.', uid=uinfo.uid, sticky=False)
    ns.close()

    input_file.close()


if __name__ == '__main__':
    main(sys.argv)

# Here there be dragons
