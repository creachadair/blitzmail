#!/usr/bin/env python
##
## Name:     notifyd.py
## Purpose:  Implements a simple BlitzMail notification protocol server.
##
## Copyright (C) 2004-2006 Michael J. Fromberger, All Rights Reserved.
##
## Additional Requirements:
##   SQLite     http://sqlite.org/
##   pysqlite2  http://pysqlite.org/
##

import dnd, re, socket, struct, sys, threading, time
from pysqlite2 import dbapi2 as sql
from SocketServer import ThreadingTCPServer, StreamRequestHandler
from ntypes import *
from packet import *


class Notice(object):
    """Represents a notice awaiting delivery."""

    def __init__(self, uid, type, msgid, sticky, data=None, rowid=None):
        """Construct a new notice object.
        
        uid    -- User ID (int)
        type   -- Notification type (int)
        msgid  -- Message ID (int)
        sticky -- Is notice persistent? (bool)
        data   -- Message content [str]
        """
        self.uid = uid
        self.type = type
        self.msgid = msgid
        self.sticky = sticky
        self.data = data
        self.rowid = rowid

    def __str__(self):
        return '<%s for %s type=%d msgid=%d sticky=%s data="%s">' % \
               (type(self).__name__,
                self.uid, self.type, self.msgid,
                (self.sticky and "Y" or "N"),
                self.data)


class Client(object):
    """Represents a client desiring notification."""

    def __init__(self, uid, ip, port, svcs):
        """Create a new client record.

        uid    -- User ID (int)
        ip     -- IP address (str)
        port   -- UDP port (int)
        svcs   -- Service codes (sequence of int)
        """
        self.uid = uid
        self.ip = ip
        self.port = port
        self.svcs = svcs
        self.smark = 0
        self.rmark = 0

    def addr(self):
        """Return a tuple (ip, port) denoting the client's address."""
        return (self.ip, self.port)

    def sendmark(self):
        """Mark the client as having had a packet sent to it recently."""
        self.smark = time.time()

    def recvmark(self):
        """Mark the client as having sent us a packet recently."""
        self.rmark = time.time()

    def age(self):
        """If we have sent a packet to this client more recently than
        the last time they sent us anything, the age of the client is
        the number of seconds elapsed since we last heard from them;
        otherwise, it is zero.
        """
        if self.smark >= self.rmark:
            return time.time() - self.rmark
        else:
            return 0

    def __eq__(self, other):
        return isinstance(other, type(self)) and \
               self.uid == other.uid and \
               self.ip == other.ip and \
               self.port == other.port

    def __str__(self):
        return '<%s uid=%d ip=%s port=%d>' % \
               (type(self).__name__,
                self.uid, self.ip, self.port)


