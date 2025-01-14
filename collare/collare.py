from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtGui import QStandardItemModel, QIcon, QFontMetrics
from PyQt5.QtCore import QTimer, QEventLoop
from PyQt5.QtWidgets import QMessageBox, QProgressDialog,QTreeWidgetItem, QFileIconProvider,QTreeWidget, QInputDialog, QHBoxLayout, QFrame, QApplication
from pathlib import Path
from subprocess import Popen, PIPE
from functools import reduce
from zipfile import ZipFile
import os, requests, json, re, base64, shutil, sys, time

collare_home = Path.home() / ".collare_projects"
current_running_file_dir, filename = os.path.split(os.path.abspath(__file__))
connected = False
supported_db_names = ["bndb","i64","idb","hop","rzdb","ghdb","jdb2","asp"]
requests.urllib3.disable_warnings()

class ProjectTree(QTreeWidget):
    def __init__(self, parent,window):
        super(ProjectTree, self).__init__(parent)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.window = window

    def setProjectData(self,server,projectName,username,password,cert,parent):
        self.server = server
        self.projectName = projectName
        self.username = username
        self.password = password
        self.cert = cert
        self.parent = parent

    def dragEnterEvent(self, event):
        event.accept()

    def deselectAll(self):
        for item in self.selectedItems():
            item.setSelected(False)

    def dragMoveEvent(self, event):
        event.accept()
        #if event.mimeData().hasUrls():
        item = self.itemAt(event.pos())
        if item: # Not none
            if item.whatsThis(0) == "binary":
                # Highlight parent folder
                self.deselectAll()
                item.parent().setSelected(True)
            elif item.whatsThis(0) == "folder":
                # Highlight current folder
                self.deselectAll()
                item.setSelected(True)
            else:
                # Higlight parent of parent (for cases where we hover over DB files listing)
                self.deselectAll()
                item.parent().parent().setSelected(True)


    def showPopupBox(self,title,text,icon):
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setIcon(icon)
        x = msg.exec_()
    
    def mimeTypes(self):
        return ["*"]

    def uploadFile(self,fsPath,remotePath):
        self.window.start_task("Uploading file ... ")
        with open(fsPath, "rb") as data_file:
            encoded_file = base64.b64encode(data_file.read()).decode("utf-8") 
        values = {'path': remotePath,"project":self.projectName,"file":encoded_file,"file_name":os.path.basename(fsPath)}
        try:
            response = requests.post(f'{self.server}/push', json=values, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
            if response.status_code != 200:
                self.showPopupBox("Error Uploading File","Something went horribly wrong!",QMessageBox.Critical)
            elif response.text == "FILE_ALREADY_EXISTS":
                self.showPopupBox("Error Uploading File","File already exists!",QMessageBox.Critical)
            self.parent.refreshProject()
        except:
            self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
            self.window.end_task()
            return
        self.window.end_task()
            

    def uploadDir(self,fs_path,path):
        self.window.start_task("Uploading directory ... ")
        if not re.match(r'^\w+$',os.path.basename(fs_path)):
            self.showPopupBox("Invalid Folder Name",f"Folder name can contain only letters, numbers and '_' (underscores). Failed with: {os.path.basename(fs_path)}",QMessageBox.Critical)
            self.window.end_task()
            return 
        for directory, subdirectories, files in os.walk(fs_path):
            for d in subdirectories:
                if not re.match(r'^\w+$',d):
                    self.showPopupBox("Invalid Folder Name",f"Folder name can contain only letters, numbers and '_' (underscores). Failed with: {d}",QMessageBox.Critical)
                    self.window.end_task()
                    return 
        # Creates the initial dir
        self.mkdir(path,os.path.basename(fs_path))
        # Base path used to get rid of the fs_path elements
        base_path_len = len(os.path.normpath(fs_path).split(os.path.sep))
        for directory, subdirectories, files in os.walk(fs_path):
            current_path = path + (os.path.normpath(directory).split(os.path.sep)[base_path_len-1:])
            for d in subdirectories:
                self.mkdir(current_path,d)
            for f in files:
                self.uploadFile(os.path.join(directory,f),current_path)
        self.window.end_task()


    def mkdir(self,path,dirname):
        # Create directory
        if not re.match(r'^\w+$',dirname):
            self.showPopupBox("Invalid Folder Name","Folder name can contain only letters, numbers and '_' (underscores).",QMessageBox.Critical)
            return
        data = {
            "project":self.projectName,
            "path": path,
            "dirname": dirname
        }
        try:
            response = requests.post(f'{self.server}/mkdir', json=data, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
            if response.status_code != 200:
                self.showPopupBox("Error Creating Folder","Something went horribly wrong!",QMessageBox.Critical)
            elif response.text == "FOLDER_ALREADY_EXISTS":
                self.showPopupBox("Error Creating Folder","Folder with this name already exists!",QMessageBox.Critical)
            self.parent.refreshProject()
        except:
            self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
            return

    def getPathToRoot(self,treeItem):
        path = [treeItem.text(0)]
        tmpItem = treeItem
        while tmpItem.parent():
            tmpItem = tmpItem.parent()
            path.insert(0, tmpItem.text(0))
        return path

    def dropEvent(self, event):
        # External source
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                # Folders currently not supported
                if os.name == 'nt':
                    url_path = url.path()[1:]
                else:
                    url_path = url.path()
                item = self.itemAt(event.pos())
                if item:
                    # Adjust target of the drop event based on where we are
                    if item.whatsThis(0) != "folder":
                        if item.parent().whatsThis(0) == "folder":
                            item = item.parent()
                        elif item.parent().whatsThis(0) == "binary":
                            item = item.parent().parent()
                        else:
                            item = item.parent().parent().parent()
                    # Upload file
                    if Path(url_path).is_dir():
                        self.uploadDir(url_path,self.getPathToRoot(item))
                    else:
                        self.uploadFile(url_path,self.getPathToRoot(item))
        else:
            # Internal drag and drop
            source_item = event.source().currentItem()
            dest_item = self.itemAt(event.pos())
            if dest_item:
                # Adjust target of the drop event based on where we are
                if dest_item.whatsThis(0) != "folder":
                    if dest_item.parent().whatsThis(0) == "folder":
                        dest_item = dest_item.parent()
                    elif dest_item.parent().whatsThis(0) == "binary":
                        dest_item = dest_item.parent().parent()
                    else:
                        dest_item = dest_item.parent().parent().parent()
                if len(self.getPathToRoot(dest_item)) > 0:
                    if source_item.whatsThis(0) == "folder" or source_item.whatsThis(0) == "binary":
                        data = {
                            "project_name": self.projectName,
                            "source_path": self.getPathToRoot(source_item),
                            "dest_path": self.getPathToRoot(dest_item) if len(self.getPathToRoot(dest_item)) > 0 else [self.projectName]
                        }
                        try:
                            response = requests.post(f'{self.server}/move', json=data, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
                        except:
                            self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
                            return
                        if response.text == "DONE":
                            #if os.path.exists(os.path.join(str(collare_home),*self.getPathToRoot(source_item))):
                                #shutil.move(os.path.join(str(collare_home),*self.getPathToRoot(source_item)),os.path.join(str(collare_home),*self.getPathToRoot(dest_item)))
                            self.parent.refreshProject()
                        elif response.text == "CHECKEDOUT_FILE":
                            self.showPopupBox("Cannot move DB item","One of the items intended to move are checked-out.",QMessageBox.Critical)
                            return
                        elif response.text == "ALREADY_EXISTS":
                            self.showPopupBox("Cannot move DB item","Item with this name already exists in destination.",QMessageBox.Critical)
                            return
                    else:
                        self.showPopupBox("Cannot move DB item","Only binaries and folders can be moved within the project tree. Not the individual DBs.",QMessageBox.Critical)



class Ui_Dialog(object):
    def prepopulateConnect(self):
        # Read previously stored connection information
        if os.path.exists(str(collare_home / "connection.json")):
            with open(str(collare_home / "connection.json"),"r") as connection_file:
                connection_data = json.load(connection_file)
                self.serverText.setText(connection_data["server"])
                self.usernameText.setText(connection_data["username"])
                self.serverCertPathText.setText(connection_data["cert"])

    def storeConnectionDetails(self,server,username,cert):
        # Store connection details
        with open(str(collare_home / "connection.json"),"w") as connection_file:
            json.dump({"username":username,"server":server,"cert":cert}, connection_file)

    def showPopupBox(self,title,text,icon):
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(text)
        msg.setIcon(icon)
        x = msg.exec_()
    
    def start_task(self,title):
        self.projectTab.setEnabled(False)
        self.progress_label.setText(title)
        loop = QEventLoop()
        QTimer.singleShot(1000, loop.quit)
        loop.exec_()

    def end_task(self):
        self.projectTab.setEnabled(True)
        self.progress_label.setText("")

    def which(self,program):
        # Search for programs in path
        def is_exe(fpath):
            return os.path.isfile(fpath) and os.access(fpath, os.X_OK)
        fpath, fname = os.path.split(program)
        if fpath:
            if is_exe(program):
                return program
        else:
            for path in os.environ["PATH"].split(os.pathsep):
                exe_file = os.path.join(path, program)
                if is_exe(exe_file):
                    return exe_file
                exe_file = os.path.join(path, f"{program}.exe")
                if is_exe(exe_file):
                    return exe_file
                exe_file = os.path.join(path, f"{program}.bat")
                if is_exe(exe_file):
                    return exe_file

        return None

    def onSuccessConnect(self):
        # Do UI changes upon connection
        self.connected = True
        self.connectStatusLabel.setText("Connected")
        self.connectStatusLabel.setStyleSheet("color: lightgreen")
        self.passwordText.setDisabled(True)
        self.usernameText.setDisabled(True)
        self.serverCertPathText.setDisabled(True)
        self.serverText.setDisabled(True)
        self.connectButton.setText("Disconnect")
        self.adminTab.setEnabled(True)
        self.newProjectFrame.setEnabled(True)
        self.existingProjectFrame.setEnabled(True)
        self.populateAllUserListings()
        self.populateExistingProjects()
        #self.projectTab.setEnabled(True)
    
    def onDisconnect(self):
        # Do UI changes upon disconnect
        self.connected = False
        self.connectStatusLabel.setText("Disconnected")
        self.connectStatusLabel.setStyleSheet("color: black")
        self.passwordText.setDisabled(False)
        self.usernameText.setDisabled(False)
        self.serverCertPathText.setDisabled(False)
        self.serverText.setDisabled(False)
        self.connectButton.setText("Connect")
        self.adminTab.setEnabled(False)
        self.newProjectFrame.setEnabled(False)
        self.existingProjectFrame.setEnabled(False)     
        self.frame_6.setEnabled(False)
        self.projectTab.setEnabled(False)
        #self.projectTab.setEnabled(False)

    def getPathToRoot(self,treeItem):
        # Traces the path to root of the manifest file
        path = [treeItem.text(0)]
        tmpItem = treeItem
        while tmpItem.parent():
            tmpItem = tmpItem.parent()
            path.insert(0, tmpItem.text(0))
        return path

    def addFolderToZip(self, zip_file, folder,strip_path):
        # Adds folder to zip file (used to handle Ghidra projects)
        for file in os.listdir(folder):
            full_path = os.path.join(folder, file)
            if os.path.isfile(full_path):
                zip_file.write(full_path,os.path.relpath(full_path,strip_path))
            elif os.path.isdir(full_path):
                self.addFolderToZip(zip_file, full_path,strip_path)

    def autoRemoveDirs(self):
        # Automatically remove directories that are not matching anything in current manifest
        # This means that local files reflect state before someone else deleted something
        mag = [self.currentProjectManifest[self.currentProject]]
        path_mag = [os.path.join(str(collare_home),self.currentProject)]
        while mag:
            current_folder = mag.pop()
            current_fs_path = path_mag.pop()
            for fs_item in os.listdir(current_fs_path):
                if not fs_item in current_folder.keys():# and not current_folder[fs_item]["__file__type__"]:
                    # Delete only folders as those are reflected in manifest file immediatelly 
                    shutil.rmtree(os.path.join(current_fs_path,fs_item))
                elif not current_folder[fs_item]["__file__type__"]:
                    # Add folders to magazine
                    mag.append(current_folder[fs_item])
                    path_mag.append(os.path.join(current_fs_path,fs_item))



    def processIn(self,tool,path):
        # Process the initial binary in selected tool
        data = {
            "project": self.currentProject,
            "path": path[:-1],
            "file_name": path[-1]
        }
        try:
            response = requests.post(f'{self.server}/getfile', json=data, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
        except:
            self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
            return
        if response.status_code != 200:
            self.showPopupBox("Error Donwloading File","Something went horribly wrong!",QMessageBox.Critical)
        response_data = response.json()
        destination = os.path.join(str(collare_home),*path) # Create folder for each file
        if not os.path.exists(destination):
            os.makedirs(destination)
        file_path = os.path.join(destination,path[-1])
        with open(file_path,"wb") as dest_file:
            dest_file.write(base64.b64decode(response_data['file']))
        if tool == "binja":
            Popen([f"binaryninja",file_path.replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True)
        elif tool == "hopper":
            Popen([f"Hopper" ,"-e",file_path.replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True)
        elif tool == "cutter":
            Popen([f"Cutter",file_path.replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True,cwd=destination.replace("\\","\\\\"))
        elif tool == "ida":
            Popen([f"ida64",file_path.replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True)
        elif tool == "ida32":
            Popen([f"ida",file_path.replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True)
        elif tool == "asp":
            self.start_task("Generating Android Studio Project")
            process = Popen([f"jadx","-d",file_path.replace("\\","\\\\")[:-4],"-e",file_path.replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True)
            output, err = process.communicate()
            with ZipFile(os.path.join(file_path+".asp"), 'w') as zipObj:
                self.addFolderToZip(zipObj,file_path[:-4],os.path.dirname(file_path))
            self.end_task()
            self.showPopupBox("Android Studio Project Created","Automatic project creation was successful!\nPush local databases.",QMessageBox.Information)
        elif tool == "jeb":
            if os.name == "nt":
                jeb = "jeb.bat"
            else:
                jeb = "jeb"
            Popen([jeb,file_path.replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True)
        elif tool == "ghidra":          
            self.start_task("Generating Ghidra Project ... ")
            
            if os.name == "nt":
                headless = "analyzeHeadless.bat"
            else:
                headless = "analyzeHeadless"
            process = Popen([headless, os.path.dirname(file_path.replace("\\","\\\\")),os.path.basename(file_path.replace("\\","\\\\")),'-import',file_path.replace("\\","\\\\")],stdout=PIPE, stderr=PIPE)
            output, err = process.communicate()
            self.end_task()
            if b"ERROR REPORT" not in output:
                # Success
                with open(os.path.join(file_path+".rep","project.prp"),"r") as project_prp:
                    project_prp_data = project_prp.read()
                with open(os.path.join(file_path+".rep","project.prp"),"w") as project_prp:
                    project_prp.write(re.sub(r'<STATE NAME=\"OWNER.*>',"", project_prp_data))
                with ZipFile(os.path.join(file_path+".ghdb"), 'w') as zipObj:
                    zipObj.write(file_path+".gpr",os.path.basename(file_path+".gpr"))
                    self.addFolderToZip(zipObj,file_path + ".rep",os.path.dirname(file_path))
                self.showPopupBox("Ghidra Project Created","Automatic project creation was successful!\nPush local databases.",QMessageBox.Information)
            else:
                gpr_path, ok = QInputDialog.getText(self, 'Import Ghidra Project', f"Automatic project creation failed!\nThe file has been downloaded to '{file_path}'.\nPlease create a Ghidra project with name that matches the name of the file ({path[-1]}) and enter full path to the '{path[-1]}.gpr' file:")
                if ok:
                    if os.path.exists(gpr_path):
                        # Change project owner:
                        with open(os.path.join(gpr_path.replace(".gpr",".rep"),"project.prp"),"r") as project_prp:
                            project_prp_data = project_prp.read()
                        with open(os.path.join(gpr_path.replace(".gpr",".rep"),"project.prp"),"w") as project_prp:
                            project_prp.write(re.sub(r'<STATE NAME=\"OWNER.*>',"", project_prp_data))
                        with ZipFile(os.path.join(destination,path[-1]+".ghdb"), 'w') as zipObj:
                            zipObj.write(gpr_path,os.path.basename(gpr_path))
                            self.addFolderToZip(zipObj,gpr_path.replace(".gpr",".rep"),os.path.dirname(gpr_path))
                    else:
                        self.showPopupBox("Ghidra Project","Specified file does not exist!",QMessageBox.Critical)


    def isCheckedOut(self,path):
        # Verify if the file is currently checkedout
        checkout, current_user = False, False
        if reduce(dict.get,path[:-1],self.currentProjectManifest)["__rev_dbs__"][path[-1]]["checked-out"] != None:
            checkout = True
            if reduce(dict.get,path[:-1],self.currentProjectManifest)["__rev_dbs__"][path[-1]]["checked-out"] == self.username:
                current_user = True
        return checkout,current_user

    def rightClickMenuHandle(self,event):
        # Get item which was clicked
        clickedItem = self.projectTreeView.itemAt(event)
        self.menu = QtWidgets.QMenu(self.projectTreeView)
        item = self.projectTreeView.itemAt(event)
        if item:
            self.menu.addSection("Project")
            refresh = self.menu.addAction(QIcon(os.path.join(current_running_file_dir,"icons","refresh.png")),"Refresh")
            if item.whatsThis(0) == "folder":
                # Right click on folder
                self.menu.addSection("Folder operations")
                create_folder = self.menu.addAction(QIcon(os.path.join(current_running_file_dir,"icons","new_folder.png")),"New Folder")  
                delete_folder = self.menu.addAction(QIcon(os.path.join(current_running_file_dir,"icons","delete.png")),"Delete Folder")
                rename_folder = self.menu.addAction(QIcon(os.path.join(current_running_file_dir,"icons","rename.png")),"Rename")
            elif item.whatsThis(0) == "binary":
                # Right click on original binary
                self.menu.addSection("Process in:")
                open_ida = self.menu.addAction(QIcon(os.path.join(current_running_file_dir,"icons","i64.png")),"IDA Pro (64-bit)")
                open_ida32 = self.menu.addAction(QIcon(os.path.join(current_running_file_dir,"icons","i64.png")),"IDA Pro (32-bit)")
                open_rizin = self.menu.addAction(QIcon(os.path.join(current_running_file_dir,"icons","rzdb.png")),"Cutter")
                open_binja = self.menu.addAction(QIcon(os.path.join(current_running_file_dir,"icons","bndb.png")),"Binary Ninja")
                open_hop = self.menu.addAction(QIcon(os.path.join(current_running_file_dir,"icons","hop.png")),"Hopper Disassembler")
                open_ghidra = self.menu.addAction(QIcon(os.path.join(current_running_file_dir,"icons","ghdb.png")),"Ghidra")
                open_jeb = self.menu.addAction(QIcon(os.path.join(current_running_file_dir,"icons","jdb2.png")),"JEB")
                open_asp = self.menu.addAction(QIcon(os.path.join(current_running_file_dir,"icons","asp.png")),"Android Studio Project (JADX decompiler)")
                self.menu.addSection("File operations")
                push_all = self.menu.addAction(QIcon(os.path.join(current_running_file_dir,"icons","upload.png")),"Push Local DBs")
                delete_file = self.menu.addAction(QIcon(os.path.join(current_running_file_dir,"icons","delete.png")),"Delete File")
                for node in range(0,clickedItem.childCount()):
                    disabled_tool = clickedItem.child(node).text(0)
                    if "i64" in disabled_tool:
                        open_ida.setEnabled(False)
                    if "idb" in disabled_tool:
                        open_ida32.setEnabled(False)
                    if "bndb" in disabled_tool:
                        open_binja.setEnabled(False)
                    if "hop" in disabled_tool:
                        open_hop.setEnabled(False)
                    if "rzdb" in disabled_tool:
                        open_rizin.setEnabled(False)
                    if "ghdb" in disabled_tool:
                        open_ghidra.setEnabled(False)
                    if "jdb2" in disabled_tool:
                        open_jeb.setEnabled(False)
                    if "asp" in disabled_tool:
                        open_asp.setEnabled(False)
                # Enable/Disable tools based on PATH
                if not self.which("ida64"):
                    open_ida.setEnabled(False)
                if not self.which("binaryninja"):
                    open_binja.setEnabled(False)
                if not self.which("Hopper"):
                    open_hop.setEnabled(False)
                if not self.which("Cutter"):
                    open_rizin.setEnabled(False)
                if not self.which("ghidraRun"):
                    open_ghidra.setEnabled(False)
                if not self.which("jeb"):
                    open_jeb.setEnabled(False)
                if not self.which("android-studio") or (".apk" not in clickedItem.text(0).lower() and ".jar" not in clickedItem.text(0).lower()):
                    open_asp.setEnabled(False)
            else:
                # Right click on one of the DB files
                self.menu.addSection("File operations")
                open_file = self.menu.addAction(QIcon(os.path.join(current_running_file_dir,"icons","open.png")),"Open File")
                checkout = self.menu.addAction(QIcon(os.path.join(current_running_file_dir,"icons","download.png")),"Check-out")
                checkin = self.menu.addAction(QIcon(os.path.join(current_running_file_dir,"icons","upload.png")),"Check-in")
                undo_checkout = self.menu.addAction(QIcon(os.path.join(current_running_file_dir,"icons","undo.png")),"Undo Check-out")
                delete_file = self.menu.addAction(QIcon(os.path.join(current_running_file_dir,"icons","delete.png")),"Delete File")
                
                checked,current_user =  self.isCheckedOut(self.getPathToRoot(clickedItem))
                # submenu for version specific checkout and open
                manifestPath = self.getPathToRoot(clickedItem)[:-1] + ["__rev_dbs__"] + [self.getPathToRoot(clickedItem)[-1]]
                versions = reduce(dict.get,manifestPath,self.currentProjectManifest)["versions"]
                self.menu.addSection("Previous File Versions")
                openSubmenu = QtWidgets.QMenu(self.menu)
                openSubmenu.setTitle("Open Previous Version")
                openSubmenu.setIcon(QIcon(os.path.join(current_running_file_dir,"icons","open.png")))
                checkoutSubmenu = QtWidgets.QMenu(self.menu)
                checkoutSubmenu.setTitle("Check-out Previous Version")
                checkoutSubmenu.setIcon(QIcon(os.path.join(current_running_file_dir,"icons","download.png")))
                counter = 0
                for version in versions:
                    checkoutAction = checkoutSubmenu.addAction(f"#{counter}: {version}")
                    checkoutAction.setWhatsThis("checkout_version")
                    openAction = openSubmenu.addAction(f"#{counter}: {version}")
                    openAction.setWhatsThis("open_version")
                    counter += 1
                
                if checked:
                    checkout.setEnabled(False)
                    checkoutSubmenu.setEnabled(False)
                    openSubmenu.setEnabled(False)
                    if not current_user:
                        checkin.setEnabled(False)
                        undo_checkout.setEnabled(False)
                        delete_file.setEnabled(False)
                else:
                    checkin.setEnabled(False)
                    undo_checkout.setEnabled(False)
                if clickedItem.isDisabled():
                    open_file.setEnabled(False)
                    checkout.setEnabled(False)
                    checkoutSubmenu.setEnabled(False)
                    openSubmenu.setEnabled(False)
                    checkin.setEnabled(False)
                    undo_checkout.setEnabled(False)
                self.menu.addMenu(openSubmenu)
                self.menu.addMenu(checkoutSubmenu)
        
        performed_action = self.menu.exec_(self.projectTreeView.mapToGlobal(event))
        # Handle actions below
        if performed_action:
            if performed_action.text() == "New Folder":
                self.mkdir(self.getPathToRoot(clickedItem))
            elif performed_action.text() == "Delete Folder":
                self.deleteDir(self.getPathToRoot(clickedItem))
            elif performed_action.text() == "Delete File":
                self.deleteFile(self.getPathToRoot(clickedItem))
            elif performed_action.text() == "Binary Ninja":
                self.processIn("binja",self.getPathToRoot(clickedItem))
            elif performed_action.text() == "Hopper Disassembler":
                self.processIn("hopper",self.getPathToRoot(clickedItem))
            elif performed_action.text() == "Cutter":
                self.processIn("cutter",self.getPathToRoot(clickedItem))
            elif performed_action.text() == "IDA Pro (64-bit)":
                self.processIn("ida",self.getPathToRoot(clickedItem))
            elif performed_action.text() == "IDA Pro (32-bit)":
                self.processIn("ida32",self.getPathToRoot(clickedItem))
            elif performed_action.text() == "Ghidra":
                self.processIn("ghidra",self.getPathToRoot(clickedItem))
            elif performed_action.text() == "JEB":
                self.processIn("jeb",self.getPathToRoot(clickedItem))
            elif performed_action.text() == "Android Studio Project (JADX decompiler)":
                self.processIn("asp",self.getPathToRoot(clickedItem))
            elif performed_action.text() == "Push Local DBs":
                self.pushLocal(self.getPathToRoot(clickedItem))
            elif performed_action.text() == "Check-out":
                manifestPath = self.getPathToRoot(clickedItem)[:-1] + ["__rev_dbs__"] + [self.getPathToRoot(clickedItem)[-1]]
                version = reduce(dict.get,manifestPath,self.currentProjectManifest)["latest"]
                self.checkoutDBFile(self.getPathToRoot(clickedItem),version)
            elif performed_action.text() == "Check-in":
                self.checkinDBFile(self.getPathToRoot(clickedItem))
            elif performed_action.text() == "Undo Check-out":
                self.undoCheckoutDBFile(self.getPathToRoot(clickedItem))
            elif performed_action.text() == "Open File":
                manifestPath = self.getPathToRoot(clickedItem)[:-1] + ["__rev_dbs__"] + [self.getPathToRoot(clickedItem)[-1]]
                version = reduce(dict.get,manifestPath,self.currentProjectManifest)["latest"]
                self.openDBFile(self.getPathToRoot(clickedItem),version)
            elif performed_action.text() == "Refresh":
                self.refreshProject()
            elif performed_action.text() == "Rename":
                self.renameFolder(self.getPathToRoot(clickedItem),clickedItem)
            elif performed_action.whatsThis() == "checkout_version":
                self.checkoutDBFile(self.getPathToRoot(clickedItem),self.parseVersionFromText(performed_action.text()))
            elif performed_action.whatsThis() == "open_version":
                self.openDBFile(self.getPathToRoot(clickedItem),self.parseVersionFromText(performed_action.text()))


    def parseVersionFromText(self,text):
        return int(text[1:text.find(":")])


    def renameFolder(self,path,item):
        dirname, ok = QInputDialog.getText(self, 'Rename Folder', f"Enter new name for the folder '{item.text(0)}':")
        if ok:
            if not re.match(r'^\w+$',dirname):
                self.showPopupBox("Invalid Folder Name","Folder name can contain only letters, numbers and '_' (underscores).",QMessageBox.Critical)
                return
            data = {
                "project":self.currentProject,
                "path": path,
                "dirname": dirname
            }
            try:
                response = requests.post(f'{self.server}/rename', json=data, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
            except:
                self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
                return
            if response.status_code != 200:
                self.showPopupBox("Error Renaming Folder","Something went horribly wrong!",QMessageBox.Critical)
            elif response.text == "FOLDER_ALREADY_EXISTS":
                self.showPopupBox("Error Renaming Folder","Folder with this name already exists!",QMessageBox.Critical)
            self.refreshProject()
        
        
    
    def pushLocal(self,path):
        # Walk through the folder in 'path' and push all known (supported_db_names) files to the server
        # Files that already exists are uploaded but silently ignored by the server
        containing_folder = os.path.join(str(collare_home),*path) # Sperate folder for files
        filename = path[-1]
        filename_no_extension = os.path.splitext(filename)[0]
        for db_file in os.listdir(containing_folder):
            filename_extension = os.path.splitext(db_file)[1][1:]
            if db_file.startswith(filename_no_extension) and filename_extension in supported_db_names:
                with open(os.path.join(containing_folder,db_file), "rb") as data_file:
                    encoded_file = base64.b64encode(data_file.read()).decode("utf-8") 
                if filename_extension == "hop" or filename_extension == "bndb":
                    # Hopper and binary ninja do strip the extension by default when saving projects so check if we need to put it back
                    if os.path.splitext(db_file)[0] != filename:
                        db_file = filename + f".{filename_extension}"
                values = {'path': path,"project":self.currentProject,"file":encoded_file,"file_name":db_file}
                try:
                    self.start_task("Pushing local DB file ... ")
                    response = requests.post(f'{self.server}/pushdbfile', json=values, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
                    self.end_task()
                except:
                    self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
                    self.end_task()
                    return
                if response.status_code != 200:
                    self.showPopupBox("Error Uploading File","Something went horribly wrong!",QMessageBox.Critical)
        self.refreshProject()


    def existingProjectSelectHandler(self):
        # Select existing project from the server and open it
        try:
            selectedProject = self.existingProjectsList.selectedItems()[0].text()
        except:
            self.showPopupBox("Error","No project selected!",QMessageBox.Critical)
            return
        try:
            response = requests.get(f'{self.server}/openproject', params={"project":selectedProject}, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
        except:
            self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
            return
        if response.status_code != 200:
            self.showPopupBox("Error Opening Project","Something went horribly wrong!",QMessageBox.Critical)
        else:
            if response.text == "PROJECT_DOES_NOT_EXIST":
                self.showPopupBox("Error Creating Project",f"Project with name '{selectedProject}' does not exist!",QMessageBox.Critical)
                return
            self.currentProjectManifest = response.json()
            self.currentProject = selectedProject
            self.frame_6.setEnabled(True)
            self.projectTab.setEnabled(True)
            self.mainTabWidget.setCurrentIndex(1)
            self.projectTreeView.setProjectData(self.server,self.currentProject,self.username,self.password,self.cert,self)
            self.currentProjectLocalPath = Path(collare_home / self.currentProject)
            self.currentProjectLocalPath.mkdir(exist_ok=True)
            self.populateCurrentProjectUserListing()
            self.refreshProject()
        

    def deleteExistingProjectHandler(self):
        # Delete remote project
        try:
            selectedProject = self.existingProjectsList.selectedItems()[0].text()
        except:
            self.showPopupBox("Error","No project selected!",QMessageBox.Critical)
            return
        questionBox = QMessageBox()
        answer = questionBox.question(self,"Deleting project", f"Are you sure that you want to delete '{selectedProject}' project?", questionBox.Yes | questionBox.No)
        if answer == questionBox.Yes:
            try:
                response = requests.get(f'{self.server}/deleteproject', params={"project":selectedProject}, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
            except:
                self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
                return
            if response.status_code != 200:
                self.showPopupBox("Error Deleting Project","Something went horribly wrong!",QMessageBox.Critical)
            else:
                self.showPopupBox("Success",f"Project '{selectedProject}' was deleted!",QMessageBox.Information)
                shutil.rmtree(os.path.join(str(collare_home),selectedProject))
                self.populateExistingProjects()

    def createNewProjectClickHandler(self):
        # Create new project
        projectName = self.newProjectName.text()
        if not re.match(r'^\w+$',projectName):
            self.showPopupBox("Invalid Project Name","Project name can contain only letters, numbers and '_' (underscores).",QMessageBox.Critical)
            return
        selectedItems = self.newProjectUsersList.selectedItems()
        user_list = []
        for item in selectedItems:
            user_list.append(item.text())
        # Auto-add self
        if self.username not in user_list:
            user_list.append(self.username)
        data={"project":projectName,"users":user_list}
        try:
            response = requests.post(f'{self.server}/createproject', json=data, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
        except:
            self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
            return
        if response.status_code != 200:
            self.showPopupBox("Error Creating Project","Something went horribly wrong!",QMessageBox.Critical)
        else:
            if response.text == "ALREADY_EXISTS":
                self.showPopupBox("Error Creating Project",f"Project with name '{projectName}' already exists!",QMessageBox.Critical)
                return
            self.showPopupBox("Success",f"New project '{projectName}' was created!",QMessageBox.Information)
            self.populateExistingProjects()
            self.currentProject = projectName
            self.frame_6.setEnabled(True)
            self.currentProjectManifest = response.json()
            self.projectTab.setEnabled(True)
            self.mainTabWidget.setCurrentIndex(1)
            self.projectTreeView.setProjectData(self.server,self.currentProject,self.username,self.password,self.cert,self)
            self.currentProjectLocalPath = Path(collare_home / self.currentProject)
            self.currentProjectLocalPath.mkdir(exist_ok=True)
            self.populateCurrentProjectUserListing()
            self.refreshProject()

    def mkdir(self,path):
        # Create directory
        dirname, ok = QInputDialog.getText(self, 'New Folder', 'Enter name for the folder:')
        if ok:
            if not re.match(r'^\w+$',dirname):
                self.showPopupBox("Invalid Folder Name","Folder name can contain only letters, numbers and '_' (underscores).",QMessageBox.Critical)
                return
            data = {
                "project":self.currentProject,
                "path": path,
                "dirname": dirname
            }
            try:
                response = requests.post(f'{self.server}/mkdir', json=data, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
            except:
                self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
                return
            if response.status_code != 200:
                self.showPopupBox("Error Creating Folder","Something went horribly wrong!",QMessageBox.Critical)
            elif response.text == "FOLDER_ALREADY_EXISTS":
                self.showPopupBox("Error Creating Folder","Folder with this name already exists!",QMessageBox.Critical)
            self.refreshProject()
    
    def deleteDir(self,path):
        # Delete directory
        if len(path) == 1:
            self.showPopupBox("Error Deleting Folder","Cannot delete project root!",QMessageBox.Critical)
            return
        questionBox = QMessageBox()
        answer = questionBox.question(self,"Deleting Folder", f"Are you sure that you want to delete '{path[-1]}' folder?", questionBox.Yes | questionBox.No)
        if answer == questionBox.Yes:
            data = {
                "project":self.currentProject,
                "path": path[:-1],
                "dirname": path[-1]
            }
            try:
                response = requests.post(f'{self.server}/deletedir', json=data, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
            except:
                self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
                return
            if response.status_code != 200:
                self.showPopupBox("Error Deleting Folder","Something went horribly wrong!",QMessageBox.Critical)
            self.refreshProject()
            if response.text == "DONE":
                try:
                    shutil.rmtree(os.path.join(str(collare_home),*path))
                except FileNotFoundError:
                    pass
            elif response.text == "CHECKEDOUT_FILE":
                self.showPopupBox("Error Deleting Folder","One of the files in this folder is currently checked-out!",QMessageBox.Critical)

    def undoCheckoutDBFile(self,path):
        # Removes checkout flag from the file
        filename = f"{path[-2]}.{path[-1]}"
        data = {
            "project": self.currentProject,
            "path": path[:-1],
            "file_name": filename
        }
        try:
            response = requests.post(f'{self.server}/undocheckout', json=data, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
        except:
            self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
            return
        if response.status_code != 200:
            self.showPopupBox("Error During Undo Check-Out","Something went horribly wrong!",QMessageBox.Critical)
            return
        elif response.text == "FILE_NOT_CHECKEDOUT":
            self.showPopupBox("Error During Undo Check-Out","File not checked out!",QMessageBox.Critical)
            return
        self.refreshProject()


    def openDoubleClickWrapper(self):
        # Double click on item, open only if parent is binary - i.e. we are clicking on db file
        selected_item = self.projectTreeView.selectedItems()
        if selected_item:
            if selected_item[0].parent().whatsThis(0) == "binary":
                manifestPath = self.getPathToRoot(selected_item[0])[:-1] + ["__rev_dbs__"] + [self.getPathToRoot(selected_item[0])[-1]]
                version = reduce(dict.get,manifestPath,self.currentProjectManifest)["latest"]
                self.openDBFile(self.getPathToRoot(selected_item[0]),version)

    def openDBFile(self,path,version):
        # Opens db file based on the relevant tool
        filename = f"{path[-2]}.{path[-1]}"
        data = {
            "project": self.currentProject,
            "path": path[:-1],
            "file_name": filename,
            "version": version
        }
        try:
            self.start_task("Opening DB file ... ")
            response = requests.post(f'{self.server}/opendbfile', json=data, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
            self.end_task()
        except:
            self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
            self.end_task()
            return
        if response.status_code != 200:
            self.showPopupBox("Error Opening File","Something went horribly wrong!",QMessageBox.Critical)
            return
        elif response.text != "FILE_ALREADY_CHECKEDOUT":
            self.showPopupBox("Opening File without Check-Out","Please consider the file to be open in 'read-only' mode. Re-opening the file or performing checkout will overwrite any changes made. Make sure to do 'Check-out' if you want to do some changes!",QMessageBox.Information)
            response_data = response.json()
            destination = os.path.join(str(collare_home),*path[:-1]) # Create folder for each file
            if not os.path.exists(destination):
                os.makedirs(destination)
            file_path = os.path.join(destination,filename)
            with open(file_path,"wb") as dest_file:
                dest_file.write(base64.b64decode(response_data['file']))
            with open(os.path.join(destination,"changes.json"),"wb") as changes_file:
                changes_file.write(base64.b64decode(response_data['changes']))
            if path[-1] == "ghdb":
                destination = os.path.join(str(collare_home),*path[:-1])
                file_path = os.path.join(destination,filename)
                try:
                    shutil.rmtree(file_path[:-4] + "rep")
                except:
                    pass
                shutil.unpack_archive(file_path, destination, "zip")  
            if path[-1] == "asp":
                destination = os.path.join(str(collare_home),*path[:-1])
                file_path = os.path.join(destination,filename)
                try:
                    shutil.rmtree(file_path[:-8])
                except:
                    pass
                shutil.unpack_archive(file_path, destination, "zip") 
        destination = os.path.join(str(collare_home),*path[:-1])
        file_path = os.path.join(destination,filename)
        if path[-1] == "bndb":
            #Popen(f'binaryninja "{file_path}"'],stdin=None, stdout=None, stderr=None, close_fds=True)
            Popen(['binaryninja',file_path.replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True)
        elif path[-1] == "hop":
            Popen(['Hopper', '-d',file_path.replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True)
        elif path[-1] == "rzdb":
            # download binary as well
            data = {
            "project": self.currentProject,
            "path": path[:-2],
            "file_name": path[-2]
            }
            try:
                self.start_task("Downloading binary file ... ")
                bin_file_response = requests.post(f'{self.server}/getfile', json=data, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
                self.end_task()
            except:
                self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
                self.end_task()
                return
            if bin_file_response.status_code != 200:
                self.showPopupBox("Error Donwloading File","Something went horribly wrong!",QMessageBox.Critical)
            bin_file_response_data = bin_file_response.json()
            bin_destination = os.path.join(str(collare_home),*path[:-1])
            bin_file_path = os.path.join(bin_destination,path[-2])
            with open(bin_file_path,"wb") as dest_file:
                dest_file.write(base64.b64decode(bin_file_response_data['file']))
            Popen([f'Cutter',"-p", file_path.replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True,cwd=destination.replace("\\","\\\\"))
        elif path[-1] == "asp":
            Popen(['android-studio',os.path.join(destination,filename.replace(".apk.asp","").replace(".jar.asp","")).replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True)
        elif path[-1] == "i64":
            Popen([f'ida64',file_path.replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True)
        elif path[-1] == "idb":
            Popen([f'ida',file_path.replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True)
        elif path[-1] == "jdb2":

            # has to be jeb.bat for windows
            if os.name == "nt":
                jeb = "jeb.bat"
            else:
                jeb = "jeb"
            Popen([jeb,file_path.replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True)
        elif path[-1] == "ghdb":
            if os.name == "nt":
                ghidraRun = "ghidraRun.bat"
            else:
                ghidraRun = "ghidraRun"
            Popen([ghidraRun,os.path.join(destination,filename.replace("ghdb","gpr")).replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True)
        self.refreshProject()
    
    def checkoutDBFile(self,path,version):
        # Checks-out the DB file for editing
        filename = f"{path[-2]}.{path[-1]}"
        data = {
            "project": self.currentProject,
            "path": path[:-1],
            "file_name": filename,
            "version": version
        }
        try:
            self.start_task("Checking out DB file ... ")
            response = requests.post(f'{self.server}/checkout', json=data, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
            self.end_task()
        except:
            self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
            self.end_task()
            return
        if response.status_code != 200:
            self.showPopupBox("Error During Check-Out","Something went horribly wrong!",QMessageBox.Critical)
            return
        elif response.text == "FILE_ALREADY_CHECKEDOUT":
            self.showPopupBox("Error During Check-Out","File already checked out!",QMessageBox.Critical)
            self.refreshProject()
            return
        response_data = response.json()
        destination = os.path.join(str(collare_home),*path[:-1]) # Create folder for each file
        if not os.path.exists(destination):
            os.makedirs(destination)
        file_path = os.path.join(destination,filename)
        with open(file_path,"wb") as dest_file:
            dest_file.write(base64.b64decode(response_data['file']))
        with open(os.path.join(destination,"changes.json"),"wb") as changes_file:
            changes_file.write(base64.b64decode(response_data['changes']))
        if path[-1] == "bndb":
            Popen(["binaryninja", file_path.replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True)
        elif path[-1] == "hop":
            Popen(["Hopper", "-d",file_path.replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True)
        elif path[-1] == "rzdb":
            # download binary as well
            data = {
            "project": self.currentProject,
            "path": path[:-2],
            "file_name": path[-2]
            }
            try:
                self.start_task("Downloading binary file ... ")
                bin_file_response = requests.post(f'{self.server}/getfile', json=data, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
                self.end_task()
            except:
                self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
                self.end_task()
                return
            if bin_file_response.status_code != 200:
                self.showPopupBox("Error Donwloading File","Something went horribly wrong!",QMessageBox.Critical)
            bin_file_response_data = bin_file_response.json()
            bin_destination = os.path.join(str(collare_home),*path[:-1])
            bin_file_path = os.path.join(bin_destination,path[-2])
            with open(bin_file_path,"wb") as dest_file:
                dest_file.write(base64.b64decode(bin_file_response_data['file']))
            Popen(["Cutter","-p",file_path.replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True,cwd=destination.replace("\\","\\\\"))
        elif path[-1] == "asp":
            try:
                shutil.rmtree(file_path[:-8])
            except:
                pass
            shutil.unpack_archive(file_path, destination, "zip") 
            Popen(['android-studio',os.path.join(destination,filename.replace(".apk.asp","").replace(".jar.asp","")).replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True)
        elif path[-1] == "i64":
            Popen(["ida64",file_path.replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True)
        elif path[-1] == "idb":
            Popen(["ida",file_path.replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True)
        elif path[-1] == "jdb2":
            if os.name == "nt":
                jeb = "jeb.bat"
            else:
                jeb = "jeb"
            Popen([jeb,file_path.replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True)
        elif path[-1] == "ghdb":
            if os.name == "nt":
                ghidraRun = "ghidraRun.bat"
            else:
                ghidraRun = "ghidraRun"
            try:
                shutil.rmtree(file_path[:-4] + "rep")
            except:
                pass
            shutil.unpack_archive(file_path, destination, "zip")  
            Popen([ghidraRun,os.path.join(destination,filename.replace('ghdb','gpr')).replace("\\","\\\\")],stdin=None, stdout=None, stderr=None, close_fds=True)
        self.refreshProject()

    def checkinDBFile(self,path):
        # Performs check-in of the checked-out file, this is the only way to update DB files on the server
        checkout = False
        questionBox = QMessageBox()
        answer = questionBox.question(self,"Check-in", f"Would you like to keep the file checked-out?", questionBox.Yes | questionBox.No)
        if answer == questionBox.Yes:
            checkout = True
        comment, ok = QInputDialog.getText(self, 'Check-in Comment', f"Enter comment for the check-in:")
        if ok:
            if comment == "":
                comment = "NoComment"
            containing_folder = os.path.join(str(collare_home),*path[:-1]) # Seperate folder for files
            filename = f"{path[-2]}.{path[-1]}"
            if path[-1] == "ghdb":
                gpr_path = os.path.join(containing_folder,path[-2] + ".gpr")
                with ZipFile(os.path.join(containing_folder,filename), 'w') as zipObj:
                    zipObj.write(gpr_path,os.path.basename(gpr_path))
                    self.addFolderToZip(zipObj,gpr_path.replace("gpr","rep"),os.path.dirname(gpr_path))
            if path[-1] == "asp":
                project_folder = os.path.join(containing_folder,path[-2][:-4])
                with ZipFile(os.path.join(containing_folder,filename), 'w') as zipObj:
                    self.addFolderToZip(zipObj,project_folder,os.path.dirname(project_folder))
            with open(os.path.join(containing_folder,"changes.json"), "rb") as changes_file:
                changes_content = base64.b64encode(changes_file.read()).decode("utf-8")
            with open(os.path.join(containing_folder,filename), "rb") as data_file:
                encoded_file = base64.b64encode(data_file.read()).decode("utf-8") 
            values = {'path': path[:-1],"project":self.currentProject,"file":encoded_file,"file_name":filename,"checkout":checkout,"comment":comment,"changes":changes_content}
            try:
                self.start_task("Checking in the DB file ... ")
                response = requests.post(f'{self.server}/checkin', json=values, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
                self.end_task()
            except:
                self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
                self.end_task()
                return
            if response.status_code != 200:
                self.showPopupBox("Error During Check-In","Something went horribly wrong!",QMessageBox.Critical)
            elif response.text == "FILE_NOT_CHECKEDOUT":
                self.showPopupBox("Error During Check-In","File is not checked-out to you!",QMessageBox.Critical)
            self.refreshProject()

    def deleteFile(self,path):
        # Removes any file from the server (and local) storage
        questionBox = QMessageBox()
        answer = questionBox.question(self,"Deleting File", f"Are you sure that you want to delete '{path[-1]}' file?", questionBox.Yes | questionBox.No)
        if answer == questionBox.Yes:
            data = {
                "project":self.currentProject,
                "path": path[:-1],
                "filename": path[-1]
            }
            try:
                response = requests.post(f'{self.server}/deletefile', json=data, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
            except:
                self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
                return
            if response.status_code != 200:
                self.showPopupBox("Error Deleting File","Something went horribly wrong!",QMessageBox.Critical)
            self.refreshProject()
            if response.text == "DONE":
                if path[-1] in supported_db_names:
                    remove_path = os.path.join(str(collare_home),*path[:-1],path[-2]) + f".{path[-1]}"
                    if os.path.exists(remove_path):
                        os.remove(remove_path)
                elif os.path.exists(os.path.join(str(collare_home),*path)):
                    shutil.rmtree(os.path.join(str(collare_home),*path))
            elif response.text == "CHECKEDOUT_FILE":
                self.showPopupBox("Error Deleting Folder","This file is currently checked-out!",QMessageBox.Critical)
                

    def refreshProject(self):
        # Refershes the view of the project
        response = requests.get(f'{self.server}/openproject', params={"project":self.currentProject}, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
        if response.status_code != 200:
            self.showPopupBox("Error Refershing Project Data","Something went horribly wrong!",QMessageBox.Critical)
        else:
            if response.text == "PROJECT_DOES_NOT_EXIST":
                self.showPopupBox("Error Refershing Project Data",f"Project with name '{self.currentProject}' does not exist!",QMessageBox.Critical)
                return
            self.currentProjectManifest = response.json()
        self.refreshProjectTree()
        self.autoRemoveDirs()
        self.projectTreeView.expandAll()

    def changePasswordClickHandler(self):
        req_data = {"password":self.newPasswrdText1.text()}
        if self.newPasswrdText1.text() != self.newPasswrdText2.text():
            self.showPopupBox("Password Change Error","Passwords don't match!",QMessageBox.Critical)
            return
        try:
            response = requests.post(f'{self.server}/changepwd', data=req_data, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
        except:
            self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
            return
        if response.status_code != 200:
            self.showPopupBox("Error Changing Password","Something went horribly wrong!",QMessageBox.Critical)
        else:
            self.showPopupBox("Password Changed",f"Password for user '{self.username}' was changed! Please disconnect and connect again with the new password!",QMessageBox.Information)


    def addNewGlobalUserClickHandler(self):
        req_data = {"username":self.newUserNameText.text(),"password":self.newUserPwdText.text()}
        if self.username != "admin":
            self.showPopupBox("Cannot create user","You need to be 'admin' to do that!",QMessageBox.Critical)
            return
        if not req_data["username"] or not req_data["password"]:
            self.showPopupBox("Cannot create user","Make sure to fill in all fields!",QMessageBox.Critical)
            return
        try:
            response = requests.post(f'{self.server}/adduser', data=req_data, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
        except:
            self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
            return
        if response.status_code != 200:
            self.showPopupBox("Error Creating User","Something went horribly wrong!",QMessageBox.Critical)
        else:
            self.showPopupBox("New User Added",f"New user with name {self.newUserNameText.text()} was added!",QMessageBox.Information)
            self.populateAllUserListings()

    def populateAllUserListings(self):
        try:
            response = requests.get(f'{self.server}/getusers', auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
        except:
            self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
            return
        if response.status_code != 200:
            self.showPopupBox("Error Getting Users","Something went horribly wrong!",QMessageBox.Critical)
            return
        user_list = response.json()
        self.newProjectUsersList.clear()
        self.newProjectUsersList.addItems(user_list["users"])
        self.projectAllUsersView.clear()
        self.projectAllUsersView.addItems(user_list["users"])
        self.deleteGlobalUsersList.clear()
        self.deleteGlobalUsersList.addItems(user_list["users"])
    
    def populateCurrentProjectUserListing(self):
        try:
            response = requests.get(f'{self.server}/getprojectusers', params={"project":self.currentProject}, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
        except:
            self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
            return
        if response.status_code != 200:
            self.showPopupBox("Error Getting Users","Something went horribly wrong!",QMessageBox.Critical)
            return
        user_list = response.json()
        self.projectCurrentUsersView.clear()
        self.projectCurrentUsersView.addItems(user_list["users"])

    def populateExistingProjects(self):
        try:
            response = requests.get(f'{self.server}/getprojectlist', auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
        except:
            self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
            return
        if response.status_code != 200:
            self.showPopupBox("Error Getting Projects","Something went horribly wrong!",QMessageBox.Critical)
            return
        project_list = response.json()
        self.existingProjectsList.clear()
        self.existingProjectsList.addItems(project_list["projects"])
        for item in os.listdir(str(collare_home)):
            full_path = os.path.join(str(collare_home),item)
            if os.path.isdir(full_path):
                if item not in project_list["projects"]:
                    questionBox = QMessageBox()
                    answer = questionBox.question(self,"Possibly Deleted Project Detected", f"It appears that the project '{item}' has been removed by other users. Would you like to remove it from local storage?", questionBox.Yes | questionBox.No)
                    if answer == questionBox.Yes:
                        shutil.rmtree(full_path)

    def addProjectUserClickHandler(self):
        selectedItems = self.projectAllUsersView.selectedItems()
        user_list = []
        for item in selectedItems:
            user_list.append(item.text())
        if user_list:
            data = {"project":self.currentProject,"users":user_list}
            try:
                response = requests.post(f'{self.server}/addprojectusers', json=data, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
            except:
                self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
                return
            if response.status_code != 200:
                self.showPopupBox("Error Adding Project Users","Something went horribly wrong!",QMessageBox.Critical)
            self.populateCurrentProjectUserListing()

    def deleteProjectUserClickHandler(self):
        selectedItems = self.projectCurrentUsersView.selectedItems()
        user_list = []
        for item in selectedItems:
            user_list.append(item.text())
        if user_list:
            data = {"project":self.currentProject,"users":user_list}
            try:
                response = requests.post(f'{self.server}/deleteprojectuser', json=data, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
            except:
                self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
                return
            if response.status_code != 200:
                self.showPopupBox("Error Deleting Project Users","Something went horribly wrong!",QMessageBox.Critical)
            self.populateCurrentProjectUserListing()

    def deleteGlobalUsersHandler(self):
        if self.username != "admin":
            self.showPopupBox("Error","Only user 'admin' can do that!",QMessageBox.Critical)
            return
        selectedItems = self.deleteGlobalUsersList.selectedItems()
        user_list = []
        for item in selectedItems:
            user_list.append(item.text())
        if user_list:
            data = {"users":user_list}
            try:
                response = requests.post(f'{self.server}/deluser', json=data, auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
            except:
                self.showPopupBox("Connection Error","Connection to the server is not working!",QMessageBox.Critical)
                return
            if response.status_code != 200:
                self.showPopupBox("Error Deleting Global Users","Something went horribly wrong!",QMessageBox.Critical)
            self.populateAllUserListings()
            self.populateCurrentProjectUserListing()

    def doesToolExist(self,tool):
        if tool == "i64" and self.which("ida64"):
            return True
        if tool == "idb" and self.which("ida"):
            return True
        if tool == "bndb" and self.which("binaryninja"):
            return True
        if tool == "hop" and self.which("Hopper"):
            return True
        if tool == "rzdb" and self.which("Cutter"):
            return True
        if tool == "ghdb" and self.which("ghidraRun"):
            return True
        if tool == "jdb2" and self.which("jeb"):
            return True
        if tool == "asp" and self.which("android-studio"):
            return True
        return False

    def refreshProjectTree(self):
        self.projectTreeView.clear()
        def fill_item(item,value):
            if type(value) is dict:
                for key, val in sorted(value.items()):
                    child = QTreeWidgetItem()
                    if key == "__file__type__" or key == "__locked__" or  key == "__rev_dbs__":
                        continue
                    if type(val) is dict:
                        if val["__file__type__"] == True:
                            if val["__locked__"]:
                                node_name = f"{key}"
                                #child.setText(1, (f"(checked-out by '{val['__locked__']}')"))
                            else:
                                node_name = key
                            icon = QIcon(os.path.join(current_running_file_dir,"icons","binary.png"))
                            child.setIcon(0,icon)
                            child.setWhatsThis(0,"binary")
                            for rev_db in val["__rev_dbs__"]:
                                rev_db_node = QTreeWidgetItem()
                                rev_db_node.setText(0,rev_db)
                                if val["__rev_dbs__"][rev_db]['checked-out']:
                                    rev_db_node.setText(1, (f"Checked-out by '{val['__rev_dbs__'][rev_db]['checked-out']}'"))
                                if not self.doesToolExist(rev_db):
                                    rev_db_node.setDisabled(True)
                                rev_db_node.setIcon(0,QtGui.QIcon(os.path.join(current_running_file_dir,"icons",f"{rev_db}.png")))
                                rev_db_node.setWhatsThis(0,"db")
                                child.addChild(rev_db_node)
                        elif val["__file__type__"] == False:
                            node_name = key
                            icon = QIcon(os.path.join(current_running_file_dir,"icons","folder.png"))
                            child.setIcon(0,icon)
                            child.setWhatsThis(0,"folder")
                            item.setExpanded(True)
                        else:
                            node_name = key
                        child.setText(0, (node_name))
                        
                        item.addChild(child)
                        fill_item(child, val)
            else:
                child = QTreeWidgetItem()
                child.setText(0, (value))
                item.addChild(child)
        fill_item(self.projectTreeView.invisibleRootItem(),self.currentProjectManifest)
        

    def connectClickHandler(self):
        if self.connectButton.text() == "Connect":
            self.server = self.serverText.text()
            if self.server[-1] == "/":
                self.server = self.server[:-1]
            self.username = self.usernameText.text()
            self.password = self.passwordText.text()
            self.cert = self.serverCertPathText.text()
            if not self.server or not self.username or not self.password or not self.cert:
                self.showPopupBox("Cannot Initiate Connection","Please make sure that all fields are filled!",QMessageBox.Critical)
                return
            try:
                response = requests.get(f'{self.server}/ping', auth=(self.username, self.password), verify=self.cert, timeout=(3,40))
            except requests.exceptions.SSLError:
                self.showPopupBox("Cannot Initiate Connection","Certificate validation failure. Make sure that the hostname in the \"Server\" field matches the one in the certificate!",QMessageBox.Critical)
                return
            except requests.exceptions.ConnectionError:
                self.showPopupBox("Cannot Initiate Connection","Cannot reach the server!",QMessageBox.Critical)
                return
            except:
                self.showPopupBox("Cannot Initiate Connection","Connection not successful! Check provided data and try again!",QMessageBox.Critical)
                return
            if response.text == "SUCCESS":
                self.onSuccessConnect()
                self.storeConnectionDetails(self.server,self.username,self.cert)
            else:
                self.showPopupBox("Cannot Initiate Connection","Login failed!",QMessageBox.Critical)
                return
        else:
            self.onDisconnect()
        
        
# SAVE THIS
    def setupUi(self, Dialog):
        Dialog.setObjectName("Dialog")
        Dialog.resize(1021, 747)
        Dialog.setMinimumSize(Dialog.size())

        frame = QFrame()
        Dialog.setCentralWidget(frame)
        layout = QHBoxLayout()
        frame.setLayout(layout)
        
        self.mainTabWidget = QtWidgets.QTabWidget(Dialog)
        self.mainTabWidget.setEnabled(True)
        self.mainTabWidget.setGeometry(QtCore.QRect(20, 10, 981, 721))
        self.mainTabWidget.setObjectName("mainTabWidget")

        self.progress_label = QtWidgets.QLabel(self.mainTabWidget)
        self.progress_label.setGeometry(QtCore.QRect(300, 7, 211, 17))
        self.progress_label.setObjectName("label")
        
        layout.addWidget(self.mainTabWidget)

        self.connectionTab = QtWidgets.QWidget()
        self.connectionTab.setObjectName("connectionTab")
        self.serverText = QtWidgets.QLineEdit(self.connectionTab)
        self.serverText.setGeometry(QtCore.QRect(250, 50, 531, 25))
        self.serverText.setObjectName("serverText")
        self.label = QtWidgets.QLabel(self.connectionTab)
        self.label.setGeometry(QtCore.QRect(40, 50, 211, 17))
        self.label.setObjectName("label")
        self.label_2 = QtWidgets.QLabel(self.connectionTab)
        self.label_2.setGeometry(QtCore.QRect(40, 80, 211, 17))
        self.label_2.setObjectName("label_2")
        self.label_3 = QtWidgets.QLabel(self.connectionTab)
        self.label_3.setGeometry(QtCore.QRect(40, 110, 211, 17))
        self.label_3.setObjectName("label_3")
        self.usernameText = QtWidgets.QLineEdit(self.connectionTab)
        self.usernameText.setGeometry(QtCore.QRect(250, 80, 531, 25))
        self.usernameText.setObjectName("usernameText")
        self.passwordText = QtWidgets.QLineEdit(self.connectionTab)
        self.passwordText.setGeometry(QtCore.QRect(250, 110, 531, 25))
        self.passwordText.setEchoMode(QtWidgets.QLineEdit.Password)
        self.passwordText.setObjectName("passwordText")
        self.serverCertPathText = QtWidgets.QLineEdit(self.connectionTab)
        self.serverCertPathText.setGeometry(QtCore.QRect(250, 140, 531, 25))
        self.serverCertPathText.setEchoMode(QtWidgets.QLineEdit.Normal)
        self.serverCertPathText.setObjectName("serverCertPathText")
        
       
        self.label_6 = QtWidgets.QLabel(self.connectionTab)
        self.label_6.setGeometry(QtCore.QRect(40, 240, 161, 17))
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        self.label_6.setFont(font)
        self.label_6.setObjectName("label_6")
        self.frame = QtWidgets.QFrame(self.connectionTab)
        self.frame.setGeometry(QtCore.QRect(10, 10, 961, 211))
        self.frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.frame.setFrameShadow(QtWidgets.QFrame.Raised)
        self.frame.setObjectName("frame")
        self.label_12 = QtWidgets.QLabel(self.frame)
        self.label_12.setGeometry(QtCore.QRect(30, 10, 151, 17))
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        self.label_12.setFont(font)
        self.label_12.setObjectName("label_12")
        self.connectButton = QtWidgets.QPushButton(self.frame)
        self.connectButton.setGeometry(QtCore.QRect(680, 160, 89, 25))
        self.connectButton.setObjectName("connectButton")
        self.label_4 = QtWidgets.QLabel(self.frame)
        self.label_4.setGeometry(QtCore.QRect(30, 160, 191, 17))
        self.label_4.setObjectName("label_4")
        self.connectStatusLabel = QtWidgets.QLabel(self.frame)
        self.connectStatusLabel.setGeometry(QtCore.QRect(240, 160, 131, 17))
        self.connectStatusLabel.setTextFormat(QtCore.Qt.PlainText)
        self.connectStatusLabel.setObjectName("connectStatusLabel")
        self.label_20 = QtWidgets.QLabel(self.frame)
        self.label_20.setGeometry(QtCore.QRect(30, 130, 201, 17))
        self.label_20.setObjectName("label_20")
        self.existingProjectFrame = QtWidgets.QFrame(self.connectionTab)
        self.existingProjectFrame.setGeometry(QtCore.QRect(10, 230, 491, 451))
        self.existingProjectFrame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.existingProjectFrame.setFrameShadow(QtWidgets.QFrame.Raised)
        self.existingProjectFrame.setObjectName("existingProjectFrame")

        self.existingProjectsList = QtWidgets.QListWidget(self.existingProjectFrame)
        self.existingProjectsList.setGeometry(QtCore.QRect(30, 30, 431, 331))
        self.existingProjectsList.setObjectName("existingProjectsList")
        
        self.selectExistingProjectButton = QtWidgets.QPushButton(self.existingProjectFrame)
        self.selectExistingProjectButton.setGeometry(QtCore.QRect(30, 410, 431, 25))
        self.selectExistingProjectButton.setObjectName("selectExistingProjectButton")
        self.deleteProject = QtWidgets.QPushButton(self.existingProjectFrame)
        self.deleteProject.setGeometry(QtCore.QRect(30, 375, 431, 25))
        self.deleteProject.setObjectName("deleteProject")
        self.newProjectFrame = QtWidgets.QFrame(self.connectionTab)
        self.newProjectFrame.setGeometry(QtCore.QRect(510, 230, 461, 451))
        self.newProjectFrame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.newProjectFrame.setFrameShadow(QtWidgets.QFrame.Raised)
        self.newProjectFrame.setObjectName("newProjectFrame")
        self.label_7 = QtWidgets.QLabel(self.newProjectFrame)
        self.label_7.setGeometry(QtCore.QRect(10, 10, 101, 17))
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        self.label_7.setFont(font)
        self.label_7.setObjectName("label_7")
        self.label_8 = QtWidgets.QLabel(self.newProjectFrame)
        self.label_8.setGeometry(QtCore.QRect(10, 40, 67, 17))
        self.label_8.setObjectName("label_8")
        self.newProjectName = QtWidgets.QLineEdit(self.newProjectFrame)
        self.newProjectName.setGeometry(QtCore.QRect(10, 60, 421, 25))
        self.newProjectName.setObjectName("newProjectName")
        self.label_9 = QtWidgets.QLabel(self.newProjectFrame)
        self.label_9.setGeometry(QtCore.QRect(10, 100, 67, 17))
        self.label_9.setObjectName("label_9")

        self.newProjectUsersList = QtWidgets.QListWidget(self.newProjectFrame)
        self.newProjectUsersList.setGeometry(QtCore.QRect(10, 120, 421, 281))
        self.newProjectUsersList.setObjectName("newProjectUsersList")
        self.newProjectUsersList.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
       
        self.createNewProjectButton = QtWidgets.QPushButton(self.newProjectFrame)
        self.createNewProjectButton.setGeometry(QtCore.QRect(10, 410, 421, 25))
        self.createNewProjectButton.setObjectName("createNewProjectButton")
        self.frame.raise_()
        self.progress_label.raise_()
        self.existingProjectFrame.raise_()
        self.serverText.raise_()
        self.label.raise_()
        self.label_2.raise_()
        self.label_3.raise_()
        self.usernameText.raise_()
        self.passwordText.raise_()
        self.serverCertPathText.raise_()
        self.existingProjectsList.raise_()
        self.label_6.raise_()
        self.newProjectFrame.raise_()
        self.mainTabWidget.addTab(self.connectionTab, "")
        self.projectTab = QtWidgets.QWidget()
        self.projectTab.setEnabled(False)
        self.projectTab.setObjectName("projectTab")
        projectLayout = QHBoxLayout()
        self.projectTab.setLayout(projectLayout)
        
        #self.projectTreeView = QtWidgets.QTreeWidget(self.projectTab)
        self.projectTreeView = ProjectTree(self.projectTab,self)
        self.projectTreeView.setGeometry(QtCore.QRect(10, 10, 961, 671))
        self.projectTreeView.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)  
        self.projectTreeView.customContextMenuRequested.connect(self.rightClickMenuHandle)  
        self.projectTreeView.setHeaderItem(QTreeWidgetItem(["File","Status"]))
        self.projectTreeView.setColumnWidth(0,500)
        self.projectTreeView.setDragEnabled(True)
        projectLayout.addWidget(self.projectTreeView)

        self.projectTreeView.setObjectName("projectTreeView")
        self.mainTabWidget.addTab(self.projectTab, "")
        self.adminTab = QtWidgets.QWidget()
        self.adminTab.setEnabled(False)
        self.adminTab.setObjectName("adminTab")
        self.frame_4 = QtWidgets.QFrame(self.adminTab)
        self.frame_4.setGeometry(QtCore.QRect(20, 10, 371, 191))
        self.frame_4.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.frame_4.setFrameShadow(QtWidgets.QFrame.Raised)
        self.frame_4.setObjectName("frame_4")
        self.label_10 = QtWidgets.QLabel(self.frame_4)
        self.label_10.setGeometry(QtCore.QRect(20, 10, 131, 17))
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        self.label_10.setFont(font)
        self.label_10.setObjectName("label_10")
        self.label_11 = QtWidgets.QLabel(self.frame_4)
        self.label_11.setGeometry(QtCore.QRect(20, 40, 141, 17))
        self.label_11.setObjectName("label_11")
        self.label_13 = QtWidgets.QLabel(self.frame_4)
        self.label_13.setGeometry(QtCore.QRect(20, 90, 179, 17))
        self.label_13.setObjectName("label_13")
        self.newPasswrdText1 = QtWidgets.QLineEdit(self.frame_4)
        self.newPasswrdText1.setGeometry(QtCore.QRect(20, 60, 331, 25))
        self.newPasswrdText1.setEchoMode(QtWidgets.QLineEdit.Password)
        self.newPasswrdText1.setObjectName("newPasswrdText1")
        self.newPasswrdText2 = QtWidgets.QLineEdit(self.frame_4)
        self.newPasswrdText2.setGeometry(QtCore.QRect(20, 110, 331, 25))
        self.newPasswrdText2.setEchoMode(QtWidgets.QLineEdit.Password)
        self.newPasswrdText2.setObjectName("newPasswrdText2")
        self.changePasswordButton = QtWidgets.QPushButton(self.frame_4)
        self.changePasswordButton.setGeometry(QtCore.QRect(20, 150, 331, 25))
        self.changePasswordButton.setObjectName("changePasswordButton")
        self.frame_5 = QtWidgets.QFrame(self.adminTab)
        self.frame_5.setGeometry(QtCore.QRect(20, 210, 371, 191))
        self.frame_5.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.frame_5.setFrameShadow(QtWidgets.QFrame.Raised)
        self.frame_5.setObjectName("frame_5")
        self.label_14 = QtWidgets.QLabel(self.frame_5)
        self.label_14.setGeometry(QtCore.QRect(20, 10, 171, 17))
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        self.label_14.setFont(font)
        self.label_14.setObjectName("label_14")
        self.label_15 = QtWidgets.QLabel(self.frame_5)
        self.label_15.setGeometry(QtCore.QRect(20, 40, 141, 17))
        self.label_15.setObjectName("label_15")
        self.label_16 = QtWidgets.QLabel(self.frame_5)
        self.label_16.setGeometry(QtCore.QRect(20, 90, 141, 17))
        self.label_16.setObjectName("label_16")
        self.newUserNameText = QtWidgets.QLineEdit(self.frame_5)
        self.newUserNameText.setGeometry(QtCore.QRect(20, 60, 331, 25))
        self.newUserNameText.setObjectName("newUserNameText")
        self.newUserPwdText = QtWidgets.QLineEdit(self.frame_5)
        self.newUserPwdText.setGeometry(QtCore.QRect(20, 110, 331, 25))
        self.newUserPwdText.setEchoMode(QtWidgets.QLineEdit.Password)
        self.newUserPwdText.setObjectName("newUserPwdText")
        self.newGlobalUserButton = QtWidgets.QPushButton(self.frame_5)
        self.newGlobalUserButton.setGeometry(QtCore.QRect(20, 150, 331, 25))
        self.newGlobalUserButton.setObjectName("newGlobalUserButton")
        self.frame_6 = QtWidgets.QFrame(self.adminTab)
        self.frame_6.setGeometry(QtCore.QRect(400, 10, 561, 391))
        self.frame_6.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.frame_6.setFrameShadow(QtWidgets.QFrame.Raised)
        self.frame_6.setObjectName("frame_6")
        self.frame_6.setEnabled(False)
        self.label_17 = QtWidgets.QLabel(self.frame_6)
        self.label_17.setGeometry(QtCore.QRect(10, 10, 281, 17))
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        self.label_17.setFont(font)
        self.label_17.setObjectName("label_17")
        self.label_18 = QtWidgets.QLabel(self.frame_6)
        self.label_18.setGeometry(QtCore.QRect(10, 40, 141, 17))
        self.label_18.setObjectName("label_18")
        self.label_19 = QtWidgets.QLabel(self.frame_6)
        self.label_19.setGeometry(QtCore.QRect(290, 40, 141, 17))
        self.label_19.setObjectName("label_19")
        self.projectCurrentUsersView = QtWidgets.QListWidget(self.frame_6)
        self.projectCurrentUsersView.setGeometry(QtCore.QRect(10, 60, 261, 281))
        self.projectCurrentUsersView.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.projectCurrentUsersView.setObjectName("projectCurrentUsersView")


        self.projectAllUsersView = QtWidgets.QListWidget(self.frame_6)
        self.projectAllUsersView.setGeometry(QtCore.QRect(290, 60, 261, 281))
        self.projectAllUsersView.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.projectAllUsersView.setObjectName("projectAllUsersView")

        self.currentProjectRemoveUsersButton = QtWidgets.QPushButton(self.frame_6)
        self.currentProjectRemoveUsersButton.setGeometry(QtCore.QRect(10, 350, 261, 25))
        self.currentProjectRemoveUsersButton.setObjectName("currentProjectRemoveUsersButton")
        self.currentProjectAddUsersButton = QtWidgets.QPushButton(self.frame_6)
        self.currentProjectAddUsersButton.setGeometry(QtCore.QRect(290, 350, 261, 25))
        self.currentProjectAddUsersButton.setObjectName("currentProjectAddUsersButton")

        self.deleteGlobalUsersFrame = QtWidgets.QFrame(self.adminTab)
        self.deleteGlobalUsersFrame.setGeometry(QtCore.QRect(20, 410, 371, 271))
        self.deleteGlobalUsersFrame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.deleteGlobalUsersFrame.setFrameShadow(QtWidgets.QFrame.Raised)
        self.deleteGlobalUsersFrame.setObjectName("deleteGlobalUsersFrame")
        self.deleteGlobalUsersLabel = QtWidgets.QLabel(self.deleteGlobalUsersFrame)
        self.deleteGlobalUsersLabel.setGeometry(QtCore.QRect(20, 10, 201, 17))
        font = QtGui.QFont()
        font.setBold(True)
        font.setWeight(75)
        self.deleteGlobalUsersLabel.setFont(font)
        self.deleteGlobalUsersLabel.setObjectName("deleteGlobalUsersLabel")
        self.deleteGlobalUsersList = QtWidgets.QListWidget(self.deleteGlobalUsersFrame)
        self.deleteGlobalUsersList.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.deleteGlobalUsersList.setGeometry(QtCore.QRect(20, 30, 331, 192))
        self.deleteGlobalUsersList.setObjectName("deleteGlobalUsersList")
        self.deleteGlobalUsersButton = QtWidgets.QPushButton(self.deleteGlobalUsersFrame)
        self.deleteGlobalUsersButton.setGeometry(QtCore.QRect(20, 230, 331, 25))
        self.deleteGlobalUsersButton.setObjectName("deleteGlobalUsersButton")


        self.mainTabWidget.addTab(self.adminTab, "")

        self.retranslateUi(Dialog)
        self.mainTabWidget.setCurrentIndex(0)
        QtCore.QMetaObject.connectSlotsByName(Dialog)

        # SAVE THIS
        self.newProjectFrame.setEnabled(False)
        self.existingProjectFrame.setEnabled(False)

        self.newGlobalUserButton.clicked.connect(self.addNewGlobalUserClickHandler)
        self.createNewProjectButton.clicked.connect(self.createNewProjectClickHandler)
        self.connectButton.clicked.connect(self.connectClickHandler)
        self.selectExistingProjectButton.clicked.connect(self.existingProjectSelectHandler)
        self.deleteProject.clicked.connect(self.deleteExistingProjectHandler)
        self.existingProjectsList.itemDoubleClicked.connect(self.existingProjectSelectHandler)
        self.currentProjectAddUsersButton.clicked.connect(self.addProjectUserClickHandler)
        self.currentProjectRemoveUsersButton.clicked.connect(self.deleteProjectUserClickHandler)
        self.changePasswordButton.clicked.connect(self.changePasswordClickHandler)
        self.projectTreeView.itemDoubleClicked.connect(self.openDoubleClickWrapper)
        self.deleteGlobalUsersButton.clicked.connect(self.deleteGlobalUsersHandler)
        

        self.prepopulateConnect()
        # SAVE THIS

    def retranslateUi(self, Dialog):
        _translate = QtCore.QCoreApplication.translate
        Dialog.setWindowTitle(_translate("Dialog", "CollaRE Client"))
        Dialog.setWindowIcon(QIcon(os.path.join(current_running_file_dir,"icons","collare.png")))
        self.label.setText(_translate("Dialog", "Server (https://remote.com/):"))
        self.progress_label.setText(_translate("Dialog", ""))
        self.label_2.setText(_translate("Dialog", "Username:"))
        self.label_3.setText(_translate("Dialog", "Password:"))
        self.label_6.setText(_translate("Dialog", "Avaialable Projects:"))
        self.label_12.setText(_translate("Dialog", "Connection Settings:"))
        self.connectButton.setText(_translate("Dialog", "Connect"))
        self.label_4.setText(_translate("Dialog", "Connection Status:"))
        self.connectStatusLabel.setText(_translate("Dialog", "Disconnected"))
        self.label_20.setText(_translate("Dialog", "Server certificate path:"))
        self.selectExistingProjectButton.setText(_translate("Dialog", "Select Project"))
        self.deleteProject.setText(_translate("Dialog", "Delete Project"))
        self.label_7.setText(_translate("Dialog", "New Project:"))
        self.label_8.setText(_translate("Dialog", "Name:"))
        self.label_9.setText(_translate("Dialog", "Users:"))
        self.createNewProjectButton.setText(_translate("Dialog", "Create Project"))
        self.mainTabWidget.setTabText(self.mainTabWidget.indexOf(self.connectionTab), _translate("Dialog", "Connection"))
        self.mainTabWidget.setTabText(self.mainTabWidget.indexOf(self.projectTab), _translate("Dialog", "Project View"))
        self.label_10.setText(_translate("Dialog", "Change Password:"))
        self.label_11.setText(_translate("Dialog", "New Password:"))
        self.label_13.setText(_translate("Dialog", "Confirm New Password:"))
        self.changePasswordButton.setText(_translate("Dialog", "Change Password"))
        self.label_14.setText(_translate("Dialog", "New User (admin only):"))
        self.label_15.setText(_translate("Dialog", "Username:"))
        self.label_16.setText(_translate("Dialog", "Password"))
        self.newGlobalUserButton.setText(_translate("Dialog", "Create User"))
        self.label_17.setText(_translate("Dialog", "Add/remove users of current project:"))
        self.label_18.setText(_translate("Dialog", "Current users:"))
        self.label_19.setText(_translate("Dialog", "All users:"))
        self.currentProjectRemoveUsersButton.setText(_translate("Dialog", "Remove Users"))
        self.currentProjectAddUsersButton.setText(_translate("Dialog", "Add Users"))
        self.deleteGlobalUsersLabel.setText(_translate("Dialog", "Remove Users (admin only):"))
        self.deleteGlobalUsersButton.setText(_translate("Dialog", "Delete Selected Users"))
        self.mainTabWidget.setTabText(self.mainTabWidget.indexOf(self.adminTab), _translate("Dialog", "Admin"))


class CollaRE(QtWidgets.QMainWindow, Ui_Dialog):
    def __init__(self, parent=None):
        super(CollaRE, self).__init__(parent)
        self.setupUi(self)

def main():
    # Create projects directory if it does not exist
    if not os.path.isdir(collare_home):
        os.mkdir(collare_home)
    app = QApplication(sys.argv)
    form = CollaRE()
    form.show()
    app.exec_()

if __name__ == '__main__':
    
    main()