##
## Name:    bulls.py
## Purpose: Classes representing bulletin summaries and data.
##
## Copyright (C) 2004-2006 Michael J. Fromberger, All Rights Reserved.
##
## Some BlitzMail installations (notably, the original at Dartmouth
## College) provide a "bulletin" service similar to local Usenet news
## groups.  The main interface to a BlitzMail bulletins server is via
## the BulletinSession class.  This handles connecting to a server and
## authenticating a user, and is the main dispatch point for loading
## topics and message summaries, posting messages, and so forth.
##

import dnd, errno, re, socket, sys
import csv, re, time, weakref
from berror import *
from session import Session
from email import message_from_string
from os import getenv
from Crypto.Cipher import XOR

default_server_port = 1119  # Where to tap into a bulletin server

regex = type(re.compile(''))  # Used in BulletinSession


class Article(object):
    """This class represents a bulletin article."""
    def __init__(self, topic, id, xhead=None):
        """Create a new article given an ID number and optional
        summary header data."""

        self._topic = weakref.ref(topic)
        self.id = id
        self._xhead = self._parse_xhead(xhead)

    def _parse_xhead(self, data):
        if data is None:
            return {}

        out = {}
        for line in data:
            match = re.match('^([-\w]+): *(.+)$', line)
            if match:
                out[match.group(1).lower()] = match.group(2)

        return out

    def __repr__(self):
        return '#<Article ID %s in "%s">' % \
               (self.id, self._topic().name)

    def keys(self):
        """Return the available summary header keys."""
        return self._xhead.keys()

    def __getitem__(self, name):
        """Return summary header contents, None if header is undefined."""

        return self._xhead.get(name.lower())

    def select(self):
        """Select the group containing this bulletin, if needed."""

        self._topic().select()

    def header(self):
        """Return a list of header lines."""

        self.select()
        self._topic()._session()._cmd1('HEAD', str(self.id))
        self._topic()._session()._expect(221)

        return self._topic()._session()._readlines()

    def body(self):
        """Return a list of body lines."""

        self.select()
        self._topic()._session()._cmd1('BODY', str(self.id))
        self._topic()._session()._expect(222)

        return self._topic()._session()._readlines()

    def get_message(self, as_text=False):
        """Return the article as a message object."""

        self.select()
        self._topic()._session()._cmd1('ARTICLE', str(self.id))
        self._topic()._session()._expect(220)

        raw = str.join('\n', self._topic()._session()._readlines())
        if as_text:
            return raw
        else:
            return message_from_string(raw)

    def mark_read(self):
        """Mark this article as read."""

        self._topic()._rcache[int(self.id)] = True

    def mark_unread(self):
        """Mark this article as unread."""

        try:
            del (self._topic()._rcache[int(self.id)])
        except KeyError:
            pass

    def is_read(self):
        """Answer whether this article is read."""

        return int(self.id) in self._topic()._rcache


