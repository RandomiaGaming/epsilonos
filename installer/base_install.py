#!/bin/env python

import os
import sys
import requests

from lib_installer import *

def main():
    # Initialization and scanity checking
    RequirePackage("util-linux") # lsblk wipefs mount blockdev
    RequirePackage("cryptsetup") # cryptsetup
    RequirePackage("gptfdisk") # sgdisk
    RequirePackage("dosfstools") # mkfs.fat
    RequirePackage("e2fsprogs") # mkfs.ext4
    RequirePackage("arch-install-scripts") # pacstrap arch-chroot
    AssertPacmanPacs()
    AssertRoot()
    Assertx64()
    AssertEfi()
    if os.path.ismount("/new_root"):
        raise Exception("Something is already mounted at /new_root. Please manually unmount.")
    if os.path.isdir("/new_root") and len(os.listdir("/new_root")) != 0:
        raise Exception("/new_root already exists and is not empty. Please manually check.")
    if os.path.exists("/dev/mapper/new_cryptroot"):
        raise Exception("Something is already open in cryptsetup as new_cryptroot. Please manually close.")
    AssertInternet()
    print()
    print("----- EOS Base Installer v1.1.0 -----")
    print()

    # User input for disk, partitions, and filesystems phase of installation
    print("List of disks:")
    RunCommand("lsblk -d -n -o NAME,MODEL,SIZE,TYPE | grep \' disk$\' | sed \'s/ disk$//\'", echo=True)
    validDrives = RunCommand("lsblk -d -n -o NAME,TYPE | grep \' disk$\' | sed \'s/ disk$//\'", capture=True)
    validDrives = [validDrive.strip() for validDrive in validDrives.splitlines() if validDrive.strip()]
    while True:
        print("Select a disk from the list above to install EOS: ", end="")
        eosDrive = input()
        if not eosDrive in validDrives:
            PrintError(f"/dev/{eosDrive} is not a valid disk.")
        elif int(RunCommand(f"blockdev --getsize64 /dev/{eosDrive}", capture=True)) < 4_000_000_000:
            PrintError(f"/dev/{eosDrive} must have at least 4GB of space to install EOS.")
        else:
            break
    print()

    PrintWarning(f"All data on {RunCommand(f"lsblk -d -n -o MODEL,SIZE /dev/{eosDrive}", capture=True)} will be destroyed!")
    if not Choice("Are you sure you want to proceed?"):
        print()
        print("Aborting install. Nothing was changed.")
        print()
        sys.exit(1)
    print()

    while True:
        diskPass = input("Please enter your password for disk encryption: ")
        if diskPass == "":
            PrintError("Disk encryption is required to install EOS and your password may not be blank.")
            continue
        if len(diskPass) < 16:
            PrintWarning(f"A password of length 16 or greater is highly recommended but yours is only {len(diskPass)}.")
            if not Choice("Are you sure you want to proceed?"):
                print("Okay let's start over.")
                continue
        diskPassConfirmation = input("Please retype your password for disk encryption to confirm: ")
        if diskPass != diskPassConfirmation:
            PrintError("Passwords did not match. Let's start over.")
            continue
        break
    print()

    # Disk, partition, filesystem, and encryption setup
    print("Creating new GPT partition table...")
    RunCommand(f"wipefs -a /dev/{eosDrive}")
    RunCommand(f"sgdisk --clear /dev/{eosDrive}")

    print("Creating partitions...")
    RunCommand(f"sgdisk --new=0:0:+512M --typecode=0:EF00 --change-name=0:\"EOS EFI Partition\" /dev/{eosDrive}")
    RunCommand(f"sgdisk --new=0:0:0 --typecode=0:8309 --change-name=0:\"EOS Root\" /dev/{eosDrive}")
    
    print("Setting up disk encryption...")
    RunCommand(f"cryptsetup luksFormat /dev/{eosDrive}{"p2" if eosDrive.startswith("nvme") else "2"} --type luks2 --cipher aes-xts-plain64 --force-password --hash sha512 --pbkdf argon2id --use-random --batch-mode", input=diskPass) # OPTIONAL: --integrity hmac-sha256
    RunCommand(f"cryptsetup open /dev/{eosDrive}{"p2" if eosDrive.startswith("nvme") else "2"} new_cryptroot --batch-mode", input=diskPass)

    print("Creating filesystems...")
    RunCommand(f"mkfs.fat -F32 -n \"EFI\" -S 4096 /dev/{eosDrive}{"p1" if eosDrive.startswith("nvme") else "1"}")
    RunCommand("mkfs.ext4 -q -L \"EOS Root\" -E lazy_journal_init /dev/mapper/new_cryptroot")
    
    print("Mounting filesystems...")
    os.makedirs("/new_root/", exist_ok=True)
    RunCommand("mount /dev/mapper/new_cryptroot /new_root")
    os.makedirs("/new_root/boot", exist_ok=True)
    RunCommand(f"mount /dev/{eosDrive}{"p1" if eosDrive.startswith("nvme") else "1"} /new_root/boot")
    
    # Genfstab
    print(f"Generating fstab...")
    bootPartitionUUID = RunCommand(f"blkid -o value -s UUID /dev/{eosDrive}{"p1" if eosDrive.startswith("nvme") else "1"}", capture=True)
    rootPartitionUUID = RunCommand("blkid -o value -s UUID /dev/mapper/new_cryptroot", capture=True)
    eosDriveSupportsTrim = ReadFile(f"/sys/block/{eosDrive}/queue/discard_max_bytes").strip() != "0"
    fstab = [
        "# <partition> <mount point> <filesystem type> <options> <dump> <pass>",
        "",
        "# EOS Root",
        f"UUID={rootPartitionUUID} / ext4 rw,noatime,errors=remount-ro{",discard" if eosDriveSupportsTrim else ""} 0 1",
        "",
        "# EOS EFI Partition",
        f"UUID={bootPartitionUUID} /boot vfat rw,noatime,errors=remount-ro,uid=0,gid=0,dmask=0077,fmask=0177,codepage=437,iocharset=ascii,shortname=mixed,utf8{",discard" if eosDriveSupportsTrim else ""} 0 2",
    ]
    os.makedirs("/new_root/etc/", exist_ok=True)
    WriteFile("/new_root/etc/fstab", "\n".join(fstab))
    print()

    # Pacstrap base system install
    print("Installing base system... (This will take a very long time.)")
    RunCommand("pacstrap /new_root base linux linux-firmware --noconfirm", echo=True)
    print("Installed base system.")
    print()

    # DONT FORGET TO CREATE SOME SWAP
    # for example a swap file can be created like this
    # fallocate -l 64G /swapfile
    # sudo chmod 600 /swapfile
    # sudo chown +0:+0 /swapfile
    # sudo mkswap /swapfile
    # sudo swapon /swapfile

    return


    # Guess and set the user's timezone
    try:
        response = requests.get("https://ipapi.co/timezone/")
        response.raise_for_status()
        timezone = response.text.strip()
    except:
        print(f"\033[0m\033[33mWARNING: Internet is required to auto set your timezone. Defaulting to UTC.\033[0m")
        timezone = "UTC"
    RunCommand(f"ln -sf /new_root/usr/share/zoneinfo/{timezone} /new_root/etc/localtime")
    
    # Guess and set the user's locale
    try:
        response = requests.get("https://ipapi.co/languages/")
        response.raise_for_status()
        language = response.text.strip()
    except:
        print(f"\033[0m\033[33mWARNING: Internet is required to auto set your locale. Defaulting to en_US.\033[0m")
        language = "en_US"
    if "," in language: language = language[0:language.index(",")]
    language = language.replace("-", "_")
    bestLocale = "es_US.UTF-8 UTF-8"
    with open("/new_root/usr/share/i18n/SUPPORTED", "r", encoding="UTF-8") as supportedLocalesFile:
        locales = [locale.strip() for locale in supportedLocalesFile.readlines()]
        for locale in locales:
            langMatch = language in locale
            bestLangMatch = language in bestLocale
            charsetMatch = "UTF-8" in locale
            bestCharsetMatch = "UTF-8" in bestLocale
            if langMatch and not bestLangMatch:
                bestLocale = locale
            if langMatch and charsetMatch and not bestCharsetMatch:
                bestLocale = locale
    WriteFile("/new_root/etc/locale.gen", bestLocale)
    RunCommand(f"arch-chroot /new_root locale-gen")
    
    # Update the system time and set the timedate service to localtime
    RunCommand("arch-chroot /new_root systemctl enable systemd-timesyncd --now")
    RunCommand("arch-chroot /new_root timedatectl set-ntp true")
    RunCommand("arch-chroot /new_root timedatectl set-local-rtc 1 --adjust-system-clock")

    # Set the hostname of the new system
    WriteFile("/new_root/etc/hostname", "EOS")

    # Setup root account
    RunCommand(f"arch-chroot /new_root usermod -p \'!*\' root")
    RunCommand(f"arch-chroot /new_root usermod -s /usr/bin/nologin root")

    # Setup user account
    username = input("Please input your username: ")
    password = input("Please input your password: ")
    password = password.replace("\'", "\'\\\'\'")
    if ":" in username:
        raise Exception("Usernames may not contain colons :")
    RunCommand(f"arch-chroot /new_root useradd -m -G wheel {username}")
    RunCommand(f"arch-chroot /new_root echo '{username}:{password}' | chpasswd")
    RunCommand(f"arch-chroot /new_root chage -m -1 -M -1 -W -1 -I -1 -E \"\" \'{username}\'")
    
    # Set sudoers file
    sudoers = """Defaults!/usr/bin/visudo env_keep += "SUDO_EDITOR EDITOR VISUAL"
Defaults secure_path="/usr/local/sbin:/usr/local/bin:/usr/bin"
Defaults timestamp_timeout=0
Defaults requiretty
Defaults env_reset
Defaults always_set_home

%wheel ALL=(ALL:ALL) ALL
root ALL=(ALL:ALL) ALL
"""
    WriteFile("/new_root/etc/sudoers", sudoers)
    os.chmod("/new_root/etc/sudoers", 0o440)
    os.chown("/new_root/etc/sudoers", 0, 0)

    # Setup networkd and resolved
    RunCommand(f"arch-chroot /new_root systemctl enable systemd-networkd.service --now")
    RunCommand(f"arch-chroot /new_root systemctl enable systemd-resolved.service --now")
    RunCommand(f"arch-chroot /new_root ln -sf /run/systemd/resolve/stub-resolv.conf /etc/resolv.conf")
    eosDotNetwork = """[Match]
Name=en* wl* ww*

[Network]
DHCP=yes
IPv6PrivacyExtensions=yes
LLDP=no

[DHCP]
UseDNS=no
UseHostname=no
UseDomains=no
UseRoutes=yes"""
    WriteFile("/new_root/etc/systemd/network/eos.network", eosDotNetwork)
    resolvedDotConf = """[Resolve]
DNS=1.1.1.1 1.0.0.1
FallbackDNS=2606:4700:4700::1111 2606:4700:4700::1001
DNSSEC=yes
DNSOverTLS=yes
MulticastDNS=no
LLMNR=no
Cache=yes
CacheFromLocalhost=no
DNSStubListener=yes
ReadEtcHosts=yes
ResolveUnicastSingleLabel=no
StaleRetentionSec=0"""
    WriteFile("/etc/systemd/resolved.conf", resolvedDotConf)

