How to register:

```bash
# https://github.com/jaroslawhartman/withings-sync
pipx install withings-sync
touch $HOME/dotfiles/systemd/.env
sudo ln -s $HOME/dotfiles/systemd/* /etc/systemd/system/
# https://askubuntu.com/questions/1083537/how-do-i-properly-install-a-systemd-timer-and-service
systemctl enable --now withings-garmin-sync.timer
sudo systemctl status withings-garmin-sync.service withings-garmin-sync.timer
```
