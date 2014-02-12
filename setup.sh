#!/usr/bin/env bash

mkdir -p $HOME/bin
mkdir -p $HOME/projects-vanilla
mkdir -p $HOME/projects

sudo apt-get install -y squid-deb-proxy git mercurial build-essential vim-gtk \
    emacs tmux ncdu lftp curl elinks cloc autossh feh htop rsync rlwrap st \
    virtualbox postgresql postgresql-client

(
    cd $HOME/projects-vanilla/
    git clone https://github.com/clvv/fasd.git

    ( #java, clojure, maven, leiningen
        git clone https://github.com/technomancy/leiningen.git
        git clone https://github.com/flexiondotorg/oab-java6.git
    )

    ( #zsh
        git clone https://github.com/zsh-users/zsh.git
        git clone https://github.com/zsh-users/antigen.git
        cd zsh
        git checkout tags/zsh-5.0.5
    )

    ( #Node.js
        git clone https://github.com/ddopson/underscore-cli.git
        git clone https://github.com/creationix/nvm.git $HOME/.nvm
        source $HOME/.nvm/nvm.sh
        # TODO
        nvm install 0.10
        nvm alias default 0.10
        nvm use 0.10
        npm install -g http-server underscore-cli bower supervisor
    )
)

( #dotfiles
    git clone https://github.com/shurane/dotfiles.git $HOME/dotfiles
    cd $HOME/dotfiles
    for elem in ".bashrc" ".pathrc" ".loadrc" ".bash_aliases" ".vimrc" ".tmux.conf" ".zshrc" ".ackrc" ".inputrc" ".gitconfig"; do
        rm $HOME/$elem
        ln -s $(readlink -f $elem) $HOME/
    done
)

( #vim
    git clone https://github.com/gmarik/vundle.git $HOME/.vim/bundle/vundle
    vim +BundleInstall +qall
)

source $HOME/.bashrc