class NotifyTCPHandler(StreamRequestHandler):
    """A command handler for the TCP notification protocol.  This class
    implements the request handler protocol used by SocketServer.

    See also:  class NotifyTCPServer
    """

    def cmd_unknown(self, cmd, args):
        """Handles commands which are not otherwise known."""
        self.wfile.write('500 Unknown command: %s\r\n' % cmd.upper())

    def cmd_QUIT(self, cmd, args):
        """QUIT

        Disconnect from the server.
        """
        self.wfile.write('221 Bye now!\r\n')
        self.quit = True
        self.server.auth = None

    def cmd_NOOP(self, cmd, args):
        """NOOP

        Does nothing, just a poll.
        """
        self.wfile.write('200 Nothing.\r\n')

    def cmd_CLEAR(self, cmd, args):
        """CLEAR <uid> <type> -- clear sticky notifications for the
        specified user <uid> and type code <type>.
        """
        if len(args) <> 2:
            self.wfile.write('501 Wrong number of arguments.\r\n')
            return

        try:
            uid = int(args[0])
            type = int(args[1])
        except ValueError:
            self.wfile.write('501 Invalid argument.\r\n')
            return

        if uid == 0 and not self.server.check_perms('broadcast'):
            self.wfile.write('554 Broadcast permission denied.\r\n')
            return

        self.server.clear(uid, type)
        self.wfile.write('200 Notifications cleared.\r\n')

    def cmd_NOTIFY(self, cmd, args):
        """NOTIFY <len> <uid> <type> <msgid> <sticky>

        Post a new notification to the server.  The <len> specifies
        the number of bytes of message data that immediately follow
        the NOTIFY command line.  The <sticky> flag is 0 or nonzero
        to determine whether the notice is persistent.

        If <uid> is zero and the connected user has permission, the
        notice is considered a "broadcast" to all registered clients.
        This is a nonstandard feature of this implementation.
        """
        if len(args) <> 5:
            self.wfile.write('501 Wrong number of arguments.\r\n')
            return

        try:
            length = int(args[0])
            uid = int(args[1])
            type = int(args[2])
            msgid = int(args[3])
            sticky = int(args[4])
        except ValueError:
            self.wfile.write('501 Invalid argument.\r\n')
            return

        if length > 0:
            data = self.rfile.read(length)
        else:
            data = None

        if uid == 0 and not self.server.check_perms('broadcast'):
            self.wfile.write('554 Broadcast permission denied.\r\n')
            return

        self.server.notify(uid, type, msgid, bool(sticky), data)
        self.wfile.write('200 Ok.\r\n')

    def cmd_USER(self, cmd, args):
        """USER <name | #uid>

        Begin authentication of a user.
        """
        if len(args) <> 1:
            self.wfile.write('501 Wrong number of arguments.\r\n')
            return

        # When a validation request begins, we connect to the DND
        # The presence of this connexion is a signal to the other
        # handlers here that a validation is in progress.
        try:
            self.dnd = dnd.DNDSession(debug=self.server.debug)
        except dnd.DNDError:
            self.wfile.write('450 Name directory unavailable.\r\n')
            return

        try:
            self.resp = self.dnd.begin_validate(args[0], 'uid')
        except dnd.DNDProtocolError, e:
            self.wfile.write('550 %s\r\n' % e.value)
            self.dnd.close()
            self.dnd = self.resp = None
            return

        self.wfile.write('300 %s\r\n' % self.resp[0])

    def cmd_PASE(self, cmd, args):
        """PASE <octal>

        Complete an authentication request with an encrypted response.
        Encoded in octal digits as per the DND protocol.
        """
        try:
            if len(args) <> 1:
                self.wfile.write('501 Wrong number of arguments.\r\n')
                return
            elif not re.match(r'[0-7]{24}$', args[0]):
                self.wfile.write('501 Invalid argument.\r\n')
                return

            try:
                result = self.resp[1](args[0], True)
                self.server.auth = int(result.uid)
                self._debug('@ Validated user: %s', result.uid)
                self.wfile.write('200 User validated.\r\n')
            except dnd.DNDProtocolError, e:
                self.wfile.write('551 %s\r\n' % e.value)
        finally:
            try:
                self.dnd.close()
            except dnd.DNDError, AttributeError:
                pass
            self.dnd = self.resp = None

    def cmd_PASS(self, cmd, args):
        """PASS <cleartext>

        Complete an authentication request with a cleartext password.
        This is not a recommended mode of operation, although the
        password is encrypted before being sent to the DND.
        """
        try:
            if len(args) <> 1:
                self.wfile.write('501 Wrong number of arguments.\r\n')
                return
            elif len(args[0]) > 8:
                self.wfile.write('501 Invalid argument.\r\n')
                return

            try:
                pw = dnd.encrypt_challenge(self.resp[0], args[0])
                result = self.resp[1](pw, True)
                self.server.auth = int(result.uid)
                self._debug('@ Validated user: %s', result.uid)
                self.wfile.write('200 User validated.\r\n')
            except dnd.DNDProtocolError, e:
                self.wfile.write('551 %s\r\n' % e.value)
        finally:
            try:
                self.dnd.close()
            except dnd.DNDError, AttributeError:
                pass
            self.dnd = self.resp = None

    def cmd_CLIENT(self, cmd, args):
        """CLIENT <uid>,<ip>,<port>,<svcs,...>

        Add a new client to the list of registered clients.  This is a
        nonstandard extension to the notification protocol.  It
        requires that the "add" permission be available.
        """
        if not self.server.check_perms('client'):
            self.wfile.write('554 Permission denied.\r\n')
            return

        if len(args) < 4:
            self.wfile.write('501 Wrong number of arguments.\r\n')
            return

        uid, ip, port = args[:3]
        svcs = args[3:]

        try:
            r_uid = int(uid)
            r_svcs = tuple(int(s) for s in svcs)
            r_port = int(port)
        except ValueError:
            self.wfile.write('501 Invalid argument.\r\n')
            return

        self.server.add_client(r_uid, ip, r_port, r_svcs)
        self.wfile.write('200 Ok.\r\n')

    def cmd_LIST(self, cmd, args):
        """LIST <notices | clients | all>
        
        Return a list of all known notices, clients, or both.  This is
        a nonstandard extension to the standard notification protocol.
        It requires that the "list" permission be held by the current
        user.
        """
        if not self.server.check_perms('list'):
            self.wfile.write('554 Permission denied.\r\n')
            return

        if len(args) <> 1:
            self.wfile.write('501 Wrong number of arguments.\r\n')
            return

        key = args[0].lower()
        if key not in ('notices', 'clients', 'all'):
            self.wfile.write('501 Invalid list selector.\r\n')
            return

        if key in ('notices', 'all'):
            notes = self.server.notices()
            self.wfile.write('101 %d\r\n' % len(notes))
            for note in notes:
                self.wfile.write('110 %s,%s,%s,%s,"%s"\r\n' %
                                 (note.uid, note.type, note.msgid,
                                  (note.sticky and "1" or "0"),
                                  str(note.data or '').replace('"', '""')))
            self.wfile.write('200 Ok.\r\n')
        if key in ('clients', 'all'):
            clients = self.server.clients()
            self.wfile.write('101 %d\r\n' % len(clients))
            for client in clients:
                self.wfile.write('110 %s,%s,%s,%s %s\r\n' %
                                 (client.uid, client.ip, client.port, ','.join(
                                     str(s)
                                     for s in client.svcs), int(client.age())))
            self.wfile.write('200 Ok.\r\n')

    def _debug(self, fmt, *args):
        self.server._debug(fmt, *args)

    def handle(self):
        """Provides the required interface for SocketServer.  This
        implementation dispatches commands to .cmd_XXX() methods based
        on the first word of each command line received from the
        client.
        """
        try:
            self.wfile.write('220 Notification server ready.\r\n')
            self.quit = False
            self.dnd = None
            self.resp = None
            while not self.quit:
                line = self.rfile.readline().rstrip().split(' ', 1)
                cmd = line[0]
                args = (len(line) > 1 and re.split(r', *', line[1])) or []
                hname = 'cmd_%s' % cmd.upper()

                # Special case to avoid replication of protocol sequencing
                if cmd.upper() not in ("PASS", "PASE") and \
                   self.dnd is not None:
                    self.wfile.write('503 Bad sequence of commands.\r\n')
                    try:
                        self.dnd.close()
                    except dnd.DNDError:
                        pass
                    self.dnd = self.resp = None
                else:
                    getattr(self, hname, self.cmd_unknown)(cmd, args)
        except socket.error, e:
            pass

        self.wfile.close()
        self.rfile.close()


