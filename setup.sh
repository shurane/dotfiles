#!/usr/bin/env bash

mkdir -p $HOME/bin
mkdir -p $HOME/projects-vanilla
mkdir -p $HOME/projects

DESKTOP="${DESKTOP:=0}"
DEPLOY="${DEPLOY:=0}"
LATEST_VIM="${LATEST_VIM:=0}"

sudo apt-add-repository -y ppa:synapse-core/testing
sudo apt-add-repository -y ppa:ubuntu-mozilla-daily/firefox-aurora
sudo apt-add-repository -y ppa:videolan/master-daily
sudo apt-add-repository -y ppa:plt/racket
sudo apt-add-repository -y ppa:pi-rho/dev
sudo apt-add-repository -y ppa:teward/znc-staging-trusty+
sudo apt-get update
sudo apt-get install -y git mercurial build-essential vim-gtk emacs tmux ncdu \
    lftp curl elinks cloc autossh feh htop rsync rlwrap virtualbox postgresql \
    postgresql-client python-dev exuberant-ctags acpi mosh openssh-server ranger \
    tig tree plt-racket

if [ $DESKTOP -eq 1 ]; then
    sudo apt-get -y install synapse pinta mupdf mplayer vlc firefox flashplugin-installer
fi 

if [ $LATEST_VIM -eq 1]; then
    sudo apt-get -y install vim-gtk
fi

(
    cd $HOME/projects-vanilla/

    ( #fasd
        git clone https://github.com/clvv/fasd.git; (cd fasd; git fetch; git reset --hard origin/master)
        cd fasd
        PREFIX=$HOME make install
    )

    ( #gist, github, git-extras, git-ignore, gitsh
        git clone https://github.com/defunkt/gist.git
        git clone https://github.com/github/hub.git
        git clone https://github.com/visionmedia/git-extras.git
        git clone https://github.com/github/gitignore.git
        git clone https://github.com/thoughtbot/gitsh.git
    )

    ( #java, clojure, maven, leiningen
        git clone https://github.com/technomancy/leiningen.git; ( cd leiningen; git fetch; git reset --hard origin/master)
        git clone https://github.com/flexiondotorg/oab-java6.git; ( cd oab-java6.git; git fetch; git reset --hard origin/master)
    )

    ( #zsh
        git clone https://github.com/zsh-users/zsh.git; ( cd zsh; git fetch ; git reset --hard origin/master)
        git clone https://github.com/zsh-users/antigen.git; ( cd antigen; git fetch ; git reset --hard origin/master)
        cd zsh
        git checkout tags/zsh-5.0.5
    )

    ( #Node.js
        git clone https://github.com/ddopson/underscore-cli.git
        git clone https://github.com/creationix/nvm.git $HOME/.nvm
        source $HOME/.nvm/nvm.sh
        # TODO
        #nvm install 0.10
        #nvm alias default 0.10
        #nvm use 0.10
        #npm install -g http-server underscore-cli bower supervisor pm2
    )

    ( #TODO throwaway ruby, perl, python
        echo "TODO"
    )

    ( #ack
        # should be https
        # instructions from http://beyondgrep.com/install/
        curl http://beyondgrep.com/ack-2.12-single-file > ~/bin/ack && chmod 0755 ~/bin/ack
    )

)

( #vim
    git clone https://github.com/Shougo/neobundle.vim $HOME/.vim/bundle/neobundle.vim; (cd $HOME/.vim/bundle/neobundle.vim; git fetch; git reset --hard origin/master)
    #git clone https://github.com/gmarik/vundle.git $HOME/.vim/bundle/vundle
    vim +NeoBundleInstall! +qall
)

( #dotfiles
    if [ $DEPLOY -eq 1 ]; then
        git clone https://github.com/shurane/dotfiles.git $HOME/dotfiles
        cd $HOME/dotfiles
        for elem in ".bashrc" ".pathrc" ".loadrc" ".bash_aliases" ".vimrc" ".tmux.conf" ".zshrc" ".ackrc" ".inputrc" ".gitconfig"; do
            rm $HOME/$elem
            ln -s $(readlink -f $elem) $HOME/
        done
    fi
)

source $HOME/.bashrc