try:
    main()
except Exception as ex:
    print()
    PrintError(ex)
    print()
    sys.exit(1)

"""
# -- Setting up wifi for live cd (optional) --
# First scan for wifi adaperts
iwctl device list

# Then scan for wifi networks
iwctl station wlan0 scan
iwctl station wlan0 get-networks

# Then connect to a wifi network
iwctl station wlan0 connect FinFi

# Then test
iwctl station wlan0 show
ping google.com



# -- Installing Base System --
# Keyring Troubleshooting (optional)
# If you try the steps below and get keyring related errors then try this
pacman-key --init
pacman-key --populate archlinux

# Next we install other useful tools (optional)
pacstrap /mnt nano sudo base-devel git

# Next install wifi service (optional)
pacstrap /mnt iwd

# -- Settings/Configs (from chroot) --
# Next enable wifi service (optional)
# You should only do this if you installed iwd with pacstrap earlier
systemctl enable iwd

# Next set the default boot target
ln -sf /usr/lib/systemd/system/multi-user.target /etc/systemd/system/default.target

# -- Bootloader (SystemDBoot) (from chroot) --
# First install systemd boot
bootctl install

# Next set general systemd boot settings
echo -e "default arch" > /boot/loader/loader.conf
echo -e "timeout 0" >> /boot/loader/loader.conf
echo -e "editor 0" >> /boot/loader/loader.conf

# Next create arch linux systemd boot entry
echo -e "title Arch Linux" > /boot/loader/entries/arch.conf
echo -e "linux /vmlinuz-linux" >> /boot/loader/entries/arch.conf
echo -e "initrd /initramfs-linux.img" >> /boot/loader/entries/arch.conf
echo -e "options cryptdevice=UUID=$(blkid -o value -s UUID /dev/sda1):cryptroot root=/dev/mapper/cryptroot rw" >> /boot/loader/entries/arch.conf # If encrypted
echo -e "options root=/dev/sda1 rw" >> /boot/loader/entries/arch.conf # If unencrypted

# Next install yay manually (optional)
mkdir /yay
chown finlaytheberry:finlaytheberry /yay
su finlaytheberry
git clone https://aur.archlinux.org/yay.git
cd yay
makepkg -si
yay -Rns yay-debug
exit
rm -rf /yay

# Next set the yay config (optional)
su finlaytheberry
echo -e "{" > ~/.config/yay/config.json
echo -e "    "buildDir": "/tmp/yay"," >> ~/.config/yay/config.json
echo -e "    "cleanBuild": false," >> ~/.config/yay/config.json
echo -e "    "diffmenu": false," >> ~/.config/yay/config.json
echo -e "    "editmenu": false," >> ~/.config/yay/config.json
echo -e "    "noconfirm": true" >> ~/.config/yay/config.json
echo -e "}" >> ~/.config/yay/config.json
exit

# Next install mkinitcpio-numlock with yay (optional)
su finlaytheberry
yay -S mkinitcpio-numlock
exit

# Set systemd boot hooks and regenerate initramfs
echo -e "MODULES=()" > /etc/mkinitcpio.conf
echo -e "BINARIES=()" >> /etc/mkinitcpio.conf
echo -e "FILES=()" >> /etc/mkinitcpio.conf
echo -e "HOOKS=(base udev autodetect microcode modconf kms keyboard keymap consolefont numlock block encrypt filesystem fsck)" >> /etc/mkinitcpio.conf # If you want numlock
echo -e "HOOKS=(base udev autodetect microcode modconf kms keyboard keymap consolefont block encrypt filesystem fsck)" >> /etc/mkinitcpio.conf # If you dont want numlock
mkinitcpio -P

# -- Setting up wifi (optional) --
# If you need to setup wifi 
# First scan for wifi adaperts
iwctl device list

# Then scan for wifi networks
iwctl station wlan0 scan
iwctl station wlan0 get-networks

# Then connect to a wifi network
iwctl station wlan0 connect FinFi

# Then test
iwctl station wlan0 show
ping google.com

# Then enable DHCP
echo -e "[Match]" > /etc/systemd/network/default.network
echo -e "Name=*" >> /etc/systemd/network/default.network
echo -e "" >> /etc/systemd/network/default.network
echo -e "[Network]" >> /etc/systemd/network/default.network
echo -e "DHCP=yes" >> /etc/systemd/network/default.network

# -- Setting the fastest mirrors (optional) --
yay -S reflector
sudo reflector --country "United States" --age 48 --protocol https --sort rate --save /etc/pacman.d/mirrorlist

# -- Plasma Desktop Environment --
# First install the programs needed for kde plasma desktop
yay -S sddm plasma-desktop sddm-kcm plasma-workspace qt6-wayland
# Next enable and configure sddm
sudo systemctl enable sddm
sudo echo -e "[Theme]" > /etc/sddm.conf
sudo echo -e "Current=breeze" >> /etc/sddm.conf
# Next enable numlock in sddm while we are here (optional)
sudo echo -e "" >> /etc/sddm.conf
sudo echo -e "[General]" >> /etc/sddm.conf
sudo echo -e "Numlock=on" >> /etc/sddm.conf
# Next restart sddm after updating sddm.conf
sudo systemctl restart sddm
# Finally set the boot target to graphical.target and reboot
sudo ln -sf /usr/lib/systemd/system/graphical.target /etc/systemd/system/default.target
sudo reboot

# -- Audio Setup --
# Install the tools needed for audio on linux with kde plasma
yay -S pipewire pipewire-pulse pavucontrol plasma-pa
# Sadly this seems to require a reboot
sudo reboot

# -- KDE Wallet Setup --
yay -S kwalletmanager gnupg
gpg --quick-gen-key "FinlayTheBerry <finlaytheberry@gmail.com>" rsa4096 default 0
kwalletmanager5
# Then from in the gui create a new wallet and use the GPG key we just created

# -- KDE Plasma Settings (optional) --
# Settings>Keyboard>NumLock on startup = Turn on
# Settings>Keyboard>Key Repeat>Delay=200 ms
# Settings>Keyboard>Key Repeat>Rate=30 repeats/s

# -- NVIDIA Drivers (optional) --
yay -S nvidia nvidia-utils lib32-nvidia-utils
reboot
# Then add the following to Environment Variables of the shortcut for programs you want to run on the nvidia gpu
__NV_PRIME_RENDER_OFFLOAD=1 __GLX_VENDOR_LIBRARY_NAME=nvidia __VK_LAYER_NV_optimus=NVIDIA_only
# Then hit save

# -- Cool Apps (optional) --
yay -S alacritty
yay -S dolphin
yay -S google-chrome
yay -S visual-studio-code-bin
yay -S gcc
yay -S gpp
yay -S nasm
yay -S python3
yay -S nodejs
yay -S gdb
yay -S git
yay -S bless
yay -S vlc
yay -S kdenlive
yay -S audacity
yay -S discord
yay -S featherpad
yay -S unzip
yay -S zip
yay -S minecraft-launcher
yay -S firefox
yay -S wireshark-qt
yay -S obs-studio
yay -S ffmpeg
yay -S libreoffice
yay -S yt-dlp
# And setup the multilib x86-32 arch repo
su root
echo -e "" >> /etc/pacman.conf
echo -e "[multilib]" >> /etc/pacman.conf
echo -e "Include = /etc/pacman.d/mirrorlist" >> /etc/pacman.conf
exit
yay -Sy
# Then install packages which are in multilib
yay -S steam
yay -S wine wine-mono

jetbrains stuff
"""