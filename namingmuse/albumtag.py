"""A module for renaming and setting tags on music albums 
using the online music database freedb to retrieve the
information.
"""

tagname = "namingmusetag"
tagver = "0.02"

import difflib
import os,re,sys,string
import random
import TagLib
import policy
import discmatch
from terminal import colorize
from cddb import *
from string import lower
from sys import exit

from exceptions import *


DEBUG = False

def footprint(album):
    footprint = tagname + ": " + tagver
    footprint += "\ncddbid: %s" % album["cddbid"]
    footprint += "\ngenreid: %s" % album["genreid"]
    return footprint

def getStoredCDDBId(filelist):
    'Get the cddb id stored in comment in a previous run'
    filename = filelist[0]
    fileref = TagLib.FileRef(filename)
    comment = fileref.tag().comment()
    comment = str(comment)
    del fileref
    regex = '\ndisc_id: (?P<disc_id>([a-f0-9]*))\ngenre: (?P<category>([a-z]*))'
    match = re.search(regex, comment)
    if match:
        return match.groupdict()
    else:
        return None

def needTag(filelist):
    ''' 
    Check if we need to write new tags to this album
    '''
    filename = filelist[0]
    fileref = TagLib.FileRef(filename)
    comment = fileref.tag().comment()
    comment = str(comment)
    del fileref
    regex = "^"+tagname+': ([0-9\.]*)'
    match = re.search(regex,comment)
    if match:
        commenttagver = match.group(1)
        if commenttagver >= tagver: 
            return False
    return True

def getfilelist(path, fullpath = True):
    """Get sorted list of files supported by taglib 
       from specified directory"""
    rtypes = re.compile("\.(mp3|ogg|flac)$", re.I)
    if fullpath:
        filelist = map(lambda x: os.path.join(path, x), os.listdir(path))
    else:
        filelist = os.listdir(path)
    filelist = filter(rtypes.search, filelist)
    filelist.sort()
    return filelist

def getFloatLength(filename):
    import commands
    #p = os.popen("/tmp/build/mp3info-0.8.4/playtime.sh " + filename)
    pread,pwrite = os.pipe()
    childid = os.fork()
    if childid:
        os.waitpid(childid, 0)
    else:
        os.dup2(pwrite, 1) #stdout
        os.execv("/tmp/build/mp3info-0.8.4/playtime.sh", ["playtime.sh", filename])
    pread = os.fdopen(pread)
    strlength = pread.readline()
    return float(strlength)

def getIntLength(filename):
    "Get length of a music file via taglib"
    tagfile = TagLib.FileRef(filename)
    audioproperties = tagfile.audioProperties()
    return audioproperties.length()


def distwrap(a, b):
    "Wraps a string distance function"
    a, b = a.lower(), b.lower()
    isjunk = lambda x: not x in string.lowercase
    return SequenceMatcher(isjunk, a, b).ratio()

def namebinder_strapprox_time(filelist, namelist):
    """Bind namelist to filelist by string approximation
       rate [0-1] multiplied by (timedelta + 1), so that
       0(+1) offsets get compared only by string approximation."""
    newnamelist = []
    for i in range(0, len(filelist)):
        file = os.path.basename(filelist[i])
        least = (distwrap(file, namelist[0]["title"]), 0)
        for j in range(0, len(namelist)):
            name = namelist[j]
            dist = distwrap(file, name["title"])
            #print "dist: ", dist, file, name["title"]
            if least[0] < dist:
                least = (dist, j)
        #print "least: ", least[0]
        newnamelist.append(namelist[least[1]])
    return newnamelist

def namebinder_strapprox(filelist, namelist):
    "Bind namelist to filelist by string approximation"
    newnamelist = []
    for i in range(0, len(filelist)):
        file = os.path.basename(filelist[i])
        least = (distwrap(file, namelist[0]["title"]), 0)
        for j in range(0, len(namelist)):
            name = namelist[j]
            dist = distwrap(file, name["title"])
            if least[0] < dist:
                least = (dist, j)
        newnamelist.append(namelist[least[1]])
    return newnamelist

