#!/usr/bin/env python

# this is a really hacky way to implement a notification setup for KDE and other
# systems that have notify-send installed. you can set it up via cronjob, or use
# KDE's 'notifications' manager to add a command to be executed whenever the
# screensaver is closed so you get a digest for what you have to work on today

# import system modules
import os
import re
import argparse
import subprocess
from datetime import date


# set up terminal help text and argparse
parser = argparse.ArgumentParser(description="""
                                 This is a notification service for task.
                                 """)
parser.add_argument("-f", "--file",
                    help="specify an alternative filename to use as default",
                    metavar="(NAME)")
args = parser.parse_args()


# global variables for reuse
if args.file:                                       # Enables user to select a
    fileName = args.file + ".txt"                   # different file to store
else:                                               # the tasks in
    fileName = "tasks.txt"
appName = "Task"                                    # Name of the application
dirName = "hello-task"                              # Directory name
homeDir = os.path.expanduser("~")                   # Use user's home as base
targetDir = homeDir + "/.local/share/" + dirName    # Determine target directory
targetFile = targetDir + "/" + fileName             # Construct full path


# pull the description and due date out of a todo.txt line
def parseLine(line):
    done = False
    due = None
    tokens = line.split(" ")
    i = 0
    if i < len(tokens) and tokens[i] == "x":
        done = True
        i += 1
        if i < len(tokens) and re.match(r'^\d{4}-\d{2}-\d{2}$', tokens[i]):
            i += 1
    if i < len(tokens) and re.match(r'^\([A-Z]\)$', tokens[i]):
        i += 1
    if i < len(tokens) and re.match(r'^\d{4}-\d{2}-\d{2}$', tokens[i]):
        i += 1
    description = []
    for token in tokens[i:]:
        match = re.match(r'^due:(\d{4}-\d{2}-\d{2})$', token)
        if match:
            due = match.group(1)
        else:
            description.append(token)
    return done, due, " ".join(description)


def todoRead(content):
    group = ""
    with open(content) as todofile:
        for line in todofile:
            line = line.rstrip("\n")
            if line.strip() == "":
                continue
            done, due, description = parseLine(line)
            if done or due is None:
                continue
            days = (date.fromisoformat(due) - date.today()).days
            # remind about anything due today or already overdue
            if days <= 0:
                group = group + "\n· " + description
    if group != "":
        subprocess.call(['notify-send', "Due Today", group])


todoRead(targetFile)
