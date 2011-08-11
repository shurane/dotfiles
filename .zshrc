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

# Source aliases from .bash_aliases (they work on both)
source $HOME/.bash_aliases

# Customize to your needs...
export PATH=$HOME/bin:/var/lib/gems/1.8/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games

[[ -f $HOME/.bash_aliases ]] && source $HOME/.bash_aliases
[[ -f $HOME/.pythonbrew/etc/bashrc ]] && source $HOME/.pythonbrew/etc/bashrc
[[ -f $HOME/.rvm/scripts/rvm ]] && source $HOME/.rvm/scripts/rvm

command -v virtualenvwrapper.sh >/dev/null && source virtualenvwrapper.sh >&/dev/null

setopt autopushd
setopt pushdignoredups
setopt histignorealldups
setopt incappendhistory
setopt rmstarwait
setopt noclobber
setopt autocontinue

source $ZSH/oh-my-zsh.sh
