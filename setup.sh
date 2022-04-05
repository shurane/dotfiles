
# third party binaries, installed manually
: << END
- neovim https://github.com/neovim/neovim/wiki/Installing-Neovim#appimage-universal-linux-package
- ripgrep https://github.com/BurntSushi/ripgrep#installation
- scc https://github.com/boyter/scc
- sharkdp/fd  https://github.com/sharkdp/fd (find alternative)
- sharkdp/bat https://github.com/sharkdp/bat (cat alternative with syntax highlighting)
- sharkdp/vivid https://github.com/sharkdp/vivid (LS_COLORS for different file extensions)
- sharkdp/diskus https://github.com/sharkdp/diskus (du -sh alternative that's parallelized)
- dandavision/delta https://github.com/dandavison/delta
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

# clang, gcc
wget -O - https://apt.llvm.org/llvm-snapshot.gpg.key | sudo apt-key add -
sudo tee /etc/apt/sources.list.d/llvm.list << END
# 14, https://apt.llvm.org/
deb http://apt.llvm.org/focal/ llvm-toolchain-focal-14 main
deb-src http://apt.llvm.org/focal/ llvm-toolchain-focal-14 main
END
# https://launchpad.net/~ubuntu-toolchain-r/+archive/ubuntu/test
sudo add-apt-repository -y ppa:ubuntu-toolchain-r/test

sudo apt update && sudo apt install clang-14 clangd-14 gcc-11
# https://gist.github.com/mpusz/886a2a68742f1f63820d6b1425866791
sudo update-alternatives --install /usr/bin/clang clang /usr/bin/clang-14 140 --slave /usr/bin/clang++ clang++ /usr/bin/clang++-14
sudo update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-11 110 --slave /usr/bin/g++ g++ /usr/bin/g++-11

# https://github.com/nodesource/distributions/blob/master/README.md
curl -sL https://deb.nodesource.com/setup_16.x | sudo -E bash -

sudo apt install -y nodejs
sudo npm install -g http-server serve nodemon
sudo npm install -g typescript ts-node js-beautify eslint rimraf
sudo npm install -g npm-check tldr #optional

