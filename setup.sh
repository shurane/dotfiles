
# third party binaries, installed manually
: << 'END'
- neovim https://github.com/neovim/neovim/wiki/Installing-Neovim#appimage-universal-linux-package
- ripgrep https://github.com/BurntSushi/ripgrep#installation
- scc https://github.com/boyter/scc
- sharkdp/fd  https://github.com/sharkdp/fd (find alternative)
- sharkdp/bat https://github.com/sharkdp/bat (cat alternative with syntax highlighting)
- sharkdp/vivid https://github.com/sharkdp/vivid (LS_COLORS for different file extensions)
- sharkdp/diskus https://github.com/sharkdp/diskus (du -sh alternative that's parallelized)
- plt/racket
- rustup
- ghcup
- ziglang
END

sudo apt install -y tmux mosh tree rsync ncdu htop fasd tig p7zip-full

# for programming
sudo apt install -y postgresql postgresql-client

# TODO install python 3.10
sudo pip3 install ipython requests flask pylint black

# https://github.com/nodesource/distributions/blob/master/README.md
curl -sL https://deb.nodesource.com/setup_16.x | sudo -E bash -

sudo apt install -y nodejs
sudo npm install -g http-server serve nodemon
sudo npm install -g typescript ts-node js-beautify eslint rimraf
sudo npm install -g npm-check tldr #optional

