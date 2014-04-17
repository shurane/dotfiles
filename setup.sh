#!/usr/bin/env bash

mkdir -p $HOME/bin
mkdir -p $HOME/projects-vanilla
mkdir -p $HOME/projects

DESKTOP="${DESKTOP:=0}"

sudo apt-get update
sudo apt-get install -y git mercurial build-essential vim-gtk emacs tmux ncdu \
    lftp curl elinks cloc autossh feh htop rsync rlwrap virtualbox postgresql \
    postgresql-client python-dev exuberant-ctags acpi mosh openssh-server ranger \
    tig tree 

if [ $DESKTOP -eq 1 ]; then
    sudo add-apt-repository -y ppa:synapse-core/testing
    sudo apt-add-repository -y ppa:ubuntu-mozilla-daily/firefox-aurora
    sudo apt-get install -y synapse pinta mupdf mplayer vlc vlc-nox firefox flashplugin-installer
fi 

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

    ( #ack
        # should be https
        # instructions from http://beyondgrep.com/install/
        curl http://beyondgrep.com/ack-2.12-single-file > ~/bin/ack && chmod 0755 !#:3 
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
    git clone https://github.com/Shougo/neobundle.vim ~/.vim/bundle/neobundle.vim
    #git clone https://github.com/gmarik/vundle.git $HOME/.vim/bundle/vundle
    #vim +BundleInstall +qall
)

source $HOME/.bashrc
