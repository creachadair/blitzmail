##
## Name:     Makefile
## Purpose:  Make script for Python BlitzMail library
##
## Copyright (C) 2004-2006 Michael J. Fromberger, All Rights Reserved.
##
SRCS=__init__.py session.py berror.py bfold.py blist.py bmesg.py \
	bulls.py bwarn.py BULLETINS.txt notify/__init__.py \
	notify/session.py notify/client.py notify/packet.py \
	notify/ntypes.py notify/PROTOCOL.txt notify/packet-fmt.graffle \
	notify/notifyd.py notify/procnotify.py notify/necho \
	notify/test.mbox \
	setup.py listedit blitz2mbox

.PHONY: clean distclean dist install help

help:
	@ echo ""
	@ echo "Targets you can build with this makefile:"
	@ echo "  clean     - remove editor temps and cores"
	@ echo "  distclean - clean up for distribution"
	@ echo "  dist      - make distribution tarball"
	@ echo "  install   - build and install"
	@ echo ""

install: distclean
	python setup.py build
	sudo python setup.py install

format:
	find . -type f -name '*.py' -print0 | \
		xargs -t0 yapf --style=pep8 -i

clean: 
	rm -f *~

distclean: clean
	rm -f *.py[co] notify/*.py[co]
	if [ -d build ] ; then rm -rf build ; fi

dist: distclean
	rm -f PyBlitz.zip __p1.zip
	zip -9 __p1.zip $(SRCS) Makefile README
	mkdir BlitzMail
	cd BlitzMail && unzip ../__p1.zip
	rm -f __p1.zip
	zip -9r PyBlitz.zip BlitzMail
	rm -rf BlitzMail

pydist: distclean
	zip -9 __p1.zip $(SRCS) Makefile README
	mkdir BlitzMail
	cd BlitzMail && unzip ../__p1.zip
	rm -f __p1.zip
	tar -cvf BlitzMail.tar BlitzMail
	rm -rf BlitzMail
	gzip -9v BlitzMail.tar

# Here there be dragons
