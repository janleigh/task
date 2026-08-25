#!/usr/bin/env python

# import modules
import os
import re
import json
import time
import argparse
import readline
from abc import ABC, abstractmethod
from os import listdir
from os.path import isfile, join, dirname, basename
from datetime import date, timedelta
from sys import stdout
from sys import exit as byebye


#set up terminal help text and argparse
parser = argparse.ArgumentParser(description="""
                                 Task is a todo list application that allows you
                                 to quickly create task lists by typing them
                                 without any additional frizz. Write anything
                                 into the input field and see it added as a new
                                 item on your list.\n
                                 Task understands you. By using a natural suffix
                                 like 'in 3 days' it will automatically create a
                                 timestamp and sort the added task according to
                                 it's due date.\n
                                 Once a task is finished, you can use it's id
                                 and delete it by typing ':d id' where 'id' is
                                 the number displayed with the task.\n
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
lvl = 4                                             # Foresight (view) level
message = ""                                        # Feedback messages
openTasks = 0                                       # Used to count open tasks

# set up classes for easier color coding
class color:
    black = "\033[30m"          # used when also supplying a background
    red = "\033[31m"            # used for urgent or deletion
    green = "\033[32m"          # used for additions or confirmations
    yellow = "\033[33m"         # used for program questions and semi-urgent
    orange = "\033[214m"        # used to highlight projects
    purple = "\033[128m"        # used to highlight contexts
    white = "\033[37m"          # used when also supplying a background
    reset = "\033[0m"           # resets all color, reverts to default printing


class bgcolor:
    black = "\033[40m"
    red = "\033[41m"


class style:
    bold = "\033[1m"
    underline = "\033[4m"
    reverse = "\033[7m"


# ---------------------------------------------------------------------------
# Bridge Pattern: Implementation interface
# ---------------------------------------------------------------------------

class StorageBackend(ABC):
    """Abstract interface for task persistence (the 'Implementation' in the
    Bridge pattern).  Concrete backends handle low-level file I/O while the
    TaskManager abstraction delegates all storage work here."""

    @abstractmethod
    def load(self, path):
        """Read tasks from *path* and return a list of task dicts."""

    @abstractmethod
    def save(self, path, tasks):
        """Persist a list of task dicts to *path* (crash-safe)."""

    @abstractmethod
    def create(self, path):
        """Create a new, empty task file (and parent directories)."""

    @abstractmethod
    def delete(self, path):
        """Delete the task file at *path* and its sidecar config."""

    @abstractmethod
    def list_files(self):
        """Return a list of available task file names."""

    @abstractmethod
    def file_exists(self, path):
        """Return True if the task file at *path* exists."""

    @abstractmethod
    def load_lvl(self, path):
        """Read the foresight level for *path*, defaulting to 4."""

    @abstractmethod
    def save_lvl(self, path, value):
        """Persist the foresight level for *path*."""

    @abstractmethod
    def migrate_json(self, json_path, txt_path):
        """One-shot migration of a legacy json file into the native format."""


# ---------------------------------------------------------------------------
# Bridge Pattern: Concrete Implementation — todo.txt backend
# ---------------------------------------------------------------------------

class TodoTxtBackend(StorageBackend):
    """Concrete storage backend that persists tasks as todo.txt files.
    Writes are crash-safe: data is flushed to a temporary file first, then
    atomically moved into place via os.replace()."""

    def __init__(self, target_dir):
        self._target_dir = target_dir

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _is_date(token):
        """True if a token looks like a todo.txt date (YYYY-MM-DD)."""
        return re.match(r'^\d{4}-\d{2}-\d{2}$', token) is not None

    @staticmethod
    def _conf_path(path):
        """Path of the sidecar that stores per-file view settings (foresight
        level).  Kept separate so the todo.txt file itself stays a pure list
        of tasks."""
        return join(dirname(path), "." + basename(path) + ".conf")

    @staticmethod
    def _line_to_task(line):
        """Parse a single todo.txt line into a task dict."""
        t = {"done": False, "completed": None, "priority": None,
             "created": None, "due": None, "task": ""}
        tokens = line.split(" ")
        i = 0
        # completion marker and optional completion date
        if i < len(tokens) and tokens[i] == "x":
            t["done"] = True
            i += 1
            if i < len(tokens) and TodoTxtBackend._is_date(tokens[i]):
                t["completed"] = tokens[i]
                i += 1
        # priority, e.g. (A)
        if i < len(tokens) and re.match(r'^\([A-Z]\)$', tokens[i]):
            t["priority"] = tokens[i][1]
            i += 1
        # creation date
        if i < len(tokens) and TodoTxtBackend._is_date(tokens[i]):
            t["created"] = tokens[i]
            i += 1
        # the rest is the description, with the due: tag pulled out as metadata
        description = []
        for token in tokens[i:]:
            due = re.match(r'^due:(\d{4}-\d{2}-\d{2})$', token)
            if due:
                t["due"] = due.group(1)
            else:
                description.append(token)
        t["task"] = " ".join(description)
        return t

    @staticmethod
    def _task_to_line(t):
        """Serialize a task dict back into a todo.txt line."""
        parts = []
        if t["done"]:
            parts.append("x")
            if t["completed"]:
                parts.append(t["completed"])
        elif t["priority"]:
            parts.append("(" + t["priority"] + ")")
        if t["created"]:
            parts.append(t["created"])
        if t["task"]:
            parts.append(t["task"])
        if t["due"]:
            parts.append("due:" + t["due"])
        return " ".join(parts)

    # -- interface ---------------------------------------------------------

    def load(self, path):
        """Read a todo.txt file into a list of task dicts.  IDs are assigned
        as the smallest available positive integers so that gaps left by
        deleted tasks are reused, keeping ID numbers low."""
        parsed = []
        with open(path) as todofile:
            for line in todofile:
                line = line.rstrip("\n")
                if line.strip() == "":
                    continue
                parsed.append(self._line_to_task(line))
        # assign the smallest available positive integer IDs
        used = set()
        for t in parsed:
            next_id = 1
            while next_id in used:
                next_id += 1
            t["id"] = next_id
            used.add(next_id)
        return parsed

    def save(self, path, tasks):
        """Write the in-memory task list to a todo.txt file.  Uses a
        temporary file + os.replace() so that a crash during the write can
        never leave the original file truncated or empty."""
        tmp = path + ".tmp"
        with open(tmp, "w") as todofile:
            for t in tasks:
                todofile.write(self._task_to_line(t) + "\n")
            todofile.flush()
            os.fsync(todofile.fileno())
        os.replace(tmp, path)

    def create(self, path):
        """Create an empty todo.txt file and its parent directory."""
        if not os.path.exists(self._target_dir):
            os.mkdir(self._target_dir, 0o755)
        open(path, "w").close()
        self.save_lvl(path, 4)

    def delete(self, path):
        """Delete a todo.txt file and its per-file settings sidecar."""
        os.remove(path)
        conf = self._conf_path(path)
        if isfile(conf):
            os.remove(conf)

    def list_files(self):
        """Return a list of available task files (todo.txt files only)."""
        return [f for f in listdir(self._target_dir)
                if isfile(join(self._target_dir, f)) and f.endswith(".txt")]

    def file_exists(self, path):
        """Return True if the task file at *path* exists."""
        return isfile(path)

    def load_lvl(self, path):
        """Read the foresight level for the current file, defaulting to 4."""
        try:
            with open(self._conf_path(path)) as conf:
                value = int(conf.read().strip())
                return value if value in range(1, 5) else 4
        except BaseException:
            return 4

    def save_lvl(self, path, value):
        """Persist the foresight level for the current file."""
        with open(self._conf_path(path), "w") as conf:
            conf.write(str(value))

    def migrate_json(self, json_path, txt_path):
        """One-shot migration of a legacy json file into todo.txt format."""
        with open(json_path) as legacy:
            old = json.load(legacy)
        migrated = []
        for o in old.get("tasks", []):
            t = {"done": str(o.get("done")) == "true", "completed": None,
                 "priority": None, "created": None, "due": None,
                 "task": str(o.get("task", ""))}
            # the old format stored the due date as a unix timestamp
            if "due" in o:
                try:
                    t["due"] = date.fromtimestamp(int(o["due"])).isoformat()
                except BaseException:
                    t["due"] = None
            migrated.append(t)
        self.save(txt_path, migrated)
        # carry the foresight level over into the new sidecar
        try:
            legacy_lvl = int(old["settings"][0]["lvl"])
        except BaseException:
            legacy_lvl = 4
        self.save_lvl(txt_path, legacy_lvl if legacy_lvl in range(1, 5) else 4)
        return migrated


# ---------------------------------------------------------------------------
# Bridge Pattern: Abstraction — task manager
# ---------------------------------------------------------------------------

class TaskManager:
    """High-level task operations (the 'Abstraction' in the Bridge pattern).
    Delegates all persistence work to a StorageBackend implementation via the
    bridge reference self.backend."""

    def __init__(self, backend):
        self.backend = backend
        self.tasks = []

    def load(self, path):
        """Load tasks from the backend."""
        self.tasks = self.backend.load(path)
        return self.tasks

    def save(self, path):
        """Persist the current task list via the backend."""
        self.backend.save(path, self.tasks)

    def add_task(self, text, path):
        """Add a new task with optional natural 'in X days' due date."""
        t = {"done": False, "completed": None, "priority": None,
             "created": today(), "due": None, "task": text}
        # if a natural 'in X days' suffix is present, convert it to a due: tag
        # and strip it from the description
        dueTime = re.search(r'(in\s+(\d+?)\s+day(s\b|\b))$', text, re.M | re.I)
        if dueTime:
            dueDays = int(re.search(r'(\d+)', dueTime.group(), re.M | re.I).group())
            t["task"] = text[:-(len(dueTime.group()) + 1)]
            t["due"] = (date.today() + timedelta(days=dueDays)).isoformat()
        self.tasks.append(t)
        # assign the smallest available ID to the new task
        used = {task["id"] for task in self.tasks if "id" in task}
        next_id = 1
        while next_id in used:
            next_id += 1
        t["id"] = next_id
        self.save(path)

    def remove_task(self, n, path):
        """Remove items from the task list.  If called without parameters,
        purge all done tasks."""
        # if removeTask was called without any parameters, purge all done tasks
        if len(n.split()) == 0:
            targets = [t["id"] for t in self.tasks if t["done"]]
        # otherwise move through the passed parameters
        else:
            targets = n.split()
        for token in targets:
            try:
                check = int(token)
            except ValueError:
                updateMsg("Please use the id of the task", 0)
                continue
            match = next((t for t in self.tasks if t["id"] == check), None)
            if match is None:
                updateMsg("Unable to find task id " + str(check), 0)
            elif not match["done"]:
                updateMsg("Unable to remove unfinished tasks", 0)
            else:
                self.tasks.remove(match)
        self.save(path)

    def done_toggle(self, n, path):
        """Toggle item's done state instead of directly removing it."""
        global openTasks
        for token in n.split():
            try:
                check = int(token)
            except ValueError:
                updateMsg("Please use the id of the task", 0)
                continue
            match = next((t for t in self.tasks if t["id"] == check), None)
            if match is None:
                updateMsg("Unable to find task id " + str(check), 0)
            elif not match["done"]:
                match["done"] = True
                match["completed"] = today()
                if openTasks > 0:
                    openTasks = openTasks - 1
                updateMsg("Marked task as done", 4)
            else:
                match["done"] = False
                match["completed"] = None
                openTasks = openTasks + 1
                updateMsg("Marked task as not done", 4)
        self.save(path)


# ---------------------------------------------------------------------------
# Instantiate the bridge: concrete backend + task manager
# ---------------------------------------------------------------------------

backend = TodoTxtBackend(targetDir)
manager = TaskManager(backend)


# ---------------------------------------------------------------------------
# UI helpers (unchanged from original, except using manager/backend)
# ---------------------------------------------------------------------------

# creates a strikethrough effect on fonts that support it
def strike(text):
    return '\u0336'.join(text) + '\u0336'


# today's date as an ISO string (todo.txt date format)
def today():
    return date.today().isoformat()


# clear screen buffer
def clearScreen():
    os.system("cls" if os.name == "nt" else "clear")


# fancy lines
def titleLine(message, seperator):
    return print(message.center(int(size[1]), seperator))


# update feedback messages
def updateMsg(msgBody, msgType):
    global message
    hint = [color.yellow + " [!] ",
            color.yellow + " [?] ",
            color.red + " [×] ",
            color.green + " [+] ",
            color.green + " [✓] "]
    message = hint[msgType] + msgBody + " "


# set different mode
def mode(m):
    modes = [color.white + " NORMAL ",
             color.yellow + " HELP ",
             color.red + " DELETION ",
             color.yellow + " FORESIGHT ",
             color.yellow + " OPEN FILE ",
             color.yellow + " NEW FILE "]
    return modes[m]


# render the modeline
def modeline(v):
    # TODO make reflow work on terminals that support reflow by resize
    size = os.popen('stty size', 'r').read().split()
    escLength = 15
    actions = [":h Help | :o Open | :d Done | :p Purge | :r Remove",
               "enter Go Back",
               "enter Go Back | id Remove File",
               "enter Go Back | value Set Foresight",
               "enter Go Back | id Open File",
               "enter Go Back | name Create New File"]
    left = mode(v) + color.white + " " + actions[v] + " "
    right = " #" + str(openTasks) + " ~" + str(lvl) + " " + message
    # calculate padding and account for escape sequence color codes
    padding = int(size[1]) - len(left) - len(right) + escLength
    output = left + " " * padding + right
    if (len(output) - escLength) > int(size[1]):
        overflow = len(output) - escLength - int(size[1]) + 4
        return print(style.reverse + output[:-overflow] + "... " + color.reset)
    else:
        return print(style.reverse + output + color.reset)


# render filename above task list
def fileline():
    if len(backend.list_files()) > 1:
        indicator = " [+]"
    else:
        indicator = ""
    size = os.popen('stty size', 'r').read().split()
    padding = int(size[1]) - len(fileName) - len(indicator)
    print(color.white + style.reverse + " " + fileName + indicator + " " * (padding - 1) + color.reset + "\n")


# ---------------------------------------------------------------------------
# Core application routines (using manager/backend bridge)
# ---------------------------------------------------------------------------

# check if the task file exists, execute creation if not
def fileCheck(path):
    if backend.file_exists(path):
        updateMsg("File loaded", 4)
        taskList(path)
    else:
        # if no todo.txt exists yet but a legacy json file does, migrate it once.
        # the original json is left in place untouched as a backup.
        legacy = path[:-4] + ".json" if path.endswith(".txt") else path + ".json"
        if backend.file_exists(legacy):
            manager.tasks = backend.migrate_json(legacy, path)
            updateMsg("Migrated tasks from json", 4)
            taskList(path)
        else:
            fileCreate(path)


# create an empty todo.txt file and directory
def fileCreate(path):
    backend.create(path)
    updateMsg("New file storage created", 4)
    taskList(path)


# add a new task to the todo.txt file
def addTask(n):
    manager.add_task(n, targetFile)
    updateMsg("New task added", 3)
    taskList(targetFile)


# remove items from the todo.txt file
def removeTask(n):
    manager.remove_task(n, targetFile)
    updateMsg("Removed task", 2)
    taskList(targetFile)


# toggle item's done state instead of directly removing it
def doneToggle(n):
    manager.done_toggle(n, targetFile)
    taskList(targetFile)


# read todo.txt file into memory and print to stdout as sorted groups
def renderTasks(content):
    global lvl
    global openTasks
    group = {}
    gkey = ""
    gval = ""
    glvl = 0
    task = 0
    manager.load(content)
    lvl = backend.load_lvl(content)
    # let's get things sorted
    for o in manager.tasks:
        # if a due date exists, assign o to a group based on how far away it is
        if o["due"]:
            days = (date.fromisoformat(o["due"]) - date.today()).days
            if days < 0:
                gkey = 2
                gval = style.bold + color.red + "Overdue"
                glvl = 3
            elif days == 0:
                gkey = 3
                gval = color.red + "Today"
                glvl = 1
            elif days == 1:
                gkey = 4
                gval = color.yellow + "Tomorrow"
                glvl = 1
            else:
                gkey = int(days + 4)
                gval = "In " + str(int(days)) + " days"
                glvl = 4
        # if there's no due date, put o into the "whenever" group
        else:
            gkey = 1
            gval = color.white + "Unscheduled"
            glvl = 2
        # create groups dynamically based on the existence of keys
        if gkey not in group:
            group[gkey] = [{
                "due": gval,
                "lvl": glvl,
                "item": []
                }]
        # add tasks to their group keys
        if not o["done"]:
            taskDescription = str(o["task"])
            doneState = '   '
            task = task + 1
        else:
            taskDescription = strike(str(o["task"]))
            doneState = color.green + ' ✓ ' + color.reset
        openTasks = task
        idSpacing = (5 - len(str(o["id"]))) * " "
        group[gkey][0]["item"].append(doneState + str(o["id"]) + idSpacing + taskDescription)
    #print something cute if no tasks exist
    if not group:
        moji("empty")
    else:
        printCounter = 0
        # and finally print everything to the terminal
        # since the sortKey is useless to us, we're only interested in the dueGroups
        # for the output, we still need to query sortKey to get proper sorting
        for (sortKey, dueGroups) in sorted(group.items()):
            for dueGroup in dueGroups:
                # print only the dueGroup that matches current view level settings
                if dueGroup["lvl"] <= lvl:
                    printCounter = printCounter + 1
                    print("   " + dueGroup["due"] + color.reset + "\n")
                    for task in dueGroup["item"]:
                        print(task)
                    print("")
        # remind user if hidden tasks
        if printCounter == 0:
            moji("hidden")


# display todo.txt content as task list
def taskList(tasks):
    clearScreen()
    fileline()
    renderTasks(tasks)
    stdout.write("\x1b]2;" + appName + "\x07")
    modeline(0)
    userInput()


# await user input and add or remove tasks
def userInput():
    # print("Type ':help' or ':?' for more info")
    choice = input(" > ").strip()
    if choice in (":help", ":?", ":h"):
        userHelp()
    elif choice in (":exit", ":quit", ":q", ":e"):
        byebye
    elif choice.startswith(":d"):
        doneToggle(choice[2:].strip())
    elif choice.startswith(":f"):
        foresight(choice[2:].strip())
    elif choice.startswith(":p"):
        removeTask(choice[2:].strip())
    elif choice.startswith(":o"):
        fileswitcher()
    elif choice.startswith(":n"):
        newfile(choice[2:].strip())
    elif choice.startswith(":r"):
        fileRemover()
    # catch user input error to prevent creation of unneccesary tasks
    elif choice.lower() in ("quit", "exit"):
        updateMsg("Did you want to quit?", 1)
        taskList(targetFile)
    elif choice == "":
        updateMsg("Not sure what to do", 1)
        taskList(targetFile)
    else:
        addTask(choice)


# update foresight
def foresight(n):
    global lvl
    try:
        value = int(n)
        if value in range(1, 5):
            lvl = value
            backend.save_lvl(targetFile, value)
            updateMsg("Foresight set to " + str(value), 4)
        else:
            raise ValueError
    except BaseException:
        clearScreen()
        fileline()
        print("""   Change amount of tasks to display

   1    tasks due today and tomorrow
   2    same as 1 plus unscheduled
   3    same as 2 plus overdue
   4    same as 3 plus tasks due days after
""")
        modeline(3)
        foresightSelect = input(" > ").strip()
        try:
            select = int(foresightSelect)
            foresight(select)
        except BaseException:
            updateMsg("Please select a value between 1-4", 0)
    taskList(targetFile)


# switch to other files
def fileswitcher():
    global targetFile
    global fileName
    clearScreen()
    fileline()
    print("   Open available file\n")
    i = 0
    fileList = backend.list_files()
    for singleFile in fileList:
        i = i + 1
        idSpacing = (5 - len(str(i))) * " "
        print("   " + str(i) + idSpacing + singleFile)
    print("\n")
    modeline(4)
    fileSelect = input(" > ").strip()
    if fileSelect.startswith("a"):
        taskList(targetFile)
    elif int(fileSelect):
        try:
            selection = int(fileSelect) - 1
            if selection <= len(fileList):
                fileName = fileList[selection]
                targetFile = targetDir + "/" + fileName
                updateMsg("Opened file", 4)
                taskList(targetFile)
            else:
                raise
        except:
            updateMsg("Please select a valid option", 0)
            fileswitcher()
    else:
        updateMsg("Please select a valid option", 0)
        fileswitcher()


# routine to delete unused/empty files manually
def fileRemover():
    global fileName
    global targetDir
    clearScreen()
    fileline()
    print("   Select a file for removal\n")
    i = 0
    deletionList = backend.list_files()
    if fileName in deletionList:
        deletionList.remove(fileName)
    for singleFile in deletionList:
        i = i + 1
        idSpacing = (5 - len(str(i))) * " "
        print("   " + str(i) + idSpacing + singleFile)
    print("\n")
    modeline(2)
    try:
        deleteFile = input(" > ").strip().split()[0]
        try:
            deletionPath = targetDir + "/" + deletionList[int(deleteFile) -1]
            try:
                backend.delete(deletionPath)
                updateMsg("File deleted", 2)
                taskList(targetFile)
            except:
                updateMsg("Could not delete file", 0)
                taskList(targetFile)
        except:
            updateMsg("Please select a valid option", 0)
            fileRemover()
    except:
        updateMsg("No file selected", 0)
        taskList(targetFile)


# create new file
def newfile(file):
    global targetFile
    global fileName
    global lvl
    clearScreen()
    fileline()
    if len(file) < 1:
        print("   Please specify a new filename\n")
        modeline(5)
        newFile = input(" > ").strip().split()[0]
        if len(newFile) > 0:
            manager.tasks = []
            lvl = 4
            fileName = newFile + ".txt"
            targetFile = targetDir + "/" + fileName
            fileCheck(targetFile)
        else:
            updateMsg("Please specify a filename", 0)
            taskList(targetFile)
    elif len(file) >= 1:
        manager.tasks = []
        lvl = 4
        fileName = file.strip().split(" ")[0] + ".txt"
        targetFile = targetDir + "/" + fileName
        fileCheck(targetFile)


# short help print
def userHelp():
    clearScreen()
    fileline()
    print("""   Available commands are

   :d (id ...)   Mark a task id as done, seperate multiple tasks by space
   :p (id ...)   Permanently remove a task, seperate multiple tasks by space
   :f (1-4)      Viewing level of tasks, type :f to see further explanation
   :o            Open another existing file
   :n (name)     Creates a new file or opens existing one if filename exists
   :r            Remove a file from disk
   :help, :?     View this screen
   :quit, :exit  exit the application
""")
    modeline(1)
    input(" > Press return to go back...")
    taskList(targetFile)


# cute
def moji(mode):
    size = os.popen('stty size', 'r').read().split()
    kao = ""
    msg = ""
    if mode == "empty":
        kao = "(.❛ ᴗ ❛.) "
        msg = "An empty file is nice, but how about adding some tasks?"
    elif mode == "hidden":
        kao = "(￣ω￣;) "
        msg = "I know you think you\'re done but trust me there\'s more..."
    else:
        kao = "(╥﹏╥) "
        msg = "You\'ll never get to see me..."
    padding = int(size[1]) - len(kao) - len(msg)
    halfpad = int(padding / 2)
    print("\n\n\n\n" + " " * halfpad + kao + msg + " " * halfpad + "\n\n\n\n")

# execute program only if not imported as module
if __name__ == "__main__":
    fileCheck(targetFile)