def namebinder_trackorder(filelist, namelist):
    "Bind namelist to filelist by track order"
    namelist.sort(lambda a,b:cmp(a["track"], b["track"]))
    return namelist

def sortedcmp(cmp, cmp2):
    cmp = cmp[:]
    cmp2 = cmp2[:]
    cmp.sort()
    cmp2.sort()
    return cmp == cmp2

def tagfiles(albumdir, albumdict, options, namebinder = namebinder_trackorder):
    '''Rename and tag files using freedb information for
       the specified album.'''

    albumdir = os.path.abspath(albumdir)
    filelist = getfilelist(albumdir, fullpath = False)

    year = albumdict['year'] 
    genre = albumdict['genre']
    albumartist = albumdict['albumartist']
    albumname = albumdict['album']
    namelist = albumdict['namelist']

    oldnamelist = namelist
    namelist = namebinder(filelist, namelist)

    if not sortedcmp(oldnamelist, namelist): 
        options.dryrun = True
        print NamingMuseError("binding was not exact, forcing dry run")

    #XXX: skift til try value convert
    #XXX: og legg til track
    try:
        if year == "": raise TagIncompleteWarning("year")
        if genre == "": raise TagIncompleteWarning("genre")
        if albumname == "": raise TagIncompleteWarning("albumname")
    except TagIncompleteWarning, warn:
        if options.strict:
            raise
        else:
            print warn, "\n"

    print "Tagging album: %s, %s - %s, %s.\n" % (year, albumartist, albumname, genre)

    pjoin = os.path.join
    dirname,basename = os.path.split(albumdir)
    todir = policy.albumdirname(basename, albumartist, albumname, year, genre)
    newalbumdir = pjoin(dirname, todir)

    # Process files
    longestfilename = max(map(lambda x: len(x), filelist))
    renamealbum = True
    for i in range(0, len(filelist)):
        file = filelist[i]
        ext = lower(os.path.splitext(file)[1])
        fullpath = pjoin(albumdir, file)
        title = namelist[i]["title"]
        if albumartist == "Various":
            trackartist, title = title.split("/")
            trackartist, title = trackartist.strip(), title.strip()
        else:
            trackartist = albumartist
        track = namelist[i]["track"]
        tofile = policy.filename(file, ext, title, track, 
                                 trackartist, albumname, year, genre, albumartist)
    
        # Tag and rename file
        fileref = TagLib.FileRef(fullpath)
        tag = fileref.tag()
        comment = tag.comment()
        renamesign = "->"
        if options.tagonly:
            renamesign = "-tag->"
        if options.dryrun:
            renamesign = "-dry->" 
        if str(comment) == "manual":
            renamesign = "-skip->"
            renamealbum = False
        print file.ljust(longestfilename)
        print "\t", colorize(renamesign), tofile
        if not (options.dryrun or str(comment) == "manual"):
            try:
                year = int(year)
            except ValueError:
                year = 0
            tag.setYear(year)
            tag.setGenre(genre)
            tag.setArtist(trackartist)
            tag.setAlbum(albumname)
            tag.setTitle(title)
            try:
                track = int(track)
            except ValueError, warn:
                track = 0
            tag.setTrack(track)
            comment = footprint(albumdict)
            tag.setComment(comment)
            fileref.save()
            if not options.tagonly:
                os.rename(fullpath, pjoin(albumdir, tofile))

    # Rename album (if no "manual" mp3 files in that dir)
    renamesign = (renamealbum and "->" or "-skip->")
    if renamealbum and options.dryrun: renamesign = "-dry->"
    print "\n", basename, colorize(renamesign), todir
    if not (options.dryrun or options.tagonly) and renamealbum:
        os.rename(albumdir, newalbumdir)
        albumdir = newalbumdir

