##
## Name:     session.py
## Purpose:  An implementation of the BlitzMail protocol
##
## Copyright (C) 2004-2006 Michael J. Fromberger, All Rights Reserved.
##
## The main interface to a BlitzMail server is via the BlitzSession
## class.  This handles connecting to a server and authenticating a
## user, and is the main dispatch point for reading folders, message
## summaries, mailing lists, user preferences, and other data stored
## on the BlitzMail server.
##
__version__ = "1.8"

import dnd, errno, os, socket, sys
import bfold, blist, bmesg, bwarn
from berror import *
from Crypto.Cipher import XOR

# -- Library defaults
default_server_port = 2151  # TCP port for BlitzMail server
client_version_msg = "Python BlitzMail library v.%s" % __version__

##
## The session class defines generic behaviour for clients of
## line-oriented network services.  It is the base class for the
## BlitzSession and BulletinSession classes.


class Session(object):
    """This class represents an open client session with a
    line-oriented TCP server.

    You may subclass this object to implement specific functionality;
    this class provides only some basic infrastructure.
    """
    def __init__(self):
        """Set up a new unconnected session."""
        self._conn = None  # socket object
        self._input = None  # file stream associated with _conn
        self._saddr = None  # tuple (addr, port) for remote server

    def __del__(self):
        """Insures that the .close() method is called when the object
        is reclaimed by the memory management system.  Exceptions that
        result from the call to .close() are ignored.
        """
        self.dprint('[disposing of %s]', self)

        try:
            self.close()
        except:
            pass

    def dprint(self, msg, *args):
        """Log a debugging diagnostic message."""
        flag = getattr(self, '_dflag', None)
        if flag is not None and flag > 0:
            print >> sys.stderr, msg % args

    def is_connected(self):
        """Returns True if a connexion is established to a server;
        otherwise False.
        """
        return self._conn is not None

    def hostname(self):
        """Return the host name of the connected server."""
        if not self.is_connected():
            raise NotConnectedError("session is not connected")

        return socket.gethostbyaddr(self._saddr[0])[0]

    def close(self):
        """A generic close method.  Just shuts down the socket.
        Override in subclasses to send QUIT commands, etc."""
        if self.is_connected():
            self._close()

    def _close(self):
        """Low-level close method; shuts down the socket and fixes up
        the internal state variables.
        """
        try:
            self._conn.shutdown(2)
        except (socket.error, SessionError):
            pass

        self._conn = None
        self._input = None
        self._saddr = None

    # These methods are for internal use by subclasses
    def _cmd0(self, cmd):
        """Send a command with no arguments."""
        msg = cmd + "\n"
        self.dprint("<< %s", msg.rstrip())
        self._rawsend(msg)

    def _cmd1(self, cmd, arg):
        """Send a command taking one argument."""
        msg = cmd + " " + arg + "\n"
        self.dprint("<< %s", msg.rstrip())
        self._rawsend(msg)

    def _cmd2(self, cmd, arg1, arg2, sep=','):
        """Send a command taking two arguments, separated by sep."""
        msg = cmd + " " + arg1 + sep + arg2 + "\n"
        self.dprint("<< %s", msg.rstrip())
        self._rawsend(msg)

    def _cmd3(self, cmd, arg1, arg2, arg3, sep=','):
        """Send a command taking three arguments, separated by sep."""
        msg = cmd + " " + sep.join((arg1, arg2, arg3)) + "\n"
        self.dprint("<< %s", msg.rstrip())
        self._rawsend(msg)

    def _send(self, data):
        """Send a block of arbitrary data, not necessarily within the
        line-oriented cycle.  Be aware that incautious use may break
        the protocol timing.
        """
        self.dprint("<< [%d bytes]\n%s<*>", len(data), data)
        self._rawsend(data)

    def _rawsend(self, data):
        """Write directly to the low-level connection."""
        if not self.is_connected():
            raise NotConnectedError("session is not connected")
        try:
            self._conn.send(data)
        except socket.error, e:
            if e[0] == errno.EPIPE:
                self._close()
                raise LostConnectionError("Broken pipe")
            else:
                raise

    def _read(self, size):
        """Read a block of arbitrary data, not necessarily within the
        line-oriented cycle.  Be aware that incautious use may break
        the protocol timing, or wedge the session.
        """
        self.dprint('[reading %d bytes]', size)
        try:
            data = self._input.read(size)
        except socket.error, e:
            if e[0] == errno.ECONNRESET:
                self._close()
                raise LostConnectionError("connection closed by remote host")
        except AttributeError:
            raise NotConnectedError("session is not connected")

        self.dprint('>> [%d bytes]\n%s<*>\n', len(data), data)
        return data

    def _expect(self, *wanted):
        """This is the primary lockstep input reader; it fails with an
        exception if the response code does not match one of the given
        codes, assuming a line of the format returned by ._readline().
        """
        (key, data) = self._readline()

        if key not in wanted:
            raise ProtocolError(key, data)
        else:
            return (key, data)

    def _readline(self):
        """Read a single line of input from the server.  Input should
        be of the form

        CODE [DATA] EOLN

        The result is a tuple of (code, data), or an exception is
        raised indicating some other error.
        """
        try:
            line = self._input.readline()
        except socket.error, e:
            if e[0] == errno.ECONNRESET:
                self._close()
                raise LostConnectionError("connection closed by remote host")
            else:
                raise
        except AttributeError:
            raise NotConnectedError("session is not connected")

        if line == '':
            self._close()
            raise LostConnectionError("connection closed by remote host")

        key, data = line.split(' ', 1)
        key, data = int(key), data.rstrip()

        self.dprint('>> [%03d] %s', key, data)
        return key, data

    def _readlines(self):
        self.dprint('[reading multi-line data]')
        data = []
        while True:
            ln = self._input.readline().rstrip()
            if ln == '.':
                break

            data.append(ln)

        self.dprint('>> [%d lines]\n%s\n', len(data),
                    '\n'.join(data[:5]) + ' ...')
        return data