class Topic(object):
    """This class represents the various metadata about bulletins,
    such as their names, permissions, and article counts.
    """
    def __init__(self, session, init):
        self.name = None  # Usenet group name
        self.title = None  # Descriptive title for topic
        self.watch = None  # Y/N, user is monitoring this topic
        self.post = None  # Y/N, user can post to this topic

        # Synopsis of articles which have been read
        self._rcache = {}
        self.parseinfo(init)

        self.id_low = None  # Lowest available article ID
        self.id_high = None  # Highest available article ID
        self.last_id = None  # Last article ID seen
        self.info = None  # Last read info

        # This is true after .load() has been invoked.
        self._loaded = False

        # Cache of bulletin objects, once loaded
        self._bcache = None

        # Keep a weak reference back to the session for protocol work
        if session is None:
            self._session = None
        else:
            self._session = weakref.ref(session)

    def __str__(self):
        return '%s,"%s",%s,%s,%d-%d,%d,"%s"' % \
               (self.name, self.title, self.watch, self.post,
                self.id_low, self.id_high, self.last_id, self.info)

    def __len__(self):
        self.articles()
        return len(self._bcache)

    def __getitem__(self, key):
        """Return the article whose ID number is given."""
        key = str(key)

        for article in self.articles():
            if article.id == key:
                return article

        raise IndexError("No article matching id %s" % key)

    def keys(self):
        return [int(article.id) for article in self.articles()]

    def load(self, force=False):
        """Load information on this topic from the server, if needed.
        Set force = True to force a load even if it was already done."""

        if not self._loaded or force:
            self._session()._cmd1('BULL', self.name)
            self._session()._expect(290)
            self.parseinfo(self._session()._readlines())

    def update(self, id=None):
        """Update the last-seen ID and reader info on the server.
        Uses the existing information, if none is provided."""

        if id is None:
            id = self.last_id
        else:
            self.last_id = id

        info = self._make_read_list()
        if self.info:
            info += ";%s" % self.info

        self._session()._cmd1('UPDT', '%s,%d,"%s"' % (self.name, id, info))
        self._session()._expect(280)

    def monitor(self):
        """Indicate to the server that this topic should be monitored."""

        self._session()._cmd1('ADDB', self.name)
        self._session()._expect(240)
        self.load(True)

    def unmonitor(self):
        """Indicate to the server that this topic should not be monitored."""

        self._session()._cmd1('REMB', self.name)
        self._session()._expect(270)
        self.load(True)

    def parseinfo(self, s):
        """Load information from a string of the form returned by the
        bulletin server.  This marks the topic as "loaded" for the
        purposes of the .load() method."""

        if not isinstance(s, (list, tuple)):
            s = [s]

        data = csv.reader(s).next()
        (self.name, self.title, self.watch, self.post) = data[:4]
        (self.id_low, self.id_high) = \
                      [ int(x) for x in data[4].split('-') ]
        self.last_id = int(data[5])
        try:
            (read, self.info) = data[6].split(';', 1)
        except ValueError:
            read = data[6]
            self.info = ''

        # Populate the set of "read" article indices.
        for r in read.split(','):
            if r.find('-') >= 0:
                (lo, hi) = r.split('-')
                for id in xrange(int(lo), int(hi) + 1):
                    if id != 0:
                        self._rcache[id] = True
            elif r:
                r = int(r)
                if r != 0:
                    self._rcache[r] = True

        self._loaded = True

    def _make_read_list(self):
        """Compress the "read" table into a compact form."""

        for key in self._rcache.keys():
            if key < self.id_low:
                del self._rcache[key]

        id = self._rcache.keys()
        id.sort()

        out = []
        lo = 0
        while lo < len(id):
            hi = lo + 1

            while hi < len(id) and id[hi] == id[hi - 1] + 1:
                hi += 1

            if lo == hi - 1:
                out.append(str(id[lo]))
            else:
                out.append('%d-%d' % (id[lo], id[hi - 1]))

            lo = hi

        return str.join(',', (out or ['0-0']))

    def select(self, force=False):
        """Select this to be the active topic on the server, if
        needed.  Does the selection unconditionally, if force =
        True."""

        if self._session().g_select != self.name or force:
            self._session()._cmd1('GROUP', self.name)
            self._session()._expect(211)
            self._session().g_select = self.name

    def articles(self, force=False):
        """Return an iterator over Article objects."""

        if self._bcache is None or force:
            self._bcache = []

            self.load()
            self.select()
            self._session()._cmd1('XHEAD',
                                  '%d-%d' % (self.id_low, self.id_high))
            self._session()._expect(221)

            data = self._session()._readlines()
            self._bcache = []
            last = 0
            for pos in [x for x in xrange(len(data)) if data[x] == '']:
                self._bcache.append(
                    Article(self, data[last], data[last + 1:pos]))
                last = pos + 1

        return iter(self._bcache)

    def about(self):
        """Return the "About" text for this topic."""

        self._session()._cmd1('WHAT', self.name)
        self._session()._expect(200)

        return str.join('\n', self._session()._readlines())

    def __getattribute__(self, name):
        if name == 'read':
            self.load()
            return self._make_read_list()

        v = super(Topic, self).__getattribute__(name)
        if v is None and not name.startswith('_'):
            self.load()
            return super(Topic, self).__getattribute__(name)
        else:
            return v


# }}

## --- BulletinSession ----------------------------------------------------


