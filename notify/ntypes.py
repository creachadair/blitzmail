##
## Name:     ntypes.py
## Purpose:  Shared data structures for UDP client and server.
##
## Copyright (C) 2004-2006 Michael J. Fromberger, All Rights Reserved.
##

import random, time, select, socket, sys, threading
from packet import *
from BlitzMail.berror import SessionError


class Notification(tuple):
    """A class representing a notification message.
    """
    def type(self):
        """Return the type code for the notification.
        """
        for key, val in NOTIFY_SERVICE.iteritems():
            if val == self[0]:
                return key

        return self[0]

    def uid(self):
        """Return the UID of the user the notification is for.
        """
        return self[1]

    def message_id(self):
        """Return the message ID included with the notification.
        """
        return self[2]

    def raw_data(self):
        """Return the raw packet data from the notification.
        """
        return self[3]

    def data(self):
        """Unpack strings from the notification and return a list of
        them.
        """
        pos = 0
        out = []
        while pos < len(self[-1]):
            end = pos + 1 + ord(self[-1][pos])
            out.append(self[-1][pos + 1:end])
            pos = end

        return out


class QElem(object):
    """Base class for packet queue elements."""
    def __init__(self, tid, data, addr, clk=None):
        self._orig = time.time()  # When packet was created
        self._time = 1  # Last time packet was used
        self._tid = tid
        self._data = data
        self._addr = addr

    def when(self):
        return self._time

    def tid(self):
        return self._tid

    def data(self):
        return self._data

    def addr(self):
        return self._addr

    def touch(self, clk=None):
        self._time = clk or time.time()

    def is_due(self, clk, ival):
        return clk - ival > self._time

    def age(self):
        return time.time() - self._orig

    def send(self, sock, rcpt):
        pkt = make_atp_packet(*self._data)
        sock.sendto(pkt, rcpt)
        self.touch()


class Request(QElem):
    """Base class for request packets."""
    pass


class Register(Request):
    """Registration request."""
    def __init__(self, tid, who, svcs, port, addr):
        super(Register,
              self).__init__(tid, ('req', ['xo'], 1, tid, 'NR02',
                                   make_register_req(svcs, who, port)), addr)


class Clear(Request):
    """Clear sticky notification request."""
    def __init__(self, tid, who, svc, addr):
        super(Clear, self).__init__(
            tid, ('req', ['xo'], 1, tid, 'CLEN', make_clear_req(svc, who)),
            addr)


class Reset(Request):
    """Request to go find another notification server."""
    def __init__(self, tid, addr):
        super(Reset, self).__init__(
            tid,
            ('req', ['xo'], 1, tid, '\x00\x00\x00\x00', '\x00\x00\x00\x01'),
            addr)


class Notify(Request):
    """Notification request."""
    def __init__(self, tid, who, svc, msgid, data, addr):
        super(Notify,
              self).__init__(tid, ('req', ['xo'], 1, tid, 'NOTI',
                                   make_notify_req(svc, who, msgid, data)),
                             addr)


class Response(QElem):
    """Transaction response entry."""
    def __init__(self, elt):
        if isinstance(elt, tuple):
            (kind, flags, seq, tid, udata, pdata, addr) = elt
        else:
            (kind, flags, seq, tid, udata, pdata) = elt.data()
            addr = elt.addr()

        super(Response,
              self).__init__(tid, ('rsp', flags, seq, tid, udata, pdata), addr)


class Release(QElem):
    """Transaction release entry."""
    def __init__(self, elt):
        (kind, flags, seq, tid, udata, pdata) = elt.data()
        addr = elt.addr()
        super(Release,
              self).__init__(tid, ('rel', flags, seq, tid, udata, None), addr)


class BlitzNotifyError(SessionError):
    """Base class for errors arising in the notification protocol."""


