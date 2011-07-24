# Path to your oh-my-zsh configuration.
export ZSH=$HOME/.oh-my-zsh
export EDITOR=vim

# setup for virtualenvwrapper and pip
export WORKON_HOME=$HOME/projects/envs
export PIP_VIRTUALENV_BASE=$WORKON_HOME
export PIP_RESPECT_VIRTUALENV=true

# Set name of the theme to load.
# Look in ~/.oh-my-zsh/themes/
# Optionally, if you set this to "random", it'll load a random theme each
# time that oh-my-zsh is loaded.

export ZSH_THEME="unt"
export DISABLE_AUTO_UPDATE="true"     # Comment this out to disable weekly auto-update checks
export DISABLE_AUTO_TITLE="true"        # Uncomment following line if you want to disable autosetting terminal title.

export HISTSIZE=20000

# Which plugins would you like to load? (plugins can be found in ~/.oh-my-zsh/plugins/*)
# Example format: plugins=(rails git textmate ruby lighthouse)
plugins=(git)

source $ZSH/oh-my-zsh.sh

# Source aliases from .bash_aliases (they work on both)
source $HOME/.bash_aliases

# Customize to your needs...
#export PATH=/home/shoerain/bin:/var/lib/gems/1.8/bin:/home/shoerain/bin:/var/lib/gems/1.8/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games

if command -v "virtualenvwrapper.sh" >/dev/null; then
    . /usr/local/bin/virtualenvwrapper.sh >&/dev/null
fi

if [ -f $HOME/.bash_aliases ]; then
    . $HOME/.bash_aliases
fi

#setopt autopushd
setopt pushdignoredups
setopt histignorealldups
setopt incappendhistory
setopt rmstarwait
setopt noclobber
setopt autocontinue
