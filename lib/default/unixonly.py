#!/usr/local/bin/python

import default, plugins, os, sys, subprocess, signal
        
# Unlike earlier incarnations of this functionality,
# we don't rely on sharing displays but create our own for each test run.
class VirtualDisplayResponder(plugins.Responder):
    instance = None
    def __init__(self, *args):
        self.displayName = None
        self.displayMachine = None
        self.displayPid = None
        self.displayProc = None
        self.guiSuites = []
        self.diag = plugins.getDiagnostics("virtual display")
        VirtualDisplayResponder.instance = self
        
    def addSuites(self, suites):
        guiSuites = filter(lambda suite : suite.getConfigValue("use_case_record_mode") == "GUI", suites)
        # On UNIX this is a virtual display to set the DISPLAY variable to, on Windows it's just a marker to hide the windows
        if os.name != "posix":
            self.setHideWindows(guiSuites)
        elif not self.displayName:
            self.setUpVirtualDisplay(guiSuites)

    def setHideWindows(self, suites):
        if len(suites) > 0 and not self.displayName:
            self.displayName = "HIDE_WINDOWS"
                              
    def setUpVirtualDisplay(self, guiSuites):
        if len(guiSuites) == 0:
            return
        machines = self.findMachines(guiSuites)
        machine, display, pid = self.getDisplay(machines, guiSuites[0].app)
        if display:
            self.displayName = display
            self.displayMachine = machine
            self.displayPid = pid
            self.guiSuites = guiSuites
            print "Tests will run with DISPLAY variable set to", display
        elif len(machines) > 0:
            plugins.printWarning("Failed to start virtual display on " + ",".join(machines) + " - using real display.")

    def getDisplay(self, machines, app):
        for machine in machines:
            displayName, pid = self.createDisplay(machine, app)
            if displayName:
                return machine, displayName, pid
            else:
                plugins.printWarning("Virtual display program Xvfb not available on " + machine)
        return None, None, None
    
    def findMachines(self, suites):
        allMachines = []
        for suite in suites:
            for machine in suite.getConfigValue("virtual_display_machine"):
                if machine == "localhost": # Local to the test run, not to where we're trying to run...
                    machine = suite.app.getRunMachine()
                if not machine in allMachines:
                    allMachines.append(machine)
        return allMachines

    def notifyExtraTest(self, *args):
        # Called when a slave is given an extra test to solve
        if self.displayProc is not None and self.displayProc.poll() is not None:
            # If Xvfb has terminated, we need to restart it
            self.setUpVirtualDisplay(self.guiSuites)
            
    def notifyAllComplete(self):
        self.cleanXvfb()
    def notifyKillProcesses(self, *args):
        self.cleanXvfb()
    def cleanXvfb(self):
        if self.displayName and os.name == "posix":
            if self.displayMachine == "localhost":
                print "Killing Xvfb process", self.displayPid
                try:
                    os.kill(self.displayPid, signal.SIGTERM)
                except OSError:
                    print "Process had already terminated"
            else:
                self.killRemoteServer()
            self.displayName = None

    def killRemoteServer(self):
        self.diag.info("Getting ps output from " + self.displayMachine)
        print "Killing remote Xvfb process on", self.displayMachine, "with pid", self.displayPid
        self.guiSuites[0].app.runCommandOn(self.displayMachine, [ "kill", str(self.displayPid) ])

    def createDisplay(self, machine, app):
        if not self.canRunVirtualServer(machine, app):
            return None, None

        startArgs = self.getVirtualServerArgs(machine, app)
        return self.startXvfb(startArgs, machine)

    def startXvfb(self, startArgs, machine):
        self.diag.info("Starting Xvfb using args " + repr(startArgs))
        self.displayProc = subprocess.Popen(startArgs, stdin=open(os.devnull), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        line = plugins.retryOnInterrupt(self.displayProc.stdout.readline)
        if line.find("Time Out!") != -1:
            self.displayProc.wait()
            self.displayProc.stdout.close()
            # We try again and hope for a better process ID!
            return self.startXvfb(startArgs, machine)
        try:
            displayNum, pid = map(int, line.strip().split(","))
            self.displayProc.stdout.close()
            return self.getDisplayName(machine, displayNum), pid
        except ValueError: #pragma : no cover - should never happen, just a fail-safe
            print "Failed to parse line :\n " + line + self.displayProc.stdout.read()
            return None, None
            
    def getVirtualServerArgs(self, machine, app):
        binDir = plugins.installationDir("libexec")
        fullPath = os.path.join(binDir, "startXvfb.py")
        logDir = os.path.join(app.writeDirectory, "Xvfb") 
        plugins.ensureDirectoryExists(logDir)
        python = self.findPython(machine)
        cmdArgs = [ python, "-u", fullPath, logDir ]
        return app.getCommandArgsOn(machine, cmdArgs)

    def findPython(self, machine):
        # In case it isn't the default, allow for a ttpython script in the installation
        if machine == "localhost":
            return sys.executable
        
        localPointer = plugins.installationPath("bin/ttpython")
        if localPointer:
            return localPointer
        else: # pragma : no cover -there is one in our local installation whether we like it or not...
            return "python"
        
    def getDisplayName(self, machine, displayNumber):
        # No point in using the port if we don't have to, this seems less reliable if the process is local
        # X keeps track of these numbers internally and connecting to them works rather better.
        displayStr = ":" + str(displayNumber) + ".0"
        if machine == "localhost":
            return displayStr
        else:
            return machine + displayStr

    def canRunVirtualServer(self, machine, app):
        retcode = app.runCommandOn(machine, [ "which", "Xvfb" ], collectExitCode=True)
        return retcode == 0
