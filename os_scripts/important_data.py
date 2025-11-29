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
    script_path = os.path.realpath(__file__)
    script_name = os.path.splitext(os.path.basename(script_path))[0]
    install_path = f"/usr/bin/{script_name}"
    if os.geteuid() != 0 or os.getegid() != 0:
        PrintError(f"{script_name} requires root. Try sudo {script_name}.")
        return 1

    service_payload = [
        f"[Unit]",
        f"Description=Mounts /important_data after root filesystem is mounted.",
        f"After=local-fs.target",
        f"Requires=local-fs.target",
        f"",
        f"[Service]",
        f"Type=oneshot",
        f"ExecStart=\"{install_path}\"",
        f"RemainAfterExit=yes",
        f"IgnoreFailure=yes",
        f"",
        f"[Install]",
        f"WantedBy=multi-user.target",
    ]
    service_path = "/etc/systemd/system/important_data.service"
    if os.path.exists(service_path) and os.path.getmtime(script_path) < os.path.getmtime(service_path):
        PrintWarning(f"Not installing because service in \"{service_path}\" is newer than \"{script_path}\".")
        return 1
    if os.path.exists(service_path) and os.path.getmtime(script_path) > os.path.getmtime(service_path):
        WriteFile(service_path, "".join([ line + "\n" for line in service_payload ]))
        script_stat = os.stat(script_path)
        os.utime(service_path, (script_stat.st_atime, script_stat.st_mtime))
        RunCommand(f"chmod 755 \"{service_path}\"")
        RunCommand(f"chown +0:+0 \"{service_path}\"")
        print(f"Installed {script_name} service to \"{service_path}\".")
    RunCommand("systemctl enable important_data")

    if not os.path.exists("/important_data"):
        RunCommand("mkdir /important_data")
        RunCommand("chmod 777 /important_data")
        RunCommand("chown root:root /important_data")
    if len(os.listdir("/important_data")) != 0:
        PrintError("/important_data is not empty.")
        return 1
    if RunCommand("findmnt /important_data", check=False) == 0:
        PrintError("Something is already mounted at /important_data.")
    important_data_dev, status_code = RunCommand("blkid --uuid c6b3988d-979c-4468-9b05-59c01ac32ad7", check=False, capture=True)
    if status_code != 0:
        PrintError("important_data drive is not connected to this PC.")
        return 1
    important_data_key_path = "/etc/important_data.key"
    if not os.path.exists(important_data_key_path):
        PrintError(f"Key could not be found at {important_data_key_path}.")
        return 1
    RunCommand(f"cryptsetup open \"{important_data_dev}\" crypt_important_data --key-file=\"{important_data_key_path}\"")
    RunCommand("mount -t ext4 -o rw,noatime,discard,errors=remount-ro /dev/mapper/crypt_important_data /important_data")

    return 0
sys.exit(Main())