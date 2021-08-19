# https://github.com/nodesource/distributions/blob/master/README.md
curl -sL https://deb.nodesource.com/setup_14.x | sudo -E bash -

# third party binaries, installed manually
: << 'END'
- neovim https://github.com/neovim/neovim/wiki/Installing-Neovim#appimage-universal-linux-package
- ripgrep https://github.com/BurntSushi/ripgrep#installation
- scc https://github.com/boyter/scc
END

sudo apt install -y tmux mosh tree rsync ncdu htop fasd p7zip-full
# for programming
sudo apt -y install postgresql postgresql-client
sudo apt install -y nodejs python3-pip tig

sudo pip3 install ipython requests flask pylint black

sudo npm install -g http-server serve nodemon
sudo npm install -g typescript ts-node js-beautify eslint rimraf
sudo npm install -g npm-check tldr #optional

