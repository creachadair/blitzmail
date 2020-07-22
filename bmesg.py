##
## Name:     bmesg.py
## Purpose:  BlitzMail message classes
##
## Copyright (C) 2004-2006 Michael J. Fromberger, All Rights Reserved.
##
## Message summaries represent a snapshot of message metadata on the
## server.  Each message summary object is associated with a folder,
## and can be moved from one folder to another on the server.
##
import re, time
import itertools, weakref
from berror import ProtocolError
from email import message_from_string
from sys import maxint as INT_MAX

# This rather hairy regular expression recognizes the format of a
# summary info line sent by the BlitzMail server.
_summ_re = re.compile('(\d+),(\d{2}/\d{2}/\d{2}),(\d{2}:\d{2}:\d{2}),'
                      '(\d),"((?:[^"]|"")*)","((?:[^"]|"")*)",'
                      '"((?:[^"]|"")*)",(\d+),(\d+),([A-Z]),(\d+)$')

# The offset in seconds between 01-Jan-1970 and 01-Jan-1904
# BlitzMail stores seconds-since-epoch in Macintosh (1904) format; the
# rest of the world uses Unix (1970) format.
_time_offset = -2082826800L

# Message types
mtype_plain = '1'
mtype_mime = '2'


class BlitzHeader(object):
    """This class represents the header of a message.  It behaves like
    a case-insensitive dictionary over the names of the header lines.
    The .keys() method will give you the header names known.
    """
    def __init__(self, text):
        if isinstance(text, basestring):
            self.data = text
        else:
            self.data = '\n'.join(text)
        self.index = None
        self.parse()

    def parse(self):
        self.index = {}

        unfolded = []
        for line in self.data.split('\n'):
            if len(line) == 0:
                continue
            elif line[0].isspace():
                unfolded[-1] += ' ' + re.sub(r'^\s+', '', line)
            else:
                unfolded.append(line)

        unpacked = []
        for line in unfolded:
            match = re.match(r'(?i)([a-z][-a-z0-9]*):\s*(.+)$', line)
            if match:
                unpacked.append((match.group(1), match.group(2)))

        # The index maps header keys to lists of tuples of the form
        # (name, list), in which the list contains all the lines that
        # were defined as having "name" as their header name.
        for hdr, data in unpacked:
            key = hdr.lower()
            self.index.setdefault(key, (hdr, []))[1].append(data)

    def keys(self):
        """Return the list of unique header names available."""
        return [z[0] for z in self.index.itervalues()]

    def iteritems(self):
        """Iterate over all the header lines, returning for each a
        tuple of the form (name, data).
        """
        for name, lst in self.index.itervalues():
            for elt in lst:
                yield (name, elt)

    def items(self):
        """Return all the header lines, each represented by a tuple of
        the form (name, data).
        """
        return list(self.iteritems())

    def get(self, hdr):
        """Return an iterator yielding all the occurrences of the named
        header line, in order of their occurrence in the message.

        Each instance is returned as a tuple of the form (name, data).
        """
        name, lst = self.index[hdr.lower()]
        return iter((name, x) for x in lst)

    def first(self, hdr):
        """Return the first occurrence of the named header line in the
        message, if any.
        """
        return self.get(hdr).next()

    def __getitem__(self, key):
        """Equivalent to .first(key)."""
        return self.first(key)

    def __len__(self):
        """Return the number of distinct header keys."""
        return len(self.index)

    def __iter__(self):
        """Iterate over all occurrences of all headers in the collection."""
        return itertools.chain(*(self.get(x) for x in self.keys()))

    def __str__(self):
        """Return the original header string."""
        return self.data


