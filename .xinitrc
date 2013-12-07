#!/bin/sh
#
# ~/.xinitrc
#
# Executed by startx (run your window manager from here)

if [ -d /etc/X11/xinit/xinitrc.d ]; then
  for f in /etc/X11/xinit/xinitrc.d/*; do
    [ -x "$f" ] && . "$f"
  done
  unset f
fi

# https://wiki.archlinux.org/index.php/Systemd/User
/usr/lib/systemd/systemd --user &

xset +fp /usr/share/fonts/local
xset fp rehash
xset b off

# https://wiki.archlinux.org/index.php/Xinitrc
xrdb -merge ~/.Xresources
xmodmap ~/.Xmodmap
xsetroot -cursor_name left_ptr &
pgrep -x synapse || synapse &
xautolock -time 5 -locker "i3lock --color=0f0f0f" &

# exec gnome-session
# exec startkde
# exec startxfce4
exec startfluxbox
# exec startlxde
# exec mate-session
