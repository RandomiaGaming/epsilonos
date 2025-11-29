#!/usr/bin/env python3
import subprocess
import os
import sys

# region EOS Script Helpers
def WriteFile(filePath, contents, binary=False):
    filePath = os.path.realpath(os.path.expanduser(filePath))
    os.makedirs(os.path.dirname(filePath), exist_ok=True)
    with open(filePath, "wb" if binary else "w", encoding=(None if binary else "UTF-8")) as file:
        file.write(contents)
def ReadFile(filePath, defaultContents=None, binary=False):
    filePath = os.path.realpath(os.path.expanduser(filePath))
    if not os.path.exists(filePath):
        if defaultContents != None:
            return defaultContents
    with open(filePath, "rb" if binary else "r", encoding=(None if binary else "UTF-8")) as file:
        return file.read()
def RunCommand(command, echo=False, capture=False, input=None, check=True):
    result = subprocess.run(command, capture_output=(not echo), input=input, check=check, shell=True, text=True)
    if capture and not check:
        return (result.stdout + result.stderr).strip(), result.returncode
    elif capture:
        return (result.stdout + result.stderr).strip()
    elif not check:
        return result.returncode
    else:
        return
def PrintWarning(message):
    print(f"\033[93mWarning: {message}\033[0m")
def PrintError(message):
    print(f"\033[91mERROR: {message}\033[0m")
def Install():
    script_path = os.path.realpath(__file__)
    script_name = os.path.splitext(os.path.basename(script_path))[0]
    install_path = f"/usr/bin/{script_name}"
    if script_path == install_path:
        return
    if os.path.exists(install_path) and os.path.getmtime(script_path) == os.path.getmtime(install_path):
        return
    if os.path.exists(install_path) and os.path.getmtime(script_path) < os.path.getmtime(install_path):
        PrintWarning(f"Not installing because script in \"{install_path}\" is newer than \"{script_path}\".")
        return
    if os.geteuid() != 0 or os.getegid() != 0:
        print(f"Root is required to install \"{script_path}\" to \"{install_path}\".")
    sudo_commands = [
        f"cp -p \"{script_path}\" \"{install_path}\"",
        f"chmod 755 \"{install_path}\"",
        f"chown +0:+0 \"{install_path}\"",
    ]
    RunCommand(f"sudo sh -c \'{"; ".join(sudo_commands)}\'")
    print(f"Installed \"{script_path}\" to \"{install_path}\".")
    print()
Install()
# endregion

def Main():
    if os.geteuid() == 0 or os.getegid() == 0:
        script_name = os.path.splitext(os.path.basename(os.path.realpath(__file__)))[0]
        PrintError(f"{script_name} may not be run as root. Please try again.")
        return 1
    print()

    print("\033[36mClearing cache...\033[0m")
    RunCommand("yay -Scc --noconfirm", echo=True)
    print()

    print(f"\033[36mRemoving orphaned packages...\033[0m")
    stdout, statusCode = RunCommand("yay -Qqdt", capture=True, check=False)
    orphans = stdout.splitlines()
    if len(orphans) == 0:
        print("There is nothing to do.")
    else:
        print(f"{" ".join(orphans)}")
        RunCommand(f"yay -Rns {" ".join(orphans)} --noconfirm")
    print()

    print("\033[36mUpdating all packages...\033[0m")
    RunCommand("yay -Syu --noconfirm", echo=True)
    print()

    return 0
sys.exit(Main())