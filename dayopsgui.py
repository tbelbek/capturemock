helpDescription = """
It follows the usage of the Carmen configuration.""" 

import unixConfig, guiplugins, os, string

def getConfig(optionMap):
    return DayOPsGUIConfig(optionMap)

class DayOPsGUIConfig(unixConfig.UNIXConfig):
    def __init__(self, optionMap):
        unixConfig.UNIXConfig.__init__(self, optionMap)
    def printHelpDescription(self):
        print helpDescription
        unixConfig.UNIXConfig.printHelpDescription(self)
    def getExecuteCommand(self, binary, test):
        propFile = test.makeFileName("properties")
        logFile = test.makeFileName("dmserverlog", temporary=1)
        os.environ["DMG_RUN_TEST"] = propFile + "#" + logFile
        return unixConfig.UNIXConfig.getExecuteCommand(self, binary, test)

class JavaPropertyReader:
    def __init__(self, filename):
        self.properties = {}
        if os.path.isfile(filename):
            for line in open(filename).xreadlines():
                line = line.strip()
                if line.startswith("#") or line.find("=") == -1:
                    continue
                parts = line.split("=")
                if len(parts) == 2:
                    self.properties[parts[0]] = parts[1]
    def get(self, key):
        if not self.properties.has_key(key):
            return ""
        else:
            return self.properties[key]
    def set(self, key, value):
        self.properties[key] = value
    def writeFile(self, filename):
        wFile = open(filename, "w")
        for key in self.properties.keys():
            wFile.write(key + "=" + self.properties[key] + os.linesep)

class RecordTest(guiplugins.RecordTest):
    def __init__(self, test):
        guiplugins.RecordTest.__init__(self, test)
        self.test = test
        self.test.setUpEnvironment(1)
        baseName = os.environ["DMG_PROPS_INPUT"]
        propFileInCheckout = os.path.join(test.app.checkout, "Descartes", "DMG", baseName)
        defaultHTTPdir = os.environ["DMG_RECORD_HTTP_DIR"]
        self.test.tearDownEnvironment(1)
        self.props = JavaPropertyReader(propFileInCheckout)
        self.optionGroup.addOption("v", "Version", "")
        self.optionGroup.addOption("host", "DMServer host", self.props.get("host"))
        self.optionGroup.addOption("port", "Port", self.props.get("port"))
        self.optionGroup.addOption("w", "HTTP dir", defaultHTTPdir)
    def canPerformOnTest(self):
        existName = self.test.makeFileName("input")
        if os.path.isfile(existName):
            return 0
        return 1
    def __call__(self, test):
        serverLog = test.makeFileName("input")
        propFileInTest = test.makeFileName("properties")
        args = [ test.abspath, serverLog, propFileInTest ]
        os.environ["DMG_RECORD_TEST"] = string.join(args,":")
        self.props.set("host", self.optionGroup.getOptionValue("host"))
        self.props.set("port", self.optionGroup.getOptionValue("port"))
        #
        # TODO: Change testPropFile file according to option for HTTP dir too
        #
        self.props.writeFile(propFileInTest)
        guiplugins.RecordTest.__call__(self, test)
        