# }}

# {{ class NotifyUDPServer


class NotifyUDPServer(ATPObject):
    """Implements the UDP interface of a BlitzMail notification server.
    """

    def __init__(self, db, port=2154, maxage=600, debug=False):
        """Construct a notification server on the local host at the
        specified port number.
        
        port    -- UDP port to listen for requests.
        db      -- database of sticky notifications.
        maxage  -- maximum client age, in seconds.
        debug   -- display debugging output?
        """
        super(NotifyUDPServer, self).__init__(port, debug)

        self.db = db  # Sticky notifications
        self._clients = []  # Registered clients
        self._clm = threading.Lock()  # Mutex for clients list

        # The maximum length of time, in seconds, between the last
        # time a message was sent to a client and the last time a
        # message was received from a client.  Clients exceeding this
        # limit are removed from the table.
        self._maxage = maxage

    def stop(self):
        """As ATPObject.stop(), but send reset messages to all clients
        before shutting down.
        """
        self._clm.acquire()
        for elt in self._clients:
            self.reset(elt)
        self._clm.release()

        # Give clients a chance to respond, but don't worry too much
        # if they aren't able to do it.
        time.sleep(1)

        super(NotifyUDPServer, self).stop()  # Important!

    def add_client(self, uid, ip, port, svcs):
        """Add a (possibly) new client to the client table.  Returns
        the Client object corresponding to the client -- either an old
        one, or a new one.
        """
        new_client = Client(uid, ip, port, svcs)
        new_client.sendmark()  # Not really, but very soon.
        new_client.recvmark()
        self._clm.acquire()
        try:
            pos = self._clients.index(new_client)
            out = self._clients[pos]
            out.recvmark()
        except ValueError:
            self._clients.append(new_client)
            out = new_client

        self.send_sticky(out)
        self._clm.release()
        return out

    def do_req(self, flags, seq, tid, udata, pdata, sndr):
        """Handle incoming request packets from clients.
        
        Requests understood:
           NR02    -- register a new notification client.
           CLEN    -- clear sticky notifications.
        """
        if udata == "NR02":
            uid, port, svcs = parse_register_req(pdata)

            # Protocol: If the client specifies port 0, we will use
            # whatever port number was in their packet.  This allows
            # the notification protocol to work through simple NATs.
            if port == 0:
                port = sndr[1]

            self.add_client(int(uid[1:]), sndr[0], port, svcs)
            return True
        elif udata == "CLEN":
            uid, service = parse_clear_req(pdata)
            self.clear_sticky(uid, service)

            return True
        else:
            return False

    def do_rsp(self, tobj):
        """Handle responses from clients.  Here we just mark the
        sender as fresh.
        """
        ip, port = tobj.addr()
        self.update(ip, port)
        return True

    def do_rel(self, tobj):
        """Handle responses from clients.  Here we just mark the
        sender as fresh.
        """
        ip, port = tobj.addr()
        self.update(ip, port)
        return True

    def write_poll(self):
        """When the writer polls, check for clients that have not been
        heard from in a long time, and remove them.
        """
        self._clm.acquire()
        try:
            dead = list(pos for pos, elt in enumerate(self._clients)
                        if elt.age() > self._maxage)

            for pos in reversed(dead):
                self._debug('! Removing stale client %s (%d..%d)',
                            self._clients[pos], int(self._clients[pos].smark),
                            int(self._clients[pos].rmark))
                self._clients.pop(pos)
        finally:
            self._clm.release()

    def update(self, ip, port):
        """Update the clients list for a message received from the
        given address.
        """
        self._clm.acquire()
        try:
            for elt in self._clients:
                if elt.ip == ip and elt.port == port:
                    elt.recvmark()
        finally:
            self._clm.release()

    def send_sticky(self, client):
        """Send sticky notifications to the specified client."""
        for notice in self.db.notices():
            if notice.uid in (0, client.uid) and notice.type in client.svcs:
                self._addreq(Notify, notice.uid, notice.type, notice.msgid,
                             notice.data, client.addr())
                client.sendmark()

    def post(self, notice):
        """Enqueue a notification request for transmission."""
        if not isinstance(notice, Notice):
            raise TypeError("First parameter must be a Notice")

        self._clm.acquire()
        for elt in self._clients:
            if notice.uid in (0, elt.uid) and notice.type in elt.svcs:
                self._addreq(Notify, notice.uid, notice.type, notice.msgid,
                             notice.data, elt.addr())
                elt.sendmark()
        self._clm.release()

    def clear_sticky(self, uid, service):
        """Process a request to clear sticky notifications.
        
        uid      -- the user ID for whom to clear.
        service  -- the service tag to be cleared.
        """
        self.db.cleartype(uid, service)

    def reset(self, client):
        """Enqueue a reset request for transmission."""
        if not isinstance(client, Client):
            raise TypeError("Parameter must be a Client")

        self._addreq(Reset, client.addr())

    def clients(self):
        """Retrieve a list of all registered clients.
        """
        self._clm.acquire()
        result = self._clients[:]
        self._clm.release()

        return result