class BlitzSession(Session):
    """This class represents an open session with a BlitzMail server.

    A connected BlitzSession behaves like a sequence of folders, which
    may be iterated or indexed either by their ID numbers or their
    names, which are case-insensitive.

    Here is a summary of the various methods implementing features of
    the BlitzMail protocol.
    
    Connecting:       .sign_on(name, pw)
                      .reconnect()
                      .close()
    
    Sending mail:     .create_new_message()     BlitzOutboundMessage

    Handling folders: .get_folder(name/id)      BlitzFolder
                      .get_folders()
                      .create_folder(name)

    Mailing lists:    .get_group_lists()        BlitzList
                      .get_private_lists()
                      .get_group_list(name)
                      .get_private_list(name)

    Warnings:         .check_warnings()         BlitzWarning

    Summaries         see classes BlitzSummary, BlitzFolder

    Emptying trash:   .empty_trash()

    Preferences:      .read_pref(name)
                      .write_pref(name, value)
                      .get_session_id()
                      .get_last_login()
                      .get_forwarding()
                      .set_forwarding(addr)
    
    Emptying trash:   .empty_trash()
    
    Other:            .keep_alive()

    Vacation:         .get_vacation_msg()
                      .set_vacation_msg(text)
                      .clear_vacation_msg()
    """
    def __init__(self, dnd=None, pw_env=None, debug=False):
        """Creates a new unconnected BlitzMail session.

        dnd    -- hostname of Dartmouth Name Directory server (str).
        pw_env -- environment variable containing password (str).
        debug  -- flag to enable debugging output (if true).

        If omitted, a default DND server will be used.  If pw_env is
        not specified, the user's password must be specified when the
        session is connected (see .connect() and .sign_on()).
        """
        super(BlitzSession, self).__init__()

        if debug:
            self._dflag = debug

        self.dnd_host = dnd  # Host name of DND server, or None.
        self.warn_flag = False  # True if warnings are pending
        self.user_info = None  # Data about current user, if any
        self.pw_env = pw_env  # Environment variable holding password

        self.gl_cache = None  # Group mailing list cache
        self.pl_cache = None  # Private mailing list cache
        self.fl_cache = None  # Folder information cache
        self.session_id = None  # Current session ID cache
        self.blitzserv = None  # Server version message cache

    def close(self, flush=False):
        """Send the QUIT command to the BlitzMail server, and close
        the session.  Retains user information unless flush = True.
        """
        if self.is_connected():
            try:
                self._cmd0("QUIT")
                self._expect(10)
            except (socket.error, SessionError):
                pass

            super(BlitzSession, self).close()

        if flush:
            self.user_info = None

        self.warn_flag = False
        self.gl_cache = None
        self.pl_cache = None
        self.fl_cache = None
        self.session_id = None
        self.blitzserv = None

    def sign_on(self, user, pw, push_off=False):
        """Establish a connexion to a BlitzMail server for the
        specified user.  If a session is already connected, a
        ValueError is thrown; call .close() to shut down the existing
        session before calling .sign_on().

        The push_off value controls what happens if you attempt to
        sign on when the account is already in use.  See .reconnect()
        for more information on the use of this value.

        If pw is None, .sign_on() tries to load the user's password
        from the environment variable specified in the initializer.
        If no password is available, an exception is raised.

        user      -- user name (str)
        pw        -- password (str) or None
        push_off  -- boolean or callable
        """
        if self.is_connected():
            raise ValueError("session is established")

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
        self.user_info = {'pw': XOR.new('\x6A').encrypt(pw)}
        if self.dnd_host is None:
            name_dir = dnd.DNDSession()
        else:
            name_dir = dnd.DNDSession(server=self.dnd_host)

        info = name_dir.lookup_unique(user, 'name', 'uid', 'blitzserv')
        name_dir.close()
        if not info:
            raise SessionError("no unique match for user '%s'" % user)
        self.user_info.update(info)
        self.user_info['blitzserv'] = info.blitzserv.split('@')[0]

        self.reconnect(push_off)

    def reconnect(self, push_off=True):
        """Connect or reconnect to BlitzMail using the current cache
        of user info, if available.  If the cache is empty, ValueError
        is raised.

        The push_off parameter controls what happens when we try to
        connect to an account that is already in use.  In this case,
        the BlitzMail server sends back a message indicating the
        account is busy.  If push_off is a callable object, it is
        invoked with the message string as its argument.  If the
        result is a true value, the existing connection is dropped and
        our session is established; otherwise our session is abandoned
        and an exception is raised.

        If push_off is not callable, but is true, the old connection
        is dropped; if false, the current session is abandoned.
        """
        if self.user_info is None:
            raise ValueError("no user information, cannot reconnect")

        # Make sure any old connexion is killed first
        self.close()

        # Establish a connexion to the specified BlitzMail server
        try:
            self._saddr = (socket.gethostbyname(self.user_info['blitzserv']),
                           default_server_port)
            self._conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._conn.connect(self._saddr)
        except socket.error, e:
            raise SessionError(str(e))

        self._input = self._conn.makefile()
        self._cmd1('VERS', client_version_msg)
        key, data = self._expect(10)
        self.blitzserv = data

        # BlitzMail sign-on protocol:
        # C -> S:  UID#
        # S -> C:  challenge (24 octal digits)
        # C -> S:  PASE response (24 octal digits)
        # S -> C:  OK or error
        # May require a PUSH to disconnect a remote user.
        self._cmd1('UID#', self.user_info['uid'])
        key, data = self._expect(33)

        resp = dnd.encrypt_challenge(
            data,
            XOR.new('\x6A').decrypt(self.user_info['pw']))

        self._cmd1('PASE', resp)
        if not push_off:
            self._expect(30)
        else:
            key, data = self._expect(30, 34)

            if key == 34:  # Client already connected
                if callable(push_off):
                    push_off = push_off(data)

                if push_off:
                    self._cmd0('PUSH')
                    self._expect(10)
                else:
                    self.close()
                    raise ProtocolError(key, data)

    def write_log_message(self, msg):
        """Write a message to the server log, if logging is supported.
        The message must be a single line, no vertical whitespace."""

        self._cmd1('SLOG', msg)
        self._expect(10, 14)  # Logging may not be available, but that's OK

    def check_warnings(self):
        """Check for pending warnings.  Returns a list of BlitzWarning
        objects.  This list is empty if there were no warnings.
        """
        warn_map = {
            61: bwarn.BlitzUnreadWarning,
            62: bwarn.BlitzMessageWarning,
            63: bwarn.BlitzShutdownWarning,
            66: bwarn.BlitzNewMailWarning
        }

        out = []
        self._cmd0('WARN')
        exp = [60] + warn_map.keys()

        while True:
            key, data = self._expect(*exp)
            if key == 60:
                break

            out.append(warn_map[key](data))

        return out

    def get_group_lists(self, force=False):
        """Return a list of all available group mailing lists.  The
        results are cached.

        force  -- if true, flush and reload the cache
        """
        if self.gl_cache and not force:
            return self.gl_cache.values()

        out = []
        self.gl_cache = {}
        self._cmd1('LSTS', '2')
        key, data = self._expect(00, 01, 02)
        if key == 2:
            return out

        while key != 0:
            lname, access = data.split(',')
            out.append(blist.BlitzGroupList(self, lname, access))
            key, data = self._expect(00, 01)

        lname, access = data.split(',')
        out.append(blist.BlitzGroupList(self, lname, access))

        for lst in out:
            self.gl_cache[lst.name.lower()] = lst

        return out

    def get_group_list(self, name, force=False):
        """Look up a group list by name.  Returns a BlitzGroupList
        object.

        name   -- the name of the list
        force  -- if true, force a reload of the list cache
        """
        if force or self.gl_cache is None:
            self.get_group_lists(force)
        return self.gl_cache[name.lower()]

    def create_group_list(self, name):
        """The same as get_group_list(), but if the list does not yet
        exist, a new empty list is created.  Nothing actually happens
        on the server until you set the members of the list.

        name     -- name of the group list to be created.

        Returns:   A new BlitzGroupList object.
        See also:  class BlitzList, class BlitzGroupList
        """
        try:
            return self.get_group_list(name)
        except KeyError:
            lst = blist.BlitzGroupList(self, name, None)  # Permissions unkown
            lst.fresh = True
            self.gl_cache[name.lower()] = lst
            return lst

    def get_private_lists(self, force=False):
        """Returns the list of available private mailing lists.

        force    -- if true, force reload of list cache
        """
        if self.pl_cache and not force:
            return self.pl_cache.values()

        out = []
        self.pl_cache = {}
        self._cmd1('LSTS', '1')
        (key, data) = self._expect(00, 01, 02)
        if key == 2:
            return out

        while key != 0:
            out.append(blist.BlitzPrivateList(self, data))
            (key, data) = self._expect(00, 01)

        out.append(blist.BlitzPrivateList(self, data))

        for lst in out:
            self.pl_cache[lst.name.lower()] = lst

        return out

    def get_private_list(self, name, force=False):
        """Returns a BlitzPrivateList object representing the private
        list whose name is specified.
        
        name     -- name of list
        force    -- if true, force reload of list cache
        """
        if force or self.pl_cache is None:
            self.get_private_lists(force)
        return self.pl_cache[name.lower()]

    def create_private_list(self, name):
        """The same as get_private_list(), but if the list does not
        exist, a new empty list is created.  Nothing actually happens
        on the server until you set the members of the list.

        name     -- the name of the list to create or load.
        """
        try:
            return self.get_private_list(name)
        except KeyError:
            lst = blist.BlitzPrivateList(self, name)
            lst.fresh = True
            self.pl_cache[name.lower()] = lst
            return lst

    def get_folders(self, force=False):
        """Return a list of BlitzFolder objects representing the various
        folders associated with the current session.

        force  -- if true, force a reload of the folder cache
        """
        if self.fl_cache and not force:
            return self.fl_cache

        out = []
        self._cmd0('FLIS')
        (key, data) = self._expect(00, 01)
        while key != 0:
            out.append(bfold.BlitzFolder(self, info=data))
            key, data = self._expect(00, 01)

        out.append(bfold.BlitzFolder(self, info=data))

        self.fl_cache = out
        return out

    def get_folder(self, name_or_id, force=False):
        """Fetch the folder whose name (str) or id (int) is specified.
        If force is true, a reload of the cache is forced.  Raises an
        error if the specified folder doesn't exist.
        """
        if isinstance(name_or_id, str):
            for fld in self.get_folders(force):
                if fld.name.lower() == name_or_id.lower():
                    return fld

            raise IndexError("no folder named `%s'" % name_or_id)
        elif isinstance(name_or_id, int):
            for fld in self.get_folders(force):
                if fld.id == name_or_id:
                    return fld

            raise IndexError("no folder with id `%d'" % name_or_id)
        else:
            raise ValueError("folders are identified by name or index")

    def create_folder(self, name):
        """Define a new folder on the BlitzMail server, and return a
        BlitzFolder object to represent it.
        """
        self._cmd1('FDEF', dnd.enquote_string(name))
        (key, data) = self._expect(00)

        self.fl_cache = None
        return bfold.BlitzFolder(self, id=data)

    def empty_trash(self):
        """Empty the "Trash" folder on the BlitzMail server.
        """
        self._cmd0('TRSH')
        self._expect(10)
        self.get_folder('trash').touch()

    def keep_alive(self):
        """Send a NOOP command to the BlitzMail server.  This keeps
        the connexion alive, in case you are leaving a session open
        for a long period of time.  It also polls for warnings (e.g.,
        new mail).
        """
        self._cmd0("NOOP")
        self._expect(10)

    def set_vacation_msg(self, data):
        """Set up a vacation message on the server.

        data     -- the body of the vacation message (str).
        """
        self._cmd1('VDAT', str(len(data)))
        self._expect(50)
        self._send(data.replace('\n', '\r'))
        self._expect(10)

    def get_vacation_msg(self):
        """Retrieve a vacation message, if it is available.  Returns
        None if no vacation message is defined.
        """
        self._cmd0('VTXT')
        (key, data) = self._expect(02, 50)

        if key == 2:
            return None

        data = self._read(int(data))
        self._expect(10)

        return data.replace('\r', '\n')

    def clear_vacation_msg(self):
        """Remove a vacation message, if present.  Returns True if the
        message was there, and is now gone; False if it was absent.
        """
        self._cmd0('VREM')
        (key, data) = self._expect(02, 10)

        return (key == 10)

    def get_session_id(self):
        """Get the current session ID.
        """
        if self.session_id is None:
            id = self.read_pref('SessionId')['SessionId']
            self.session_id = int(id)

        return self.session_id

    def get_last_login(self):
        """Get the time at which this session was connected.
        """
        return self.read_pref('LastLogin')['LastLogin']

    def get_forwarding(self):
        """Retrieve the current forwarding address.  If forwarding is
        not enabled, returns False.
        """
        fw = self.read_pref('ForwardTo')['ForwardTo']
        if fw in ('', None):
            return False
        else:
            return fw

    def set_forwarding(self, addr):
        """Set a forwarding address on the account.  By convention,
        forwarding is handled by defining a "ForwardTo" preference;
        not all BlitzMail servers honour this convention.  This
        implementation does not check.

        If the specified forward address is a false value, forwarding
        is disabled by removing the ForwardTo preference.
        """
        if not addr:
            self.remove_pref('ForwardTo')
        else:
            self.write_pref('ForwardTo', addr)

    def _munge_pref(self, op, names):
        """Private function for reading or removing a collection of
        preferences in one transaction.

        op    -- command to send to the server (e.g., PREF, PDEF)
        names -- a sequence of preference names to be munged

        Returns a dictionary in which each name is mapped to the value
        of the preference, or to None if the preference is undefined.
        """
        if len(names) == 0:
            raise ValueError("names may not be empty")

        out = {}
        self._cmd1(op, ' '.join(names))

        while True:
            key, data = self._expect(00, 01, 02, 03)

            if key in (00, 01):
                out[names[len(out)]] = data
            elif key in (02, 03):
                out[names[len(out)]] = None

            if key in (00, 02):
                break

        return out

    def read_pref(self, *names):
        """Read the specified preferences.  Each preference is
        specified as a string giving the name of the preference
        to be read.
        """
        out = self._munge_pref('PREF', names)

        # Fix up quoted strings
        for key in out.keys():
            if out[key] is not None:
                out[key] = out[key][1:-1].replace('""', '"')

        return out

    def remove_pref(self, *names):
        """Remove the specified preference names.  Each preference is
        specified as a string giving the name of the preference to be
        removed.
        """
        return self._munge_pref('PREM', names)

    def write_pref(self, name, value):
        """Write or create a single preference value.

        name     -- the name of the preference to write (str).
        value    -- the value of the preference (str)
        """
        name = '"' + name.replace('"', '""') + '"'
        value = '"' + value.replace('"', '""') + '"'

        self._cmd2('PDEF', name, value, sep=' ')
        self._expect(10)

    def create_new_message(self):
        """Initiate a new outbound message.  Note: This clears any
        previously initiated message, even if it has not yet been
        sent!

        See also:  class BlitzOutboundMessage
        """
        return bmesg.BlitzOutboundMessage(self)

    def __len__(self):
        """Returns the number of folders defined in the account for the
        currently signed-on user.
        """
        return len(self.get_folders())

    def __iter__(self):
        """Iterate over the folders defined in the account for the
        currently signed-on user.
        """
        return iter(self.get_folders())

    def __getitem__(self, key):
        """Look up a folder by name or by ID number.
        """
        return self.get_folder(key)

    def _expect(self, *wanted):
        """Overrides the version of ._expect() inherited from Session,
        to check response codes and set the warning flag.
        """
        key, data = self._readline()

        flag = (key / 100)
        value = key % 100

        if value not in [(k % 100) for k in wanted]:
            raise ProtocolError(key, data)
        else:
            self.warn_flag = (flag != 0)
            return value, data


# }}

__all__ = ["Session", "BlitzSession", "__version__"]

# Here there be dragons
