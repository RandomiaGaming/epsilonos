#!/usr/bin/env python3
import subprocess
import os
import sys
import time

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

# Types of .backup files:
# lastpush.backup: Stores the timestamp when the given repo was last pushed to the remote.
# ignorerepos.backup: Tells this script not to commit, push, or warn about no remote for the git repo in the given folder.
# ignorecode.backup: Tells this script to silence warnings about unprotected code in the given folder recursively.
#
# To audit .backup files:
# find /important_data/ -type f -name "*.backup" -not -path "*/.git/lastpush.backup"

def Main():
    # Initial scanity checks
    if os.geteuid() == 0 or os.getegid() == 0:
        script_name = os.path.splitext(os.path.basename(os.path.realpath(__file__)))[0]
        PrintError(f"{script_name} may not be run as root. Please try again.")
        return 1
    if not "successfully authenticated" in RunCommand(f"ssh git@github.com", capture=True, check=False)[0]:
        PrintError("ssh doesn't seem to be properly setup. git@github.com refused authentication.")
        return 1
    if RunCommand(f"git config user.name", capture=True) == "":
        PrintError("Git username not set. Please run: git config --global user.name \"Your Name\"")
        return 1
    if RunCommand(f"git config user.email", capture=True) == "":
        PrintError("Git email not set. Please run: git config --global user.email \"Your Email\"")
        return 1
    if RunCommand(f"git config push.autoSetupRemote", capture=True) != "true":
        PrintError("Git is not configured with auto setup remote. Please run: git config --global push.autoSetupRemote true")
        return 1

    # Enumerating files and folders
    print("Enumerating files in /important_data/...")
    code_exts = [
        ".c", ".cpp", ".cc", ".asm", ".cs", ".java", # C family
        ".py", ".ps1", ".sh", ".cmd", ".bat", # Scripting
        ".js", ".ts", ".html", ".css", ".htm", # Web
        ".rb", ".swift", ".go", ".php", ".r", ".rs", ".sql", ".kt", ".dart" # Other
    ]
    code_paths = RunCommand(f"find \"/important_data/\" -type f" + " -o".join([ f" -name \"*{code_ext}\"" for code_ext in code_exts ]), capture=True).splitlines()
    repo_paths = [ os.path.dirname(repo_path) for repo_path in RunCommand(f"find \"/important_data/\" -type d -name \".git\"", capture=True).splitlines() ]
    backup_file_paths = RunCommand(f"find \"/important_data/\" -type f -name \"*.backup\"", capture=True).splitlines()
    ignore_repos_paths = []
    ignore_code_paths = []
    for backup_file_path in backup_file_paths:
        backup_file_name = os.path.basename(backup_file_path)
        if backup_file_name == "ignorerepos.backup":
           ignore_repos_paths.append(os.path.dirname(backup_file_path))
        elif backup_file_name == "ignorecode.backup":
           ignore_code_paths.append(os.path.dirname(backup_file_path))
        else:
            PrintWarning(f"Unknown backup file at \"{backup_file_path}\".")

    # Checking for unprotected code
    for code_path in code_paths:
        if any([ code_path.startswith(repo_path) for repo_path in repo_paths ]):
            continue
        if any([ code_path.startswith(ignore_code_path) for ignore_code_path in ignore_code_paths ]):
            continue
        PrintWarning(f"Unprotected code at \"{code_path}\".")

    # Committing and pushing git repos
    print("Committing and pushing all repos...")
    for repo_path in repo_paths:
        if any([ repo_path.startswith(ignore_repos_path) for ignore_repos_path in ignore_repos_paths ]):
            continue
        if not os.path.isfile(os.path.join(repo_path, ".gitignore")):
            PrintError(f"Repo missing required .gitignore. \"{repo_path}\"")
            continue
        os.chdir(repo_path)
        remote_url, status_code  = RunCommand(f"git remote get-url origin", capture=True, check=False)
        if status_code != 0 or not remote_url.startswith("git@github.com:RandomiaGaming/"):
            PrintError(f"Repo has invalid or non-existant remote origin. \"{repo_path}\".")
            continue
        if RunCommand("git rev-parse @", capture=True) != RunCommand("git rev-parse @{u}", capture=True):
            PrintError(f"Repo has become desync with remote origin. \"{repo_path}\".")
            continue
        changes = RunCommand(f"git status --porcelain", capture=True)
        if changes != "":
            print(f"Committing and pushing changes to \"{repo_path}\"...")
            RunCommand(f"git rm --cached -r .")
            RunCommand(f"git add --all")
            RunCommand(f"git commit -m\"Auto-generated backup commit.\"")
            RunCommand(f"git push origin --all")

    print("Backup Complete!")
    return 0
sys.exit(Main())