# }}

# {{ class NoticeDB


class NoticeDB(object):
    """A persistent database of sticky notifications."""

    def __init__(self, path):
        """Create or open the specified database.  If the notices
        table does not already exist, it is created.

        path   -- where the database resides.

        See also:  pysqlite2.dbapi2
        """
        self.db = sql.connect(path, check_same_thread=False)

        cur = self.db.cursor()
        cur.execute("PRAGMA table_info(notices)")
        if cur.fetchone() is None:
            cur.execute("""CREATE TABLE notices
            ( uid INT, type INT, msgid INT, data TEXT )""")
            self.db.commit()

    def enter(self, uid, type, msgid, data):
        """Enter a new notice in the database.

        See also:  class Notice
        """
        cur = self.db.cursor()
        cur.execute(
            """INSERT INTO notices (uid, type, msgid, data)
        VALUES (?, ?, ?, ?)""", (uid, type, msgid, data))
        cur.close()
        self.db.commit()

    def notices(self):
        """Return a list of all the notices in the database.

        See also:  class Notice
        """
        cur = self.db.cursor()
        cur.execute("""SELECT *, rowid FROM notices""")
        result = [
            Notice(uid, type, msgid, True, data, rowid)
            for (uid, type, msgid, data, rowid) in cur.fetchall()
        ]
        cur.close()
        return result

    def cleartype(self, uid, type):
        """Remove all entries from the database whose UID and type
        code match the specified values.

        uid    -- User ID (int)
        type   -- Notification type (int)
        """
        cur = self.db.cursor()
        cur.execute(
            """DELETE FROM notices
        WHERE uid == ? AND type == ?""", (uid, type))
        cur.close()
        self.db.commit()

    def flush(self):
        """Remove all entries from the database."""
        cur = self.db.cursor()
        cur.execute("""DELETE FROM notices""")
        cur.close()
        self.db.commit()

    def close(self):
        """Close the database connexion."""
        if self.db is not None:
            self.db.close()
            self.db = None

    def __del__(self):
        self.close()


