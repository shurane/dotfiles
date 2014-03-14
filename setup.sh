#!/usr/bin/env bash

mkdir -p $HOME/bin
mkdir -p $HOME/projects-vanilla
mkdir -p $HOME/projects

sudo apt-add-repository -y ppa:ubuntu-mozilla-daily/firefox-aurora
sudo apt-get update
sudo apt-get install -y git mercurial build-essential vim-gtk \
    emacs tmux ncdu lftp curl elinks cloc autossh feh htop rsync rlwrap \
    virtualbox postgresql postgresql-client python-dev firefox flashplugin-installer

(
    cd $HOME/projects-vanilla/

    ( #fasd
        git clone https://github.com/clvv/fasd.git
        cd fasd
        PREFIX=$HOME make install
    )

    ( #gist, github, git-extras, git-ignore
        git clone https://github.com/defunkt/gist.git
        git clone https://github.com/github/hub.git
        git clone https://github.com/visionmedia/git-extras.git
        git clone https://github.com/github/gitignore.git
    )

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
        #npm install -g http-server underscore-cli bower supervisor
    )

    ( #TODO throwaway ruby, perl, python
        echo "TODO"
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