class BlitzSummary(object):
    """This class represents summaries of messages stored on the
    BlitzMail server.  You can use a summary to manipulate the
    message:

    .get_header(),     retrieve the message header (=> str)
    .get_body(),       retrieve the message body (=> str)
    .get_message(),    creates an email.Message object of message
    .move_to(folder),  move the message to another BlitzFolder
    .select(),         select this message for other operations."""
    def __init__(self, folder, info=None, msg_id=None):
        self.folder = folder
        self.session = folder.session  # Is a weak reference
        self.h_cache = None  # Cache of header
        self.b_cache = None  # Cache of body
        self.c_cache = None  # Cache of catalog

        if msg_id:
            self.message_id = int(msg_id)
            self.reload()
        elif info is None:
            raise ValueError("info line or message ID must be provided")
        else:
            self._parse_response(info)

    def __repr__(self):
        return '<BlitzSummary: MessageID=%d Length=%d Subject="%s">' % \
               (self.message_id, self.length, self.subject)

    def __str__(self):
        return str(self.get_message())

    def _parse_response(self, data):
        match = _summ_re.match(data)
        if not match:
            raise ValueError('invalid message summary line: "%s"' % data)

        self.message_id = int(match.group(1))
        self.delivery_date = match.group(2)
        self.delivery_time = match.group(3)
        self.delivered = time.mktime(
            time.strptime(
                match.group(2) + ' ' + match.group(3), '%m/%d/%y %H:%M:%S'))
        self.message_format = int(match.group(4))
        self.sender_name = match.group(5)
        self.rcpt_name = match.group(6)
        self.subject = match.group(7)
        self.length = int(match.group(8))
        self.num_enclosures = int(match.group(9))
        self.status = match.group(10)
        self.expires = int(match.group(11)) + _time_offset

    def __len__(self):
        return self.length

    def select(self):
        """Choose this message as the "current" message on the server."""

        self.session()._cmd2('MESS',
                             str(self.folder.id),
                             str(self.message_id),
                             sep='/')
        self.session()._expect(10)

    def set_expiration(self, when):
        """Set the expiration time of this message.  Time may be
        specified as an integer in seconds-since-Unix-epoch, the
        string 'never' to indicate the message should never expire, or
        a date/time string in the format 'MM/DD/YYYY HH:MM:SS'.  The
        time is optional; hours should be in 24-hour format."""

        exp_time = self._parse_expire(when)
        self.session()._cmd2('EXPR',
                             str(self.folder.id) + '/' + str(self.message_id),
                             str(exp_time),
                             sep=' ')
        self.session()._expect(10)
        self.reload()

    def _parse_expire(self, when):
        if isinstance(when, int):
            return when - _time_offset  # Convert to Macintosh epoch

        if not isinstance(when, str):
            raise ValueError("invalid expiration time: %s" % when)

        if when.lower() == 'never':
            return 2 * INT_MAX + 1

        try:
            t = time.strptime(when, '%m/%d/%Y %H:%M:%S')
            return int(time.mktime(t) - _time_offset)
        except ValueError:
            pass

        t = time.strptime(when, '%m/%d/%Y')
        return int(time.mktime(t) - _time_offset)

    def get_header(self, force=False):
        """Fetch the header from the server.  The result is cached,
        and will not be reloaded unless you set force = True."""

        if self.h_cache and not force:
            return self.h_cache

        self.select()
        self.session()._cmd0('HEAD')
        (key, data) = self.session()._expect(50)

        size = int(data)
        data = self.session()._read(size)
        self.session()._expect(10)

        self.h_cache = BlitzHeader(data.replace('\r', '\n'))
        return self.h_cache

    def _load_bcache(self, offset, length):
        selected = False

        if not self.b_cache:
            self.select()
            self.session()._cmd2('TEXT', str(offset), str(length), sep=' ')
            (key, data) = self.session()._expect(50)

            size = int(data)
            data = self.session()._read(size)
            self.session()._expect(10)

            self.b_cache = (offset, data)
            return self.b_cache[1].replace('\r', '\n')

        if offset < self.b_cache[0]:
            self.select()
            selected = True
            seek = self.b_cache[0] - offset
            self.session()._cmd2('TEXT', str(offset), str(seek), sep=' ')
            (key, data) = self.session()._expect(50)

            size = int(data)
            data = self.session()._read(size)
            self.session()._expect(10)

            self.b_cache = (offset, data + self.b_cache[1])

        endpos = (offset - self.b_cache[0]) + length
        if endpos > len(self.b_cache[1]):
            if not selected:
                self.select()
            seek = endpos - len(self.b_cache[1])
            self.session()._cmd2('TEXT',
                                 str(self.b_cache[0] + len(self.b_cache[1])),
                                 str(seek),
                                 sep=' ')
            (key, data) = self.session()._expect(50)

            size = int(data)
            data = self.session()._read(size)
            self.session()._expect(10)

            if len(self.b_cache[1]) == 0:
                self.b_cache = (offset, data)
            else:
                self.b_cache = (self.b_cache[0], self.b_cache[1] + data)

        out = self.b_cache[1][offset - self.b_cache[0]:endpos]
        return out.replace('\r', '\n')

    def get_body(self, offset=None, length=None, force=False):
        """Fetch all or part of the message body from the server.  If
        offset and length are specified, only that portion of the message
        will be retrieved.  The result is cached, and will not be reloaded
        unless you set force = True."""

        if not self.b_cache or force:
            self.b_cache = None

        if offset and length:
            return self._load_bcache(offset, length)
        else:
            return self._load_bcache(0, self.length)

    def delete_body(self, offset, length):
        endpos = offset + length - 1

        self.select()
        self.session()._cmd2('TDEL', str(offset), str(endpos), sep='-')

        # The response returns the new message ID
        (key, data) = self.session()._expect(00)
        self.message_id = data

        self.b_cache = None
        self.reload()

    def get_message(self, force=False):
        """Load the header and body of the message, and create a
        Message object from them (see the "email" package).  The force
        parameter has the same meaning as for .get_header() and
        .get_body()."""

        head = str(self.get_header(force=force))
        body = self.get_body(force=force)

        return message_from_string(head + "\n" + body)

    def get_catalog(self, force=False):
        """Load the MIME catalog of the message."""

        if self.c_cache and not force:
            return self.c_cache

        self.select()
        self.session()._cmd0('MCAT')
        cat = {}

        (key, data) = self.session()._expect(00, 01)
        while key <> 0:
            tag, rest = data[0], data[2:]

            if not cat.has_key(tag):
                cat[tag] = []

            cat[tag].append(rest)
            (key, data) = self.session()._expect(00, 01)

        tag, rest = data[0], data[2:]
        if not cat.has_key(tag):
            cat[tag] = []

        cat[tag].append(rest)
        keys = cat.keys()
        keys.sort()

        out = [None] * len(keys)
        for key in keys:
            out[int(key) - 1] = BlitzHeader(cat[key])

        self.c_cache = out
        return out

    def reload(self):
        """Re-load message summary information from the server."""

        self.session()._cmd2('MSUM',
                             str(self.folder.id),
                             str(self.message_id),
                             sep='/')
        (key, data) = self.session()._expect(00)

        self._parse_response(data)

    def move_to(self, new_folder):
        """Move this message to another folder.  This may cause the
        message's expiration time to change, depending upon the
        settings of the AutoExp preference."""

        self._move_message('MOVE', new_folder)
        self.folder.touch()
        self.folder = new_folder
        new_folder.touch()

    def copy_to(self, new_folder):
        """Copy this message to another folder.  The original message
        is left in its original location; the copy gets a new ID."""

        self._move_message('COPY', new_folder)
        new_folder.touch()

    def _move_message(self, op, new_folder):
        src_id = self.folder.id
        tgt_id = new_folder.id
        my_id = self.message_id

        self.session()._cmd3(op, str(src_id), str(tgt_id), str(my_id), sep=' ')
        (key, data) = self.session()._expect(01)

        new_exp = int(data)
        if new_exp <> -1 and op <> 'COPY':
            self.expires = new_exp

        while key <> 0:
            (key, data) = self.session()._expect(00, 01)

        self.folder.touch()
        new_folder.touch()

    def mark_read(self):
        """Clear the "unread" flag for the message on the server."""
        self._mark_message('R')

    def mark_unread(self):
        """Set the "unread" flag for the message on the server."""
        self._mark_message('U')

    def _mark_message(self, how):
        my_id = str(self.folder.id) + '/' + str(self.message_id)

        self.session()._cmd2('MARK', how.upper(), my_id, sep=' ')
        self.session()._expect(10)