# }}

# {{ class NotifyTCPServer


class NotifyTCPServer(ThreadingTCPServer):
    """Implements the TCP notification interface.

    See also:  class NotifyTCPHandler
    """

    def __init__(self,
                 db,
                 udp=None,
                 host=None,
                 port=2152,
                 admin=None,
                 debug=False):
        """Create a new server instance.
        
        db    -- NoticeDB instance for sticky notifications.
        udp   -- UDP server object (or None).
        host  -- hostname or IP to listen on.
        port  -- TCP port to listen on.
        admin -- ID of privileged user.
        debug -- enable debugging output?
        """
        if host is None:
            host = '0.0.0.0'  # Whatever's available locally

        self.db = db  # Database of sticky notices
        self.udp = udp  # UDP server
        self.auth = None  # Currently authenticated user, if any
        self.run = False  # Currently running?
        self.adm = admin  # Privileged user ID, if any

        self.debug = debug

        ThreadingTCPServer.__init__(self, (host, port), NotifyTCPHandler)

    def _debug(self, fmt, *args):
        if self.debug:
            print >> sys.stderr, fmt % args

    def start(self):
        """Start up the server.  If a UDP service is known, it is also
        started.
        """
        if self.udp is None:
            self._debug('@ UDP service unavailable')
        else:
            self._debug('@ Starting up UDP service')
            self.udp.start()

        self._debug('@ Activating TCP service')
        self.server_activate()

        self.run = True
        try:
            while self.run:
                self.handle_request()
        except KeyboardInterrupt:
            self._debug('@ Interrupt received, closing down')
            self.run = False

        self._debug('@ Closing down TCP service')
        self.server_close()
        if self.udp is None:
            self._debug('@ UDP service unavailable')
        else:
            self._debug('@ Closing down UDP service (takes a moment)')
            self.udp.stop()

    def check_perms(self, operation):
        if operation not in ('list', 'broadcast'):
            return True

        return (self.adm is not None and \
                self.auth == self.adm)

    def clear(self, uid, type):
        """Clear sticky notifications for the specified user and type."""
        self._debug('@ Clearing sticky notifications for UID %s, type %s', uid,
                    type)
        self.db.cleartype(uid, type)

    def notices(self):
        """Return a list of available notifications."""
        return self.db.notices()

    def clients(self):
        """Return a list of registered clients."""
        if self.udp is None:
            return []
        else:
            return self.udp.clients()

    def add_client(self, uid, ip, port, svcs):
        """Register a new client with the UDP service."""
        if self.udp is not None:
            self.udp.add_client(uid, ip, port, svcs)

    def notify(self, uid, type, msgid, sticky, data):
        """Enter a new notification with the specified parameters.

        uid    -- user ID (int).
        type   -- notification type (int).
        msgid  -- message ID (int).
        sticky -- is notice persistent? (bool).
        data   -- message content (str or None).
        """
        self._debug('@ New notification for UID %s, type %s, msgid %s', uid,
                    type, msgid)
        if sticky:
            self._debug('@ - Entering notification in sticky database')
            self.db.enter(uid, type, msgid, data)

        if self.udp is not None:
            self._debug('@ - Posting notification to UDP clients')
            self.udp.post(Notice(uid, type, msgid, sticky, data))