class BulletinSession(Session):
    """This class represents an open session with the BlitzMail
    bulletin server.

    Construct a new instance, optionally providing the name of the DND
    to use for user-name resolution.  To sign on, use the .sign_on()
    method.  To disconnect, use .close().  To reconnect the same user,
    e.g., after another client has forced us off, use .reconnect()."""
    def __init__(self, dnd=None, pw_env=None, debug=False):
        """Creates a new session associated with the specified name
        directory (given as a hostname).  If omitted a default DND
        session will be used to look up user information."""
        super(BulletinSession, self).__init__()

        if debug:
            self._dflag = debug

        self.dnd_host = dnd  # Host name of DND server, or None.
        self.warn_flag = False  # True if warnings are pending
        self.user_info = None  # Data about current user, if any
        self.pw_env = pw_env  # Environment variable holding password
        self.bullserv = None  # Server version we're talking to
        self.t_cache = None  # Cache of topics
        self.g_select = None  # Last name sent to GROUP command

    def __len__(self):
        """Return the number of available bulletin topics."""

        self.get_topics()  # Make sure the cache is primed
        return len(self.t_cache)

    def __getitem__(self, key):
        """Look up a topic by name, and return a Topic object
        for it.  If the key is a string, the result is a single
        object; if the key is a regular expression object, the result
        is a list of strings, the names of the matching topics."""

        if isinstance(key, regex):
            return [name for name in self.get_topics() if key.search(name)]

        elif isinstance(key, basestring):
            self.get_topics()  # Make sure the cache is primed
            return self.t_cache[key.lower()]  # KeyError if it fails
        else:
            raise TypeError("Key must be a string or a regular expression")

    def __iter__(self):
        """Iterate over the bulletin topics on this server."""

        self.get_topics()  # Make sure the cache is primed
        return self.t_cache.itervalues()

    def get_topics(self, force=False):
        """Return a list of available bulletin topic names."""

        if self.t_cache is None or force:
            self._cmd0('LSTB')
            self._expect(260)
            lst = self._readlines()
            self.t_cache = {}
            for topic in [Topic(self, x) for x in lst]:
                self.t_cache[topic.name.lower()] = topic

        return self.t_cache.iterkeys()

    def close(self, flush=False):
        """Send the QUIT command to the BlitzMail server, and close
        the session.  Retains user information unless flush = True.
        """
        if self.is_connected():
            try:
                self._cmd0("QUIT")  # No response expected
            except (socket.error, SessionError):
                pass

            super(BulletinSession, self).close()

        if flush:
            self.user_info = None

        self.bullserv = None
        self.t_cache = None
        self.g_select = None

    def sign_on(self, user, pw):
        """Establish a connexion to a bulletin server for the
        specified user.  If a session is already connected, a
        ValueError is thrown; call .close() to shut down the existing
        session before calling .sign_on().

        If pw is None, .sign_on() tries to load the user's password
        from the environment variable specified in the initializer.
        If no password is available, an exception is raised.

        user      -- user name (str)
        pw        -- password (str) or None
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
        self.user_info = {'pw': XOR.new('\x9C').encrypt(pw)}
        if self.dnd_host is None:
            name_dir = dnd.DNDSession()
        else:
            name_dir = dnd.DNDSession(self.dnd_host)

        info = name_dir.lookup_unique(user, 'name', 'uid', 'bullserv')
        name_dir.close()
        if not info:
            raise SessionError("no unique match for user '%s'" % user)
        self.user_info.update(info)
        self.user_info['bullserv'] = info.bullserv.split('@')[0]

        self.reconnect()

    def new_topics(self):
        """Return a list of topic names which have new bulletins."""

        self.get_topics()  # Make sure cache is primed
        self._cmd0('NEWB')
        self._expect(290)

        return [t.split(',')[0] for t in self._readlines()]

    def server_time(self):
        """Return the time/date stamp from the server, as a string."""

        self._cmd0('TOD')
        (key, data) = self._expect(200)

        return data

    def subscribed(self):
        """Return a list of topic names to which user is subscribed."""

        return [t.name for t in self if t.watch == 'Y']

    def reconnect(self):
        """Connect or reconnect to the bulletin server using the
        current cache of user info, if available.  If the cache is
        empty, ValueError is raised.
        """
        if self.user_info is None:
            raise ValueError("no user information, cannot reconnect")

        # Make sure any old connexion is killed first
        self.close()

        # Establish a connexion to the specified Bulletin server
        try:
            self._saddr = (socket.gethostbyname(self.user_info['bullserv']),
                           default_server_port)
            self._conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._conn.connect(self._saddr)
        except socket.error as e:
            raise SessionError(str(e))

        self._input = self._conn.makefile()

        # Obtain welcome banner and server version information
        key, data = self._expect(200)
        self.bullserv = data

        # BlitzMail (and Bulletin) sign-on protocol:
        # C -> S:  UID#
        # S -> C:  challenge (24 octal digits)
        # C -> S:  PASE response (24 octal digits)
        # S -> C:  OK or error
        self._cmd1('UID#', self.user_info['uid'])
        key, data = self._expect(300)

        resp = dnd.encrypt_challenge(
            data,
            XOR.new('\x9C').decrypt(self.user_info['pw']))

        self._cmd1('PASE', resp)
        self._expect(210)

    def keep_alive(self):
        """Send a NOOP command to the bulletin server.  This keeps the
        connexion alive, in case you are leaving a session open for a
        long period of time.  It also polls for warnings (e.g., new
        mail)."""

        self._cmd0("NOOP")
        self._expect(0)


__all__ = ["BulletinSession"]

# Here there be dragons