class BlitzOutboundMessage(object):
    """This class represents a message being composed for outbound
    delivery.  When created, it must be associated with a BlitzSession
    object so that it can communicate with the server.  At a minimum,
    you must call the .add_to_recipient() method to add a recipient.
    You can also use .set_subject() to set the subject line.

    The message payload can be set using
      .set_plain_body() -- to set a plain-text message body, or
      .set_mime_body()  -- to set the complete MIME structure

    Use the .send() method to cause the message to be sent.
    
    If you screw up, use .reset() or .reset_recipients() to get back
    to a "pristine" state.  Keep in mind, however, that this object
    doesn't keep track of previously-added information; it is simply
    an interface to the server commands.
    """
    def __init__(self, session):
        self.session = weakref.ref(session)

        self.reset()

    def _read_response(self):
        """Private interface to read a response from the server;
        converts the response codes into tuples for internal use.
        """
        out = []

        while True:
            key, data = self.session()._expect(28, 29, 40, 41, 42, 43, 44, 45,
                                               46, 47)

            if key in (40, 44):
                out.append(("ok", data))  # Recipient okay
            elif key in (43, 47):
                out.append(("ambig", data))  # Ambiguous match
            elif key in (42, 46):
                out.append(("none", data))  # No match
            elif key in (28, 29):
                out.append(("loop", data))  # Forwarding or list loop
            elif key in (41, 45):
                out.append(("perm", data))  # Permission denied

            # These codes indicate the end of expansion
            if key in (28, 40, 41, 42, 43):
                break

        return out

    def reset(self):
        """Clear all current message data from the server."""
        self.session()._cmd0('CLEA')
        self.session()._expect(10)

    def reset_rcpt(self):
        """Clear all current recipient data from the server."""
        self.session()._cmd0('CLER')
        self.session()._expect(10)

    def set_audit(self, folder):
        """Specify an audit mailbox to save a copy in, when sent."""
        self.session()._cmd1('AUDT', str(folder.id))
        self.session()._expect(10)

    def set_subject(self, subj):
        """Set the subject line."""
        self.session()._cmd1('TOPC', subj)
        self.session()._expect(10)

    def set_plain_body(self, data):
        """Set the body of the message to the specified text; uses the
        old "BlitzMail" style (no MIME parts are processed)."""

        # Message objects should expand here (which may lead to
        # unpleasant or unexpected results if you meant to send MIME
        # content)
        data = str(data).replace('\n', '\r')

        self.session()._cmd2('MDAT', str(len(data)), mtype_plain, sep=' ')
        self.session()._expect(50)

        self.session()._send(data)
        self.session()._expect(10)

    def set_mime_body(self, data):
        """Set the body of the message to the specified MIME message,
        including headers.  Note that only MIME-relevant headers are
        processed; the server overrides From, Subject, To, Cc, and Bcc
        headers according to its own rules."""

        # Message objects should expand here
        data = str(data).replace('\n', '\r')

        self.session()._cmd2('MDAT', str(len(data)), mtype_mime, sep=' ')
        self.session()._expect(50)

        self.session()._send(data)
        self.session()._expect(10)

    def add_to_recipient(self, who):
        """Add a recipient to the To: field."""
        self.session()._cmd1('RCPT', who)

        return self._read_response()

    def add_cc_recipient(self, who):
        """Add a recipient to to the Cc: field."""
        self.session()._cmd1('RCCC', who)

        return self._read_response()

    def add_bcc_recipient(self, who):
        """Add a recippient to the Bcc: field."""
        self.session()._cmd1('RBCC', who)

        return self._read_response()

    def set_reply_to(self, addr):
        """Set the Reply-To: header to the given address."""
        self.session()._cmd1('RPL2', addr)
        self.session()._expect(10)

    def request_receipt(self):
        """Request a return-receipt on this message."""
        self.session()._cmd0('RTRN')
        self.session()._expect(10)

    def hide_recipients(self):
        """Request that the recipient list be suppressed from the header."""
        self.session()._cmd0('HIDE')
        self.session()._expect(10)

    def send(self):
        """Commit and send the message."""
        self.session()._cmd0('SEND')
        self.session()._expect(10)


__all__ = ["BlitzHeader", "BlitzSummary", "BlitzOutboundMessage"]

# Here there be dragons