# }}

# {{ main(argv)


def main(argv):
    """Main driver for notify daemon command line tool."""
    import getopt

    def usage(help=False):
        print >> sys.stderr, \
              "Usage: notifyd [options] db-file"
        if help:
            print >> sys.stderr, \
"""
Options include:
  -a/--admin <uid>  : privileged user ID
  -t/--tcp <port>   : port for TCP service
  -u/--udp <port>   : port for UDP service
  -d/--debug        : enable debugging output
  -h/--help         : display this help message
"""
        else:
            print >> sys.stderr, "       [use notifyd --help for options]\n"

    # System defaults
    tcp_port = 2152
    udp_port = 2154
    admin_uid = None
    debug = False

    try:
        opts, args = getopt.getopt(argv, 'a:dht:u:',
                                   ('admin=', 'help', 'tcp=', 'udp=', 'debug'))
    except getopt.GetoptError, e:
        print >> sys.stderr, "Error: %s" % e
        usage(False)
        return

    for opt, val in opts:
        if opt in ('-t', '--tcp'):
            tcp_port = int(val)
        elif opt in ('-u', '--udp'):
            udp_port = int(val)
        elif opt in ('-d', '--debug'):
            debug = True
            print >> sys.stderr, "[debugging output enabled]"
        elif opt in ('-a', '--admin'):
            admin_uid = int(val)
        elif opt in ('-h', '--help'):
            usage(True)
            return

    if len(args) == 0:
        usage(True)
        return
    else:
        db_path = args[0]

    udp_server = NotifyUDPServer(NoticeDB(db_path), port=udp_port, debug=debug)
    tcp_server = NotifyTCPServer(
        NoticeDB(db_path),
        udp=udp_server,
        port=tcp_port,
        admin=admin_uid,
        debug=debug)
    tcp_server.start()


# }}

if __name__ == "__main__":
    main(sys.argv[1:])

__all__ = ["NotifyTCPServer", "NotifyUDPServer", "NoticeDB"]

# Here there be dragons
