
```bash
# How to register:
# https://github.com/jaroslawhartman/withings-sync
uv tool install withings-sync
touch $HOME/dotfiles/systemd/.env
sudo ln -s $HOME/dotfiles/systemd/{withings-garmin-sync.service,withings-garmin-sync.timer} /etc/systemd/system/
# https://askubuntu.com/questions/1083537/how-do-i-properly-install-a-systemd-timer-and-service
systemctl enable --now withings-garmin-sync.timer
systemctl status withings-garmin-sync.service withings-garmin-sync.timer

# To source env variables:
# https://stackoverflow.com/questions/19331497/set-environment-variables-from-file-of-key-value-pairs
set -a; source ~/dotfiles/systemd/.env; set +a
# or
env $(cat .env | xargs) withings-sync
```

----

That was before, but I'm setting it up again with qui:

```bash
# create qui user
sudo useradd -r -s /usr/bin/nologin -m -d /var/lib/qui qui
# symlink systemd unit
sudo ln -s $HOME/dotfiles/systemd/qui.service /etc/systemd/system/qui.service
# copy config file
sudo systemctl stop qui.service
sudo cp $HOME/dotfiles/systemd/qui/config.toml /var/lib/qui/config.toml
sudo chown qui:qui /var/lib/qui/config.toml
# reload
# first time to enable running on boot: sudo systemctl enable --now qui.service
sudo systemctl daemon-reload
sudo systemctl start qui.service
# check status:
systemctl status qui.service
journalctl -u qui.service -f
# list users on qui:
sudo -u qui sqlite3 /var/lib/qui/qui.db "SELECT username FROM user;"
```

Arch update checks download pending packages without installing them:

```bash
sudo pacman -S pacman-contrib
sudo ln -s "$HOME/dotfiles/systemd/arch-checkupdates.service" /etc/systemd/system/
sudo ln -s "$HOME/dotfiles/systemd/arch-checkupdates.timer" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now arch-checkupdates.timer
systemctl list-timers arch-checkupdates.timer
journalctl -u arch-checkupdates.service
```

Install downloaded updates manually after reviewing Arch news and package changes:

```bash
sudo pacman -Syu
```

Run WeeChat in a persistent tmux session, including before login:

```bash
mkdir -p ~/.config/systemd/user
ln -s ~/dotfiles/systemd/weechat.service ~/.config/systemd/user/
sudo loginctl enable-linger "$USER"
systemctl --user daemon-reload
systemctl --user enable --now weechat.service
tmux attach -t weechat
```
