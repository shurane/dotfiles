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

To source env variables:

```bash
# https://stackoverflow.com/questions/19331497/set-environment-variables-from-file-of-key-value-pairs
set -a; source ~/dotfiles/systemd/.env; set +a

# or 
env $(cat .env | xargs) withings-sync
```
