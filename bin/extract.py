#!/usr/bin/env python

import subprocess
import sys
import os
import errno
import logging

## taken from http://stackoverflow.com/a/377028/198348
def which(program):
    def is_exe(program):
        return os.path.isfile(program) and os.access(program, os.X_OK)

    fpath, fname = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file
    return None

## taken from http://stackoverflow.com/a/5032238/198348
def make_sure_path_exists(path):
    try:
        os.makedirs(path)
    except OSError as exception:
        if exception.errno != errno.EEXIST:
            raise

if __name__ == "__main__":
    ## to make sure commands exist:
    #commands = ["7z", "unrar", "bunzip2", "gunzip", "wicked"]
    #for command in commands:
        #print("%s %s" % (command, which(command)))

    ## make some assertions... 

    print(len(sys.argv))
    assert len(sys.argv) == 2+1, "only 2 arguments taken"
    assert os.path.isfile(sys.argv[1]), "file doesn't exist"

    try:
        make_sure_path_exists(sys.argv[2])
    except Exception as e:
        print >>sys.stderr, e

    print("cool, passed!")


