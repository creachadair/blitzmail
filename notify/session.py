##
## Name:     session.py
## Purpose:  Implements the TCP notification client protocol.
##
## Copyright (C) 2004-2006 Michael J. Fromberger, All Rights Reserved.
##

from BlitzMail.session import Session
from BlitzMail.berror import SessionError
from Crypto.Cipher import XOR
from packet import NOTIFY_SERVICE
import dnd, errno, socket, sys, time

default_notify_port = 2152  # Where to contact the BlitzNotify server


class NotifySession(Session):
    """This class represents an open session with the TCP interface to
    a BlitzNotify server.

    To sign on, construct a new instance, optionally providing the
    name and port of the notify server, then use the .sign_on()
    method. To disconnect, use .close().  To reconnect the same user,
    use .reconnect().
    """
    def __init__(self,
                 server=None,
                 port=default_notify_port,
                 dnd=None,
                 debug=False,
                 pw_env=None):
        """Creates a new session associated with the specified notify
        server.
        """
        super(NotifySession, self).__init__()

        if debug:
            self._dflag = debug

        self.dnd_host = dnd  # Where to find the DND server
        self.not_host = server  # Notification host to connect to
        self.not_port = port  # Port to talk to notify service
        self.user_info = None  # User data, if any

    def close(self, flush=False):
        """Send the QUIT command to the notify server, and close the
        session.  Retains user information unless flush = True.
        """
        if self.is_connected():
            try:
                self._cmd0("QUIT")
                self._expect(221)
                self._conn.shutdown(2)
            except (socket.error, SessionError):
                pass  # Ignore errors when attempting to close

            super(NotifySession, self).close()

        if flush:
            self.user_info = None

    def sign_on(self, user, pw):
        """Sign on to the notify server as the specified user.  
        
        If pw is set to None, and the pw_env parameter of the
        constructor was set to a string, then the contents of that
        environment variable will be used as the password, instead of
        the pw value.  However, if pw is set, then it overrides that
        behaviour.
        """
        if self.is_connected():
            raise ValueError("session is connected")

        # If not provided explicitly try to load the user password
        # from the environment; complain if this fails.
        if pw is None and self.pw_env:
            pw = os.getenv(self.pw_env)
            if pw is None:
                raise SessionError("unable to obtain password")

            self.dprint('[loaded password from %s]', self.pw_env)

        # Cache the user's info for later use.  The password is
        # lightly scrambled to reduce the likelihood or shoulder
        # surfing attacks on the password during development.
        if self.not_host is None:
            self.user_info = {'pw': XOR.new('\x35').encrypt(pw)}
            if self.dnd_host is None:
                name_dir = dnd.DNDSession()
            else:
                name_dir = dnd.DNDSession(self.dnd_host)

            info = name_dir.lookup_unique(user, 'name', 'uid', 'notifyserv')
            name_dir.close()
            if not info:
                raise SessionError("no unique match for user '%s'" % user)
            self.user_info.update(info)
            self.user_info['blitzserv'] = info.notifyserv.split('@')[0]
        else:
            self.user_info['name'] = user
            self.user_info['notifyserv'] = self.not_host

        self.reconnect()

    def connect(self, server):
        """Connect to the notification server, but do not sign on.
        See .sign_on() if you want to authenticate.
        """
        self.user_info = None
        self.reconnect(server)

    def reconnect(self, server=None):
        """Re-connect to the notification server with the current user
        info, if available.
        """
        if server is None and self.user_info is None:
            raise ValueError("no server specified and no user information")

        # Make sure any old connexion is killed first
        self.close()

        # Establish a connexion to the specified notify server
        if server is None:
            server = self.user_info['notifyserv']
        try:
            self._saddr = (socket.gethostbyname(server), default_notify_port)
            self._conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._conn.connect(self._saddr)
        except socket.error as e:
            raise SessionError(str(e))

        self._input = self._conn.makefile()

        # Eat welcome banner, mmm, tasty!
        self._expect(220)

        # Sign-on protocol:  -> USER, <- challenge, -> response, <- Ok
        # But only do this if the user actually wants to sign on
        if self.user_info is not None:
            if 'uid' in self.user_info:
                self._cmd1('USER', '#' + self.user_info['uid'])
            else:
                self._cmd1('USER', self.user_info['name'])

            key, data = self._expect(300)

            response = dnd.encrypt_challenge(
                data,
                XOR.new('\x35').decrypt(self.user_info['pw']))

            self._cmd1('PASE', response)
            self._expect(200)

    def clear_sticky(self, type, uid=None):
        """Clear sticky notifications of the specified type for the
        given user.  If none is specified, the ID of the currently
        signed-on user is supplied.
        
        Notification types include:
        'mail'     -- e-mail notifications (BlitzMail).
        'bulletin' -- bulletin notifications.
        'talk'     -- talk requests (DoubleSpeak).
        """
        if uid is None and not self.user_info:
            raise ValueError("No user info available and no UID specified")

        id = (uid is None and self.user_info.get('uid')) or int(uid)
        try:
            type = NOTIFY_SERVICE[type]
        except KeyError:
            if isinstance(type, (int, long)):
                type = int(type)
            else:
                raise ValueError("Unknown service code: %s" % type)

        self._cmd2('CLEAR', str(id), str(type))
        self._expect(200)

    def add_client(self, uid, ip, port, svcs):
        """Tell the server to add a new client to its registry.  This
        is a nonstandard extension to the notification service, and
        will not work with stock Dartmouth notification servers.
        
        uid     -- user ID client is interested in.
        ip      -- IP address or hostname of client.
        port    -- port number client is listening to.
        svcs    -- list of notification types desired by client.
        """
        codes = []
        for svc in svcs:
            try:
                codes.append(NOTIFY_SERVICE[svc])
            except KeyError:
                if isinstance(svc, (int, long)):
                    codes.append(int(svc))
                else:
                    raise ValueError("Unknown service code: %s" % svc)

        arg = ','.join((str(uid), str(ip), str(port)) +
                       tuple(str(s) for s in codes))
        self._cmd1('CLIENT', arg)
        self._expect(200)

    def post_notify(self, type, data=None, uid=None, msg_id=None, sticky=True):
        """Post a new notification of the specified type.  The uid is
        taken from the current connexion, if not specified.  Data may
        be a string of up to 255 characters to be transmitted along
        with the notification.
        """
        if uid is None and not self.user_info:
            raise ValueError("No user info available and no UID specified")

        id = (uid is None and self.user_info.get('uid')) or int(uid)
        try:
            type = NOTIFY_SERVICE[type]
        except KeyError:
            if isinstance(type, (int, long)):
                type = int(type)
            else:
                raise ValueError("Unknown service code: %s" % type)

        if data is None:
            data = '\x00'
        elif type != 0:
            if len(data) > 255:
                raise ValueError("Notification data too long (%d, max 255)" %
                                 len(data))
            data = chr(len(data)) + data  # Pascal-style string

        if msg_id is None:
            msg_id = int(time.time())

        arg = '%d,%s,%d,%d,%d' % (len(data), id, type, msg_id, int(
            bool(sticky)))

        self._cmd1('NOTIFY', arg)
        self._rawsend(data)
        return self._expect(200)[1]

    def post_reset(self, uid=None):
        """Post a reset control message.
        """
        return self.post_notify('reset',
                                data='\x00\x00\x00\x01',
                                uid=uid,
                                msg_id=0,
                                sticky=False)

    def keep_alive(self):
        """Send a NOOP to the server, to keep the connexion alive.
        """
        self._cmd0('NOOP')
        self._expect(200)


__all__ = ["NotifySession"]

# Here there be dragons
