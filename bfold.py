##
## Name:     bfold.py
## Purpose:  BlitzMail folder classes
##
## Copyright (C) 2004-2006 Michael J. Fromberger, All Rights Reserved.
##
## A folder represents a collection of messages.  Each folder has a
## name and a unique ID number.  Folder objects allow you to index
## their contents by position or by message ID.
##
import re
import bmesg, dnd, sys, weakref

_info_re = re.compile('(\d+),(\d+),"(.+)",(\d+)')


class BlitzFolder(object):
    """A class to represent BlitzMail folders.  The BlitzMail server
    provides a simple "folder" abstraction that allows messages to be
    grouped together.  Each message is contained in exactly one folder
    on the server, and can be moved between folders at will.  Folders
    are identified by user-chosen names and internally-assigned ID
    numbers.

    This class allows a folder to be manipulated as a sequence type,
    in that you may index into the folder by position (int) or message
    ID (str), and you may iterate over the messages contained in the
    folder.
    """

    def __init__(self, session, info=None, id=None):
        """A folder may be constructed by giving a session object and
        either the BlitzMail server's info line for the folder, or the
        numeric ID of the folder.  The details will either be parsed
        from the info line, or loaded from the session using the
        ID."""

        self.need_rl = False
        self.session = weakref.ref(session)
        if id is None:
            if info is None:
                raise ValueError("folder name or ID must be provided")

            self._parse_info(info)
        else:
            self.id = int(id)
            self.need_rl = True

    def __repr__(self):
        return '<BlitzFolder: "%s" with %d messages, size=%d, id=%d>' % \
               (self.name, self.count, self.size, self.id)

    def __str__(self):
        return repr(self)

    def __iter__(self):
        """Iterate over the message summaries contained in this folder.

        See also:  class BlitzSummary
        """
        return iter(self.get_summaries())

    def _parse_info(self, data):
        match = _info_re.match(data)
        if not match:
            raise ValueError('invalid folder info line: "%s"' % data)

        self.id = int(match.group(1))
        self.count = int(match.group(2))
        self.name = match.group(3)
        self.size = int(match.group(4))

    def __getattribute__(self, attr):
        # Anytime a server attribute is accessed, make sure it's up to date.
        if attr in ('count', 'name', 'size') and self.need_rl:
            self.reload()

        return super(BlitzFolder, self).__getattribute__(attr)

    def __len__(self):
        """Returns the number of messages in the folder right now."""
        return self.count

    def keys(self):
        """Return the message ID's in the folder right now."""
        return [s.message_id for s in self.get_summaries()]

    def __getitem__(self, pos):
        if isinstance(pos, slice):
            if pos.stop == sys.maxint:
                rng = self.get_summaries(pos.start + 1, '$')
            else:
                rng = self.get_summaries(pos.start + 1, pos.stop)
            return rng[:pos.step:]

        if isinstance(pos, str):
            pos = int(pos)
            for s in self.get_summaries():
                if s.message_id == pos:
                    return s
            else:
                raise IndexError("message ID %s not found" % pos)

        if not isinstance(pos, int):
            raise TypeError("folder indices must be integers")

        if pos < 0:
            pos += self.count

        if pos < 0 or pos >= self.count:
            raise IndexError("folder index out of range")

        return self.get_summaries(pos + 1)[0]

    def reload(self):
        """Re-load folder information from the server."""

        # It is important that this method not attempt to read the
        # server attributes "count", "name", and "size".

        self.session()._cmd1('FLIS', '%d' % self.id)
        (key, data) = self.session()._expect(00)

        self._parse_info(data)
        self.need_rl = False

    def touch(self):
        """Mark this folder as being "out of sync" with the server.
        This forces a reload of the folder's vital statistics from the
        server the next time you try to access them.
        """
        self.need_rl = True

    def rename(self, new_name):
        """Change the name of the folder to the new name specified."""
        self.session()._cmd1('FNAM',
                             '%d %s' % (self.id, dnd.enquote_string(new_name)))
        self.session()._expect(10)
        self.need_rl = True

    def remove(self):
        """Delete this folder from the server."""
        self.session()._cmd1('FREM', '%d' % self.id)
        self.session()._expect(10)
        self.session().fl_cache = None

    def get_autoexp(self):
        """Fetch the AutoExp preference for this folder."""

        pname = "AutoExp%d" % self.id
        return self.session().read_pref(pname)[pname]

    def set_autoexp(self, interval):
        """Set automatic expiration for this folder to the given interval.

        Expiration intervals are specified as a number of days or months,
        in string form, e.g., '7' for seven days '2M' for two months.
        """
        pname = "AutoExp%d" % self.id
        self.session().write_pref(pname, interval)

    def get_expired_list(self):
        """Return the list of message ID's expired from this folder.
        This supports client-side summary caching.
        """
        pname = 'Expired%d' % self.id
        exp = self.session().read_pref(pname)[pname]

        if exp:
            return exp.split()
        else:
            return []

    def clear_expired_list(self):
        """Clear the list of message ID's expired from this folder.
        This supports client-side summary caching.
        """
        pname = 'Expired%d' % self.id
        self.session().remove_pref(pname)

    def get_session_tag(self):
        """Return the value of SessionId the last time this folder was
        modified.
        """
        pname = 'FoldSessionTag%d' % self.id
        return int(self.session().read_pref(pname)[pname])

    def get_summaries(self, lo_index=None, hi_index=None):
        """Fetch summaries by their position within the folder.  If
        only lo_index is specified, that single summary is fetched; if
        hi_index is also specified, a range of indices is fetched.  If
        no indices are specified, all available summaries are
        fetched.
        """
        # Degenerate special case; FSUM is an error on an empty folder
        # for some dumb reason.
        if self.count == 0: return []

        if hi_index is None:
            if lo_index is None:
                rng = '1-$'
            else:
                rng = str(lo_index)
        else:
            if lo_index is None:
                lo_index = 1
            rng = '%s-%s' % (lo_index, hi_index)

        out = []
        self.session()._cmd2('FSUM', str(self.id), rng, sep=' ')
        (key, data) = self.session()._expect(00, 01)

        while key <> 0:
            out.append(bmesg.BlitzSummary(self, data))
            (key, data) = self.session()._expect(00, 01)

        out.append(bmesg.BlitzSummary(self, data))
        return out


__all__ = ["BlitzFolder"]

# Here there be dragons
