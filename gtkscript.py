
"""
The idea of this module is to implement a generic record/playback tool for GTK GUIs that
will create scripts in terms of the domain language. These will then be much more stable
than traditional such tools that create complicated Tcl scripts with lots of references
to pixel positions etc., which tend to be extremely brittle if the GUI is updated.

(1) For user actions such as clicking a button, selecting a list item etc., the general idea
is to add an extra argument to the call to 'connect', so that instead of writing

button.connect("clicked", myMethod)

you would write

eventHandler.connect("save changes", "clicked", button, myMethod)

thus tying the user action to the script command "save changes". If you set up a record
script, then the module will write "save changes" to the script whenever the button is clicked.
Conversely, if you set up a replay script, then on finding the command "save changes", the
module will emit the "clicked" signal for said button, effectively clicking it programatically.

This means that, so long as my GUI has a concept of "save changes", I can redesign the GUI totally,
making the user choose to do this via a totally different widget, but all my scripts wiill
remaing unchanged.

(2) Some GUI widgets have "state" rather than relying on signals (for example text entries, toggle buttons),
so that the GUI itself may not necessarily make any calls to 'connect'. But you still want to generate
script commands when they change state, and be able to change them programatically. I have done this
by wrapping the constructor for such widgets, so that instead of

entry = gtk.Entry()

you would write

entry = eventHandler.createEntry("file name")

which would tie the "focus-out-event" to the script command "enter file name = ".

(3) There are also composite widgets like the TreeView where you need to be able to specify an argument.
In this case the application has to provide extra information as to how the text is to be translated
into selecting an item in the tree. So, for example:

treeView.connect("row_activated", myMethod)

might become

eventHandler.connect("select file", "row_activated", treeView, myMethod, (column, dataIndex))

(column, dataIndex) is a tuple to tell it which data in the tree view we are looking for. So that
the command "select file foobar.txt" will search the tree's column <column> and data index <dataIndex>
for the text "foobar.txt" and select that row accordingly.

(4) Idle handlers can also be scripted: it's often a significant event when an idle handler exits and
you want to script waiting for that to happen. Therefore you can replace

gtk.idle_add(myMethod)

with

eventHandler.addIdle("background processing", myMethod)

which, as expected, will create the command "wait for background processing" when this idle handler exits
(returns gtk.FALSE). On running the script, it will do as expected and wait for this idle handler to exit
before proceeding.
"""

import gtk, os, string, sys

# Exception to throw when scripts go wrong
class GtkScriptError(RuntimeError):
    pass

class Event:
    def __init__(self, name, widget):
        self.name = name
        self.widget = widget
    def widgetHasChanged(self):
        return 1
    def outputForScript(self, *args):
        return self.name
    # Return 1 if we succeed in generating, 0 if we should wait for some external action
    def generate(self, argumentString):
        return 1

class ActivateEvent(Event):
    def __init__(self, name, widget, active = gtk.TRUE):
        Event.__init__(self, name, widget)
        self.active = active
    def widgetHasChanged(self):
        return self.widget.get_active() == self.active
    def generate(self, argumentString):
        self.widget.set_active(self.active)
        return 1

class EntryEvent(Event):
    def __init__(self, name, widget):
        Event.__init__(self, name, widget)
        self.oldText = ""
    def widgetHasChanged(self):
        text = self.widget.get_text()
        return text != self.oldText
    def outputForScript(self, *args):
        text = self.widget.get_text()
        self.oldText = text
        return self.name + " " + text
    def generate(self, argumentString):
        self.widget.set_text(argumentString)
        return 1
        
class SignalEvent(Event):
    def __init__(self, name, widget, signalName):
        Event.__init__(self, name, widget)
        self.signalName = signalName
    def generate(self, argumentString):
        self.widget.emit(self.signalName, *argumentString)
        return 1

class TreeViewSignalEvent(SignalEvent):
    def __init__(self, name, widget, signalName, argumentParseData):
        SignalEvent.__init__(self, name, widget, signalName)
        self.column, self.valueId = argumentParseData
        self.model = widget.get_model()
    def outputForScript(self, path, *args):
        nodeLabel = self.model.get_value(self.model.get_iter(path), self.valueId)
        return self.name + " " + nodeLabel
    def generate(self, argumentString):
        arguments = argumentString.split(" ")
        rowText = arguments[0]
        path = self.findTreePath(self.model.get_iter_root(), rowText)
        if not path:
            raise GtkScriptError, "Could not find row '" + rowText + "' in Tree View"
        userArgs = argumentString.replace(rowText, "").strip()
        self.widget.emit(self.signalName, path, self.column, *userArgs)
        return 1
    def pathHasText(self, iter, argumentText):
        return self.model.get_value(iter, self.valueId) == argumentText
    def findTreePath(self, iter, argumentText):
        if self.pathHasText(iter, argumentText):
            return self.model.get_path(iter)
        childIter = self.model.iter_children(iter)
        if childIter:
            childPath = self.findTreePath(childIter, argumentText)
            if childPath:
                return childPath
        nextIter = self.model.iter_next(iter)
        if nextIter:
            return self.findTreePath(nextIter, argumentText)
        return None

class IdleHandler(Event):
    def __init__(self, name, callback):
        Event.__init__(self, "wait for " + name, None)
        self.callback = callback
        self.exited = 0
        self.observers = []
        gtk.idle_add(self.runCallback)
    def addObserver(self, observer):
        self.observers.append(observer)
    def runCallback(self):
        retValue = self.callback()        
        if retValue == gtk.FALSE:
            self.exited = 1
            for observer in self.observers:
                observer.idleHandlerExited(self)
        return retValue
    def generate(self, argumentString):
        return self.exited

