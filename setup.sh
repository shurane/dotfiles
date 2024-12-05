
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
- zoxide (successor to fasd, autojump) https://github.com/ajeetdsouza/zoxide
- broot https://github.com/Canop/broot - file manager
- bkt https://github.com/dimo414/bkt (for caching command output)
- plt/racket
- rustup
- ghcup
- ziglang
END

sudo apt install -y tmux mosh tree rsync ncdu htop zoxide tig p7zip-full

# for programming
sudo apt install -y postgresql postgresql-client

# python 3.10 or maybe use pyenv?
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt update && sudo apt install python3.10

# python packages
sudo pip3 install pandas numpy scipy
sudo pip3 install ipython bpython requests flask pylint black pep8 rope pyright

# clang, gcc
wget -qO- https://apt.llvm.org/llvm-snapshot.gpg.key | sudo tee /etc/apt/trusted.gpg.d/apt.llvm.org.asc
sudo tee /etc/apt/sources.list.d/llvm.list << END
# https://apt.llvm.org/
deb http://apt.llvm.org/noble/ llvm-toolchain-noble main
deb-src http://apt.llvm.org/noble/ llvm-toolchain-noble main
END
# https://launchpad.net/~ubuntu-toolchain-r/+archive/ubuntu/test
sudo add-apt-repository -y ppa:ubuntu-toolchain-r/test
# related to having a c compiler
# https://github.com/microsoft/WSL/issues/5663 - "/sbin/ldconfig.real: /usr/lib/wsl/lib/libcuda.so.1 is not a symbolic link"

sudo apt update && sudo apt install clang clangd clang-format gcc-13 g++-13
# https://gist.github.com/mpusz/886a2a68742f1f63820d6b1425866791
#sudo update-alternatives --install /usr/bin/clang clang /usr/bin/clang-18 180 --slave /usr/bin/clang++ clang++ /usr/bin/clang++-18 --slave /usr/bin/clangd clangd /usr/bin/clangd-18
sudo update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-13 130 --slave /usr/bin/g++ g++ /usr/bin/g++-13

# https://github.com/nodesource/distributions/blob/master/README.md
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -

sudo apt install -y nodejs
sudo npm install -g http-server serve nodemon
sudo npm install -g typescript ts-node js-beautify eslint
#sudo npm update -g # update global packages
