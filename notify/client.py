##
## Name:     client.py
## Purpose:  Implements the UDP notification client protocol.
##
## Copyright (C) 2004-2006 Michael J. Fromberger, All Rights Reserved.
##
## Notes:
## The implementation here is not quite complete; it does not handle
## the "reset" message from the notification server that tells the
## client to "look elsewhere."  This should not usually cause any
## problems, because account moves between servers are rare, but I
## should probably implement it at some point.
##
from ntypes import *
from packet import *
import dnd, socket, threading

default_debug = False  # Set True to enable debugging output by default


def lookup_user(name, dndhost=None):
    """Find relevant information in the DND for the specified user, in
    order to establish a NotifyClient.

    name     -- User name or UID to look up
    dndhost  -- Host name of DND server to talk to
    
    Returns:  DNDRecord object with .name, .uid, and .blitzserv fields.
    """
    dir = dnd.DNDSession(dndhost)
    info = dir.lookup_unique(name, 'name', 'uid', 'blitzserv')
    if not info:
        raise BlitzNotifyError("No unique match for user '%s'" % name, name)

    info.blitzserv = info.blitzserv.split('@')[0]
    return info


class NotifyClient(ATPObject):
    """Implements a simple UDP client for the BlitzNotify protocol.
    The client runs two threads to communicate with the server, so
    that it doesn to block the rest of your application.
    
    This implementation can only handle one user at a time: If you
    want to receive notifications ofr multiple users, you should
    create one instance of this class for each user.
    """
    def __init__(self,
                 uid,
                 host,
                 svcs,
                 port=0,
                 nport=2154,
                 debug=default_debug):
        """Create a new notification client.

        uid     -- unique ID of user to get notifications for.
        host    -- hostname or IP address of notification server.
        svcs    -- service names to listen for (sequence).
        port    -- UDP port to listen on [integer, random].
        nport   -- where to contact the notification server.
        debug   -- show debugging output [bool].
        """
        super(NotifyClient, self).__init__(port, debug)
        self.nport = nport  # Where to contact notification server

        self._nqueue = []  # Notifications received
        self._nqc = threading.Condition()  # CVar for notification queue

        self._uid = str(uid).lstrip('#')
        self.svcs = tuple(NOTIFY_SERVICE.get(s, s) for s in svcs)
        self.host = host
        self.addr = None

    def __len__(self):
        """Return the number of notifications available in the queue."""
        self._nqc.acquire()
        try:
            return len(self._nqueue)
        finally:
            self._nqc.release()

    def __del__(self):
        self.stop()

    def start(self):
        """Start up the notification client."""
        if self.is_running():
            return

        self._nqueue = []  # Notifications received

        # Save the IP and port of the notification server for later
        self.addr = (socket.gethostbyname(self.host), self.nport)

        super(NotifyClient, self).start()
        self._addreq(Register, '#' + self._uid, self.svcs, self.port,
                     self.addr)

    def do_req(self, flags, seq, tid, udata, pdata, sndr):
        """Handle incoming request packets (called from ATPObject).
        """
        if udata == 'NOTI':
            self._nqc.acquire()
            self._nqueue.append(Notification(parse_notify_req(pdata)))
            self._nqc.notify()
            self._nqc.release()
            return True
        elif udata == '\x00\x00\x00\x00':
            return True
        else:
            return False

    def clear(self, svc):
        """Clear sticky notifications for the specified service."""

        self._addreq(Clear, self._uid, NOTIFY_SERVICE.get(svc, svc), self.addr)

    def next(self, timeout=None):
        """Wait for a notification to become available, and return it.
        Waits for up to timeout seconds for a notification to arrive,
        or forever if no timeout is specified.  Returns None if the
        timer expires without a notification becoming available.  The
        notification returned is removed from the queue.
        """
        self._nqc.acquire()
        try:
            if self.is_running() and len(self._nqueue) == 0:
                self._nqc.wait(timeout)

            if len(self._nqueue) == 0:
                out = None
            else:
                out = self._nqueue.pop(0)
        finally:
            self._nqc.release()

        return out

    def peek(self):
        """If there are any notifications available, return the first
        one without removing it from the queue.  If no notifications
        are available, returns None.  Does not block.
        """
        self._nqc.acquire()
        try:
            if len(self._nqueue) == 0:
                out = None
            else:
                out = self._nqueue[0]
        finally:
            self._nqc.release()

        return out


__all__ = [
    'NotifyClient', 'BlitzNotifyError', 'Notification', 'Register', 'Clear',
    'ATPObject', 'lookup_user'
]

# Here there be dragons