class EventHandler:
    def __init__(self):
        self.replayScript = None
        self.recordScript = None
    def hasScript(self):
        return self.replayScript or self.recordScript
    def setScripts(self, replayScriptName, recordScriptName):
        if replayScriptName and replayScriptName == recordScriptName:
            raise GtkScriptError, "Cannot record to the same script we are replaying"
        if replayScriptName:
            self.replayScript = ReplayScript(replayScriptName)
        if recordScriptName:
            self.recordScript = RecordScript(recordScriptName)
    def connect(self, eventName, signalName, widget, method, argumentParseData = None, *data):
        widget.connect(signalName, method, *data)
        if self.hasScript():
            stdName = self.standardName(eventName)
            signalEvent = self.createSignalEvent(signalName, stdName, widget, argumentParseData)
            self.addEventToScripts(signalEvent, signalName)
    def addEventToScripts(self, event, signalName):
        if self.replayScript:
            self.replayScript.addEvent(event)
        if self.recordScript:
            self.recordScript.addEvent(event, signalName)
    def createSignalEvent(self, signalName, eventName, widget, argumentParseData):
        if isinstance(widget, gtk.TreeView):
            return TreeViewSignalEvent(eventName, widget, signalName, argumentParseData)
        else:
            return SignalEvent(eventName, widget, signalName)
    def standardName(self, name):
        firstIndex = None
        lastIndex = len(name)
        for i in range(len(name)):
            if name[i] in string.letters or name[i] in string.digits:
                if firstIndex is None:
                    firstIndex = i
                lastIndex = i
        return name[firstIndex:lastIndex + 1].lower()
    def addIdle(self, handlerName, method):
        if self.hasScript():
            handler = IdleHandler(handlerName, method)
            if self.replayScript:
                self.replayScript.addEvent(handler)
                handler.addObserver(self.replayScript)
            if self.recordScript:
                handler.addObserver(self.recordScript)
        else:
            gtk.idle_add(method)
    def createEntry(self, description):
        entry = gtk.Entry()
        if self.hasScript():
            stateChangeName = "enter " + self.standardName(description) + " ="
            entryEvent = EntryEvent(stateChangeName, entry)
            self.addEventToScripts(entryEvent, "focus-out-event")
        return entry
    def createCheckButton(self, description):
        button = gtk.CheckButton(description)
        if self.hasScript():
            checkChangeName = "check " + self.standardName(description)
            uncheckChangeName = "uncheck " + self.standardName(description)
            checkEvent = ActivateEvent(checkChangeName, button)
            uncheckEvent = ActivateEvent(uncheckChangeName, button, gtk.FALSE)
            self.addEventToScripts(checkEvent, "toggled")
            self.addEventToScripts(uncheckEvent, "toggled")
        return button

eventHandler = EventHandler()

class ReplayScript:
    def __init__(self, scriptName):
        self.events = {}
        self.commands = []
        self.pointer = 0
        if not os.path.isfile(scriptName):
            raise GtkScriptError, "Cannot replay script " + scriptName + ", no such file or directory"
        for line in open(scriptName).xreadlines():
            if line != "" and line[0] != "#":
                self.commands.append(line.strip())
        self.enableReading()
    def addEvent(self, event):
        self.events[event.name] = event
    def enableReading(self):
        # If events fail, we store them and wait for the relevant handler
        self.waitingForHandler = None
        gtk.idle_add(self.runCommands)
    def isFinished(self):
        return self.pointer >= len(self.commands)
    def runCommands(self):
        if self.isFinished():
            return gtk.FALSE

        nextCommand = self.commands[self.pointer]
        # Filter blank lines and comments
        self.pointer += 1
        try:
            return self.generateEvent(nextCommand)
        except GtkScriptError:
            print "Script terminated due to exception : "
            type, value, traceback = sys.exc_info()
            sys.excepthook(type, value, traceback)
            return gtk.FALSE
        return gtk.TRUE
    def generateEvent(self, scriptCommand):
        eventName = self.findEvent(scriptCommand)
        if not eventName:
            raise GtkScriptError, "Could not parse script command '" + scriptCommand + "'"
        argumentString = scriptCommand.replace(eventName, "").strip()
        print "'" + eventName + "' event created with arguments '" + argumentString + "'"
        event = self.events[eventName]
        if event.generate(argumentString):
            return gtk.TRUE
        else:
            self.waitingForHandler = event
            return gtk.FALSE
    def findEvent(self, command):
        for eventName in self.events.keys():
            if command.startswith(eventName):
                return eventName
        return None
    def idleHandlerExited(self, idleHandler):
        if self.waitingForHandler == idleHandler:
            self.enableReading()

            

class RecordScript:
    def __init__(self, scriptName):
        self.fileForAppend = open(scriptName, "w")
        self.events = []
    def addEvent(self, event, signalName):
        self.events.append(event)
        event.widget.connect(signalName, self.writeEvent, event)
    def writeEvent(self, widget, *args):
        event = self.findEvent(*args)
        if event.widgetHasChanged():
            self.fileForAppend.write(event.outputForScript(*args) + os.linesep)
    def findEvent(self, *args):
        for arg in args:
            if isinstance(arg, Event):
                return arg
    def idleHandlerExited(self, idleHandler):
        self.writeEvent(None, idleHandler)

            

