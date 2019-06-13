# About the Python BlitzMail Library

* N.B.: The BlitzMail system has been decommissioned, so the code here is
  mostly of historical curiosity. Some of the links below no longer work.

This is an implementation of the majority of the BlitzMail protocol in Python.
If you are not familiar with BlitzMail, you probably do not need this, however,
for more information, see:

* http://www.dartmouth.edu/softdev/
* http://www.dartmouth.edu/netsoftware/blitz.html

In summary, BlitzMail is an easy-to-use electronic mail system developed at
Dartmouth College in the late 1980's, which is still the dominant e-mail system
in use at the College as of this writing.  It is also used at other sites
(e.g., Dartmouth-Hitchcock Medical Center, Reed College, Washington University,
and at least two ISP's in the Upper Connecticut River Valley).

What is missing from this implementation:

  - Kerberos authentication (K4 is supported by the DND).
  - Old-style "enclosures" are not handled (though MIME ones are).
  - Summary caching (although you can add it yourself fairly easily).

## Roadmap

The library consists of the following files:

```
  __init__.py     : The module loader for the library
  session.py      : The primary module, defines the BlitzSession class.
  berror.py       : Exception classes thrown within the library.
  bfold.py        : Defines folder manipulation (the BlitzFolder class).
  blist.py        : Defines list manipulation (the BlitzList classes).
  bmesg.py        : Defines message handling (the BlitzMessage classes).
  bulls.py        : Defines the BulletinSession, Topic, and Article classes.
  bwarn.py        : Handles "warnings" (the BlitzWarning class).

  notify/
    __init__.py   : The module loader for the notification client
    session.py    : Defines the TCP client, NotifySession.
    client.py     : Defines the UDP client, NotifyClient.
    packet.py     : Defines packet formats and manipulation.
    ntypes.py     : Base classes for notification handling.
    notifyd.py    : An implementation of a notification server.
    procnotify.py : A procmail notifier for non-BlitzMail systems.
    necho         : A command-line notification posting client.
```

### Basic Usage

 1. Install the "BlitzMail" folder somewhere Python can find it.
    For instance, /usr/share/python/lib/site-packages is a good location.

    You will also need "dnd.py": http://www.dartmouth.edu/~sting/sw.shtml#dnd

	You will also need the PyCrypto library.

 2. In your programs, "`import BlitzMail`"

 3. Create a `BlitzSession` object, and use its `.sign_on()` method to get
    connected:

        blitz = BlitzMail.BlitzSession()

        blitz.sign_on(user_name, password)

    This method, like all others in the library, will throw exceptions in case
    of errors.  Unfortunately, the library does not yet support Kerberos
    authentication; however, it does encrypt passwords so they are NOT sent in
    cleartext.

    If the specified user is already connected, `.sign_on()` will raise a
    `BlitzProtocolError`.  You can get around this by setting the push_off
    keyword parameter to True:

        blitz.sign_on(user_name, password, push_off = True)

    If you want to query the user, set `push_off` instead to a callable object;
    it will be called with a single argument, the message string from the
    BlitzMail server.  If the callable returns a true value, the connexion will
    be terminated; otherwise an exception is raised.

    Alternately, you can use the `.reconnect()` method, after you have
    attempted to sign on:

        blitz.reconnect()

    When you're done with the session,

        blitz.close()
        del(blitz)     # Releases user information

To obtain a list of available folders:

      blitz.folders()

Operations on folders are handled by the `BlitzFolder` class, including
downloading message summaries (bfold.py, and see also bmesg.py for the
`BlitzSummary` class).

To obtain a list of available private mailing lists:

      blitz.get_private_lists()

Operations on private mailing lists are handled by the `BlitzPrivateList` class
(blist.py).

To obtain a list of available group mailing lists:

      blitz.get_group_lists()

Operations on group mailing lists are handled by the `BlitzGroupList` class
(blist.py).

Global preferences are handled by the `BlitzSession` methods:

    .read_pref()
    .write_pref()
    .remove_pref()
    .get_session_id()
    .get_last_login()

Folder-related preferences (like the list of expired messages for a folder, as
well as the auto-expiration interval) are set using methods on the
`BlitzFolder` object:

    .get_autoexp()
    .set_autoexp()
    .get_expired_list()
    .clear_expired_list()

You can check warnings using the `.check_warnings()` method.  At all times, the
`BlitzSession` object maintains a `.warn_flag` property that is set to True
whenever the server posts a warning in its responses (see the BlitzMail
Protocol document for more about how this works).

To compose a message, call the `BlitzSession` method:

    .create_new_message()

This returns a `BlitzOutboundMessage` object which can be used to set up the
various parameters of the message, and send it (cf. bmesg.py).

To retrieve messages, obtain `BlitzSummary` objects from the various folders,
and use their methods:

```python
  .get_header()    # Returns a BlitzHeader object
  .get_body()      # Fetch all or part of message body
  .delete_body()   # Delete all or part of message body
  .get_message()   # Returns an email.Message object
  .move_to(fldr)   # Move it to a different folder
  .copy_to(fldr)   # Copy it to a different folder
```

## Other BlitzSession Methods

You can send a NOOP to the server to keep the connexion live:

    .keep_alive()

You can post, review, and delete vacation messages:

    .get_vacation_message()
    .set_vacation_message()
    .clear_vacation_message()

## Reading Bulletins

In order to read bulletins, your site will have to run a bulletin server.  As
far as I know, only Dartmouth bothers to do this, but there may be other
BlitzMail sites that use them.  Assuming you do have access to bulletins,
here's how you access them.

1.  Create a `BulletinSession` object, and use its `.sign_on()` method to log
    in with your name and password:

        b = BlitzMail.BulletinSession()
        b.sign_on(user_name, password)

2.  Get a list of available topics in one of two ways:

    You can get the names of all the topics, as strings,

        topic_names = b.get_topics()

    Or, you can get a list of `Topic` objects with complete info,
	
        topics = list(b)

    The BulletinSession object is iterable, and will return a sequence of
    `Topic` objects.  If you index into the session object, you can either
    index by the literal name of the topic (a string), or with a regular
    expression object (from the `re` or `sre` modules).  The first will return
    a single topic object, if available; the second will return a list of topic
    names which contain the regular expression.

    You can get a list of subscribed topic names using:

        b.subscribed()

    You can get a list of subscribed topic names for which there are new
    articles available using:

        b.new_topics()

3.  Once you have a topic object, there are several useful fields:

    - `.name`       -- the NNTP-style group name of the topic (string).
    - `.title`      -- human-readable topic description (string).
    - `.watch`      -- "Y" or "N", whether user monitors this topic.
    - `.post`       -- "Y" or "N", whether user can post to this topic.
    - `.id_low`     -- lowest-numbered available article ID.
    - `.id_high`    -- highest-numbered available article ID.
    - `.last_id`    -- last-read article ID, set by client.
    - `.info`       -- client info string, set by client.
	
    To obtain a list of article objects, use:
	
            topic.articles()

    To set whether this group is monitored or not:

            topic.monitor()
            topic.unmonitor()

    To update the last-read ID and client info string, use:

            topic.update(id[, client_string])

    To select this topic as the active group on the server,

            topic.select()

4.  An `Article` lets you get the content of an individual article.  The useful
    methods here include:

    - `.header()`    -- return a list of header lines (strings).
    - `.body()`      -- return a list of body lines (strings).
    - `.keys()`	-- return the names of summary fields.
    - `.select()`	-- select the topic containing this article.

    To obtain a Message object containing the article, use `msg.get_message()`.

    An Article behaves like a dictionary of summary fields obtained by the
    `XHEAD` protocol command when the Article was loaded.

## Sending and Receiving Notifications

> [not all sites may support this facility]

The BlitzMail system contains a simple asynchronous notification facility.  A
client registers with it via UDP, and when new mail is received, the BlitzMail
server will send out a notice.  This allows clients to be informed of new
message arrivals without polling the server.

The system also permits clients to post notifications, via a second TCP-based
server interface.

To listen for notifications,

```python
  # Import the UDP client library
  from BlitzMail.notify import client

  # Create a new client object, specifying user name and which services
  # should be listened for.  Right now, "mail", "news", and "talk" are
  # the only options.
  c = client.NotifyClient('username', ("mail", "news"))

  # Start up the client threads (which run independently)
  c.start()
```

When new notifications arrive, they are posted in a queue.  To read the queue,
use

    note = c.next()

This blocks until a notification is available.  If you do not want it to block,
you may specify a timeout in seconds:

    note = c.next(5)  # Wait up to 5 seconds for a notification

You may also use `c.peek()` to effect a single poll, which does not block, and
does not remove the notification it returns.

Notifications are returned as tuples, of the format

    (service, userid, msgid, data)

Here, "service" is the service code (1 = mail, 2 = news, 3 = talk), "userid" is
the DND UID of the user for whom this notification was sent, "msgid" is a
message identifier (usually a BlitzMail message ID for mail notifications), and
"data" is a string of additional data, whose first byte indicates its length.

To clear sticky notifications for a particular category,

    c.clear('mail')   #  ... for example

To post notifications,

```python
  # Import the TCP client library
  from BlitzMail.notify import session

  # Create a new session object
  s = session.NotifySession()

  # Sign on
  s.sign_on('username', '<user-password>')

  # Post a notification
  s.post_notify('mail', 'You have received new mail!', msg_id = 12345)

  # Clear "sticky" notifications
  s.clear_sticky('mail')
  s.clear_sticky('news')

  # Sign off
  s.close()
```

A note about "sticky" notifications: When a notification is posted, it has the
option to be "sticky".  A sticky notification is not removed from the notify
server's queue of available notifications when it is delivered, and thus it
will be sent as a new notification each time a new notification client
registers.  Clearing sticky notifications for a given service clears out the
user's queue for that service.

The program "procnotify.py" allows you to receive notifications of e-mail that
is sent to a non-BlitzMail account.  It is intended to be used from a
server-side mail filter such as procmail [1].  Basically, you arrange for
incoming mail to be piped to this program, and it will post a notification
based on the sender and subject line of the message.

Usage:

    procnotify.py --user "Your BlitzMail Name"

The script uses the DND to figure out where your notification server lives, and
posts a mail notification (type code 1).  The sender and subject are extracted
using the rfc822 module, if possible.  You can also use this from the command
line, by specifying a file name:

    procnotify.py -u "Your Name" --file "my-message.txt"

Use "`procnotify.py --help`" for a complete list of command line options.  This
tool has not been widely tested, so I wouldn't be surprised if there are some
mistakes -- please let me know if you have any trouble, and I will try to help
you debug it.

The program "necho" is similar in spirit to the Unix "echo" command, but
instead of echoing to the terminal, it sends a message as a notification, to
the current user's name.  Command line options allow you to specify an
alternate notification type, make the notification sticky, and change which DND
you are talking to.  Use "necho --help".

The module "notifyd.py" provides an implementation of a notification server
similar to the one that runs on the BlitzMail servers.  There are two main
classes:

*  `NotifyTCPServer`   -- provides the TCP posting interface.
*  `NotifyUDPServer`   -- provides the UDP client interface.

The implementation uses a SQLite database [2] to store sticky notifications, so
you will need both SQLite and pysqlite2 [3] installed on your system in order
to use this module.  If you really don't want to do this, you can rewrite the
NoticeDB class to use some other back end storage mechanism.

The TCP service implements a few things the original notifyd [4] does not:

 1. You may specify a "privileged user" by giving a DND UID to the server.  You
    must authenticate using the USER and PASS/PASE commands.  This
    implementation uses the DND to authenticate.

 2. This privileged user may list all the sticky notifications in the database
    (using the nonstandard LIST command).

 3. Notifications to UID 0 are broadcast to all clients.  The privileged user
    may post such notifications, and may clear them.

 4. The CLIENT command allows you to publish the existence of a client via the
    TCP interface, supplying UID, address, port, and a list of desired service
    codes.

## References

[1] http://www.procmail.org/
[2] http://sqlite.org/
[3] http://pysqlite.org/
[4] In ftp://ftp.dartmouth.edu/pub/software/mac/BlitzMail/Export/src/,
    see blitzserv-3.10b2.tar.Z, notably the notify/ directory.

## Author and Copyright Notice

Copyright (C) 2004-2006 Michael J. Fromberger, All Rights Reserved.
Use and distribution are permitted under the terms in the LICENSE file.