class ATPObject(object):
    """This class provides the basis of a simple interface to send and
    receive ATP requests via UDP.  A subclass may handle ATP requests,
    responses, and releases by overriding the do_req(), do_rsp(), and
    do_rel() methods.  The default methods do nothing.
    
    Override protocol:
      do_req(flags, seq, tid, udata, pdata, sndr)
         flags   -- ATP flags (int)
         tid     -- transaction ID (int)
         udata   -- user data (str)
         pdata   -- packet data (str)
         sndr    -- sender address (ip, port)

         If the return value of do_req() is true, a response is queued
         for the request; if the return value is a string, it becomes
         the packet data for the response.  Otherwise, the request is
         ignored and dropped, no response is sent.
    
      do_rsp(tobj), do_rel(tobj)
         tobj    -- transaction object (QElem)
    """
    def __init__(self, port=0, debug=False):
        """Initialize internal data structures.

        port   -- UDP port to receive packets on.
        debug  -- send debugging output to stderr?
        """
        self.port = port
        self.tid = random.randint(1, 0xffff)  # Transaction ID
        self.debug = debug

        self._maxage = 300  # Max. packet lifetime in seconds

        self._reader = None  # Thread to receive packets from server
        self._writer = None  # Thread to send packets to server
        self._socket = None  # UDP socket to talk to the server
        self._cdown = False  # Flag for shutting down

        self._rqueue = []  # Packets to be (re)transmitted
        self._lqueue = []  # Releases to be transmitted

        self._rqm = threading.Lock()  # Mutex for retrans queue
        self._som = threading.Lock()  # Mutex for shared socket
        self._cdc = threading.Condition()  # CVar for shutting down

    def _debug(self, fmt, *args):
        """Write debugging output to stderr if debug flag is set.
        """
        if self.debug:
            print >> sys.stderr, fmt % args

    def _send(self, req):
        """Send a request object on the UDP socket.
        """
        self._som.acquire()
        try:
            self._debug("+ SEND %s %s to %s for tid = %s", req._data[0],
                        req._data[4], req.addr(), req._tid)
            req.send(self._socket, req.addr())
        finally:
            self._som.release()

    def _addreq(self, Kind, *args):
        """Transmit a new request to the other end, and queue it for
        retransmission if necessary.  Kind must be a subclass of
        Request.  A transaction ID is automatically assigned.
        """
        if not issubclass(Kind, Request):
            raise BlitzNotifyError("Unknown request type: %s" % Kind)

        self._rqm.acquire()
        try:
            self._rqueue.append(Kind(self.tid, *args))
            self.tid = (self.tid + 1) & 0xffff

            self._debug("! Added new request to outbound queue: %s",
                        self._rqueue[-1])
            self._cdc.acquire()
            try:
                self._cdc.notify()
            finally:
                self._cdc.release()
        finally:
            self._rqm.release()

    def _sender(self):
        """Process retransmissions as necessary.  This is the target
        of the writer thread.
        """
        try:
            while True:
                now = time.time()

                self._rqm.acquire()
                try:
                    # Send any requests that are "due"
                    # Discard any requests that are too old
                    dead = []
                    for pos, elt in enumerate(self._rqueue):
                        if elt.age() > self._maxage:
                            self._debug("! Removing superannuated request: %s",
                                        elt)
                            dead.append(pos)
                        elif elt.is_due(now, 20):
                            self._send(elt)

                    for pos in reversed(dead):
                        self._rqueue.pop(pos)

                    # Send any outstanding releases
                    for elt in self._lqueue:
                        self._send(elt)
                    self._lqueue = []

                    # Find out when the next retransmission is due
                    if len(self._rqueue) == 0:
                        sleep_time = None
                    else:
                        sleep_time = min(elt.when()
                                         for elt in self._rqueue) + 20 - now
                finally:
                    self._rqm.release()

                self._debug("! Writer finished checking, sleep_time = %s",
                            sleep_time)

                if hasattr(self, 'write_poll'):
                    getattr(self, 'write_poll')()

                # Sleep until the next retransmission, or until
                # notified that the client is closing down.
                self._cdc.acquire()
                try:
                    if self._cdown: break
                    self._cdc.wait(sleep_time)
                    self._debug("! Writer awakened from sleep")
                    if self._cdown: break
                finally:
                    self._cdc.release()

        except socket.error:
            pass  # Also close down if the socket dies

        if hasattr(self, '_writer_done'):
            getattr(self, '_writer_done')()

        self._debug("! Writer thread is now exiting")

    def _receiver(self):
        """Handle packets received from the notification server.  This
        is the target of the reader thread.
        """
        try:
            fn = self._socket.fileno()

            while True:
                try:
                    (rd, wr, ex) = select.select([fn], (), ())
                except select.error, e:
                    self._debug("? Select failed on fd = %s:  %s", fn, e[1])
                    break

                self._debug("! Reader awakened from select")
                if fn not in rd: continue

                (pkt, sndr) = self._socket.recvfrom(256)
                if pkt == '': break  # Empty packet = EOF
                self._debug("RECEIVED PACKET FROM %s\n ==> %s", sndr,
                            repr(pkt))

                (kind, flags, seq, tid, udata, pdata) = \
                       parse_atp_packet(pkt)

                if kind == 'req':
                    self._debug("* REQUEST  %s tid = %d", udata, tid)

                    # Whether or not to respond depends on the return
                    # value from the request handler
                    rdata = self.do_req(flags, seq, tid, udata, pdata, sndr)
                    if rdata:
                        # Enqueue a response for transmission by the writer
                        self._rqm.acquire()
                        try:
                            if isinstance(rdata, str):
                                self._rqueue.append(
                                    Response((kind, flags, seq, tid, udata,
                                              rdata, sndr)))
                            else:
                                self._rqueue.append(
                                    Response((kind, flags, seq, tid, udata,
                                              None, sndr)))

                            # Wake up the writer to send it
                            self._cdc.acquire()
                            try:
                                self._cdc.notify()
                            finally:
                                self._cdc.release()
                        finally:
                            self._rqm.release()

                elif kind == 'rsp':
                    self._debug("* RESPONSE %s tid = %d", udata, tid)

                    self._rqm.acquire()
                    try:
                        # Remove pending requests for this transaction ID
                        dead = [
                            pos for (pos, elt) in enumerate(self._rqueue)
                            if elt.tid() == tid
                        ]

                        if dead:
                            tobj = self._rqueue[dead[0]]
                            elt = Release(tobj)
                            for pos in reversed(dead):
                                self._rqueue.pop(pos)

                            if self.do_rsp(tobj):
                                self._lqueue.append(elt)

                                # Wake up the writer to send it
                                self._cdc.acquire()
                                try:
                                    self._cdc.notify()
                                finally:
                                    self._cdc.release()
                    finally:
                        self._rqm.release()

                elif kind == 'rel':
                    self._debug("* RELEASE  %s tid = %d", udata, tid)

                    self._rqm.acquire()
                    try:
                        # Remove pending responses for this transaction ID
                        dead = []
                        for pos, elt in enumerate(self._rqueue):
                            if elt.tid() == tid:
                                dead.append(pos)
                                self.do_rel(elt)

                        for pos in reversed(dead):
                            self._rqueue.pop(pos)
                    finally:
                        self._rqm.release()

                else:  # ignore
                    self._debug("? UNKNOWN  %s tid = %d", udata, tid)

        except socket.error:
            pass  # Close down if the socket dies

        if hasattr(self, '_reader_done'):
            getattr(self, '_reader_done')()
        self._debug("! Reader thread is now exiting")

    def start(self):
        """Start up the ATP processing threads."""
        if self.is_running(): return

        self._reader = None  # Thread to receive packets from server
        self._writer = None  # Thread to send packets to server
        self._socket = None  # UDP socket to talk to the server
        self._cdown = False  # Flag for shutting down

        self._rqueue = []  # Packets to be (re)transmitted
        self._lqueue = []  # Releases to be transmitted
        self._nqueue = []  # Notifications received

        # Set up a datagram socket for communication with the server
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # If the user specified a local port, bind to it
        if self.port <> 0:
            self._socket.bind(('0.0.0.0', self.port))

        self._reader = threading.Thread(target=self._receiver)
        self._writer = threading.Thread(target=self._sender)
        self._reader.setName("READER")
        self._reader.setDaemon(True)
        self._writer.setName("WRITER")
        self._writer.setDaemon(True)

        self._reader.start()
        self._writer.start()

    def stop(self):
        """Shut down the ATP processing threads."""
        if not self.is_running(): return

        # Close the socket to kill the reader, flag shutdown and
        # notify the writer to break out of the wait loop.
        self._socket.close()
        self._cdc.acquire()
        try:
            self._cdown = True
            self._cdc.notifyAll()
        finally:
            self._cdc.release()

        self._debug('! Waiting for reader to close down')
        self._reader.join()
        self._debug('! Waiting for writer to close down')
        self._writer.join()
        self._debug('! THREADS COMPLETE')

    def is_running(self):
        """Return True if both processing threads are running, else False."""
        return None not in (self._reader, self._writer) and \
               self._reader.isAlive() and self._writer.isAlive()

    # Default request, response, and release handlers
    def do_req(self, *args):
        return True

    def do_rsp(self, *args):
        return True

    def do_rel(self, *args):
        pass


__all__ = [
    "BlitzNotifyError", "Release", "Response", "Notify", "Clear", "Register",
    "Reset", "Request", "QElem", "Notification", "ATPObject"
]

# Here there be dragons
