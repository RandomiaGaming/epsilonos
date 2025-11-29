#!/usr/bin/env python3
import subprocess
import os
import re
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

    # Initial setup and scanity checks
    if os.geteuid() != 0 or os.getegid() != 0:
        PrintError(f"Root is required to run {script_name}. Try sudo {script_name}.")
        return 1
    if RunCommand("findmnt --noheadings --raw --output source --target /boot", check=False) != 0:
        PrintError("Nothing is mounted on /boot. Did you forget something?")
        return 1
    if RunCommand("findmnt --noheadings --raw --output source --target /sys/firmware/efi/efivars/", check=False) != 0:
        PrintError("Nothing is mounted on /sys/firmware/efi/efivars/. Maybe you forgot to mount efivarsfs inside a chroot?")
        return 1
    kernel_paths = RunCommand("find /usr/lib/modules -maxdepth 2 -mindepth 2 -type f -name vmlinuz", capture=True).splitlines()
    if len(kernel_paths) == 0:
        PrintError("Unable to locate system kernel.")
        return 1
    if len(kernel_paths) > 1:
        PrintError("Multiple system kernels installed.")
        return 1
    kernel_path = kernel_paths[0]
    root_dev = RunCommand("findmnt --noheadings --raw --output source --target /", capture=True)
    crypt_info, crypt_status_code = RunCommand(f"cryptsetup status \"{root_dev}\"", capture=True, check=False)
    if crypt_status_code != 0:
        PrintError(f"{script_name} requires an encrypted root partition.")
        return 1
    crypt_root_dev = crypt_info[crypt_info.find("device:") + len("device:"):crypt_info.find("\n", crypt_info.find("device:") + len("device:"))].strip()
    optrom_esl_path = "/home/finlaytheberry/Desktop/optrom.esl"
    if not os.path.exists(optrom_esl_path):
        PrintError(f"OPTROM signatures could not be found at \"{optrom_esl_path}\".")
        return 1
    secure_boot = ReadFile("/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c", binary=True)[4:] == b"\x01"
    if not secure_boot:
        PrintError(f"Secure boot is disabled. This feature is required to use {script_name}.")
        return 1

    # Disable mkinitcpio hooks
    hooks_dir_path = "/usr/share/libalpm/hooks"
    for hook_name in os.listdir(hooks_dir_path):
        if "mkinitcpio" in hook_name and not hook_name.endswith(".disabled"):
            old_hook_path = os.path.join(hooks_dir_path, hook_name)
            new_hook_path = os.path.join(hooks_dir_path, hook_name + ".disabled")
            RunCommand(f"mv \"{old_hook_path}\" \"{new_hook_path}\"")

    # Install the boot builder pacman hook
    hook_payload = [
        f"# This file is auto-generated by {script_name}.",
        f"# Do not modify. All changes will be lost.",
        f"",
        f"[Trigger]",
        f"Operation = Install",
        f"Operation = Upgrade",
        f"Type = Package",
        f"Target = linux",
        f"",
        f"[Action]",
        f"Description = Running {script_name}...",
        f"When = PostTransaction",
        f"Exec = {install_path}",
    ]
    hook_path = os.path.join(hooks_dir_path, "boot_builder.hook")
    WriteFile(hook_path, "".join([ line + "\n" for line in hook_payload ]))
    RunCommand(f"chmod 644 \"{hook_path}\"")
    RunCommand(f"chown +0:+0 \"{hook_path}\"")

    # Create boot builder temp folder
    temp_dir_path = "/tmp/boot_builder"
    RunCommand(f"rm -rf \"{temp_dir_path}\"")
    RunCommand(f"mkdir \"{temp_dir_path}\"")
    RunCommand(f"chmod 700 \"{temp_dir_path}\"")
    RunCommand(f"chown +0:+0 \"{temp_dir_path}\"")

    # Generate initramfs
    print("Making initramfs...")
    mkinitcpio_conf_path = os.path.join(temp_dir_path, "mkinitcpio.conf")
    mkinitcpio_conf = [
        f"MODULES=(fat vfat nls_iso8859_1)",
        f"BINARIES=()",
        f"FILES=()",
        f"HOOKS=(autodetect base udev microcode keyboard keymap numlock block encrypt filesystems)",
        f"COMPRESSION=\"cat\"",
        f"COMPRESSION_OPTIONS=()",
    ]
    WriteFile(mkinitcpio_conf_path, "".join([ line + "\n" for line in mkinitcpio_conf ]))
    cpio_path = os.path.join(temp_dir_path, "initramfs.cpio")
    RunCommand(f"mkinitcpio -c \"{mkinitcpio_conf_path}\" -g \"{cpio_path}\" -k \"{kernel_path}\"")

    # Compress initramfs
    print("Compressing initramfs...")
    cpio_zstd_path = cpio_path + ".zst"
    RunCommand(f"zstd --rm \"{cpio_path}\" -o \"{cpio_zstd_path}\"")

    # Generate unified kernel image
    print("Making unified kernel image...")
    crypt_root_uuid = RunCommand(f"blkid -o value -s UUID \"{crypt_root_dev}\"", capture=True)
    cmdline = f"cryptdevice=UUID={crypt_root_uuid}:crypt_root root=/dev/mapper/crypt_root rw"
    kernel_info = RunCommand(f"file \"{kernel_path}\"", capture=True)
    uname = kernel_info[kernel_info.find("version ") + len("version "):]
    uname = uname[:uname.find(" ")]
    ukify_conf_path = os.path.join(temp_dir_path, "ukify.conf")
    ukify_conf = [
        f"[UKI]",
        f"Linux={kernel_path}",
        f"Initrd={cpio_zstd_path}",
        f"OSRelease=EOS",
        f"Uname={uname}",
        f"Cmdline={cmdline}",
    ]
    WriteFile(ukify_conf_path, "".join([ line + "\n" for line in ukify_conf ]))
    efi_path = os.path.join(temp_dir_path, "eos.efi")
    RunCommand(f"ukify -c \"{ukify_conf_path}\" build -o \"{efi_path}\"")
    RunCommand(f"rm \"{cpio_zstd_path}\"")

    # Install uki to boot partition
    RunCommand("rm -rf /boot/*")
    RunCommand("chmod 700 /boot")
    RunCommand("chown +0:+0 /boot")
    RunCommand("mkdir /boot/EFI")
    RunCommand("chmod 700 /boot/EFI")
    RunCommand("chown +0:+0 /boot/EFI")
    RunCommand("mkdir /boot/EFI/BOOT")
    RunCommand("chmod 700 /boot/EFI/BOOT")
    RunCommand("chown +0:+0 /boot/EFI/BOOT")
    RunCommand(f"cp \"{efi_path}\" /boot/EFI/BOOT/BOOTX64.EFI")
    RunCommand("chmod 700 /boot/EFI/BOOT/BOOTX64.EFI")
    RunCommand("chown +0:+0 /boot/EFI/BOOT/BOOTX64.EFI")

    # Setup efi boot entries as needed
    for line in RunCommand("efibootmgr", capture=True).splitlines():
        if not len(line) > 8:
            continue
        if not line.startswith("Boot"):
            continue
        if not line[8:].startswith(" ") and not line[8:].startswith("* "):
            continue
        boot_num = line[4:8]
        if not all([ c in "0123456789" for c in boot_num ]):
            continue
        RunCommand(f"efibootmgr --delete-bootnum --bootnum {boot_num}")
    boot_dev = RunCommand("findmnt --noheadings --raw --output source --target /boot", capture=True)
    boot_disk = os.path.join("/dev", RunCommand(f"lsblk --noheadings --raw --output PKNAME \"{boot_dev}\"", capture=True))
    boot_part = RunCommand(f"lsblk --noheadings --raw --output PARTN \"{boot_dev}\"", capture=True)
    RunCommand(f"efibootmgr --create-only --disk \"{boot_disk}\" --part \"{boot_part}\" --loader \"\\EFI\\BOOT\\BOOTX64.EFI\" --label \"EOS\"")
    for line in RunCommand("efibootmgr", capture=True).splitlines():
        if not len(line) > 8:
            continue
        if not line.startswith("Boot"):
            continue
        if not line[8:].startswith(" ") and not line[8:].startswith("* "):
            continue
        boot_num = line[4:8]
        if not all([ c in "0123456789" for c in boot_num ]):
            continue
        RunCommand(f"efibootmgr --bootorder {boot_num}")
        break
    RunCommand("efibootmgr --timeout 0", check=False)
    RunCommand("efibootmgr --delete-bootnext", check=False)

    # Generate efi certs, keys, and values for efi vars
    eos_uuid = "81702c04-15cc-4573-b5d4-c3a476b635dc"
    openssl_conf = "x509_extensions = noext\n[noext]\nsubjectKeyIdentifier=none"
    openssl_conf_path = os.path.join(temp_dir_path, "openssl.conf")
    WriteFile(openssl_conf_path, openssl_conf)
    keys_dir_path = "/etc/efi_keys"
    if not os.path.exists(keys_dir_path):
        RunCommand(f"mkdir \"{keys_dir_path}\"")
        RunCommand(f"chmod 700 \"{keys_dir_path}\"")
        RunCommand(f"chown +0:+0 \"{keys_dir_path}\"")

    pk_key_path = os.path.join(keys_dir_path, "PK.key")
    if not os.path.exists(pk_key_path):
        RunCommand(f"openssl genrsa -out \"{pk_key_path}\" 4096")
    pk_cert_path = os.path.join(keys_dir_path, "PK.crt")
    if not os.path.exists(pk_cert_path):
        RunCommand(f"openssl req -new -x509 -key \"{pk_key_path}\" -out \"{pk_cert_path}\" -days 3650 -sha256 -subj \"/CN=EOS Autogenerated PK\" -config \"{openssl_conf_path}\"")
    pk_esl_path = os.path.join(keys_dir_path, "PK.esl")

    if not os.path.exists(pk_esl_path):
        RunCommand(f"cert-to-efi-sig-list -g \"{eos_uuid}\" \"{pk_cert_path}\" \"{pk_esl_path}\"")
    kek_key_path = os.path.join(keys_dir_path, "KEK.key")
    if not os.path.exists(kek_key_path):
        RunCommand(f"openssl genrsa -out \"{kek_key_path}\" 4096")
    kek_cert_path = os.path.join(keys_dir_path, "KEK.crt")
    if not os.path.exists(kek_cert_path):
        RunCommand(f"openssl req -new -x509 -key \"{kek_key_path}\" -out \"{kek_cert_path}\" -days 3650 -sha256 -subj \"/CN=EOS Autogenerated KEK\" -config \"{openssl_conf_path}\"")
    kek_esl_path = os.path.join(keys_dir_path, "KEK.esl")
    if not os.path.exists(kek_esl_path):
        RunCommand(f"cert-to-efi-sig-list -g \"{eos_uuid}\" \"{kek_cert_path}\" \"{kek_esl_path}\"")

    db_esl_path = os.path.join(keys_dir_path, "db.esl")
    RunCommand(f"hash-to-efi-sig-list \"{efi_path}\" \"{db_esl_path}\"")
    RunCommand(f"cat \"{optrom_esl_path}\" >> \"{db_esl_path}\"")

    dbx_payload = b"\x26\x16\xC4\xC1\x4C\x50\x92\x40\xAC\xA9\x41\xF9\x36\x93\x43\x28\x4C\x00\x00\x00\x00\x00\x00\x00\x30\x00\x00\x00\x04\x2C\x70\x81\xCC\x15\x73\x45\xB5\xD4\xC3\xA4\x76\xB6\x35\xDC\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    dbx_esl_path = os.path.join(keys_dir_path, "dbx.esl")
    if not os.path.exists(dbx_esl_path):
        WriteFile(dbx_esl_path, dbx_payload, binary=True)

    # 
    RunCommand(f"chattr = /sys/firmware/efi/efivars/PK-8be4df61-93ca-11d2-aa0d-00e098032b8c", check=False)
    pk_actual = ReadFile("/sys/firmware/efi/efivars/PK-8be4df61-93ca-11d2-aa0d-00e098032b8c", binary=True)[4:]
    pk_expected = ReadFile(pk_esl_path, binary=True)
    if pk_actual != pk_expected:
        setup_mode = ReadFile("/sys/firmware/efi/efivars/SetupMode-8be4df61-93ca-11d2-aa0d-00e098032b8c", binary=True)[4:] == b"\x01"
        print("we fucked")

    RunCommand(f"chattr = /sys/firmware/efi/efivars/KEK-8be4df61-93ca-11d2-aa0d-00e098032b8c", check=False)
    KEK = ReadFile("/sys/firmware/efi/efivars/KEK-8be4df61-93ca-11d2-aa0d-00e098032b8c", binary=True)[4:]
    RunCommand(f"chattr = /sys/firmware/efi/efivars/db-d719b2cb-3d3a-4596-a3bc-dad00e67656f", check=False)
    db = ReadFile("/sys/firmware/efi/efivars/db-d719b2cb-3d3a-4596-a3bc-dad00e67656f", binary=True)[4:]
    RunCommand(f"chattr = /sys/firmware/efi/efivars/dbx-d719b2cb-3d3a-4596-a3bc-dad00e67656f", check=False)
    dbx = ReadFile("/sys/firmware/efi/efivars/dbx-d719b2cb-3d3a-4596-a3bc-dad00e67656f", binary=True)[4:]


    RunCommand(f"sign-efi-sig-list -g {eos_uuid} -c /etc/keys/PK.crt -k /etc/keys/PK.key PK /tmp/bootbuilder/PK.esl /tmp/bootbuilder/PK.auth")
    RunCommand(f"efi-updatevar -f /tmp/bootbuilder/PK.auth PK")

    RunCommand(f"sign-efi-sig-list -g {eos_uuid} -c /etc/keys/PK.crt -k /etc/keys/PK.key KEK /tmp/bootbuilder/KEK.esl /tmp/bootbuilder/KEK.auth")
    RunCommand(f"efi-updatevar -f /tmp/bootbuilder/KEK.auth KEK")



    RunCommand(f"sign-efi-sig-list -g {eos_uuid} -c /etc/keys/KEK.crt -k /etc/keys/KEK.key db /tmp/bootbuilder/db.esl /tmp/bootbuilder/db.auth")
    RunCommand(f"efi-updatevar -f /tmp/bootbuilder/db.auth db")

    RunCommand(f"sign-efi-sig-list -g {eos_uuid} -c /etc/keys/KEK.crt -k /etc/keys/KEK.key dbx /tmp/bootbuilder/dbx.esl /tmp/bootbuilder/dbx.auth")
    RunCommand(f"efi-updatevar -f /tmp/bootbuilder/dbx.auth dbx")

    # Post Install Cleanup
    RunCommand(f"rm -rf \"{temp_dir_path}\"")
    print("Successfully updated and installed new bootloader!")
    return 0
sys.exit(Main())