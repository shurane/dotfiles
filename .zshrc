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
[[ -f $HOME/.autojump ]] && source $HOME/.autojump
command -v virtualenvwrapper.sh >/dev/null && source virtualenvwrapper.sh #>&/dev/null

setopt autopushd
setopt pushdignoredups
setopt histignorealldups
setopt incappendhistory
setopt rmstarwait
setopt noclobber
setopt autocontinue

source $ZSH/oh-my-zsh.sh

#autojump
#Copyright Joel Schaerer 2008, 2009
#This file is part of autojump

#autojump is free software: you can redistribute it and/or modify
#it under the terms of the GNU General Public License as published by
#the Free Software Foundation, either version 3 of the License, or
#(at your option) any later version.
#
#autojump is distributed in the hope that it will be useful,
#but WITHOUT ANY WARRANTY; without even the implied warranty of
#MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#GNU General Public License for more details.
#
#You should have received a copy of the GNU General Public License
#along with autojump.  If not, see <http://www.gnu.org/licenses/>.

#local data_dir=${XDG_DATA_HOME:-$([ -e ~/.local/share ] && echo ~/.local/share || echo ~)}
local data_dir=$([ -e ~/.local/share ] && echo ~/.local/share || echo ~)
if [[ "$data_dir" = "${HOME}" ]]
then
    export AUTOJUMP_DATA_DIR=${data_dir}
else
    export AUTOJUMP_DATA_DIR=${data_dir}/autojump
fi
if [ ! -e "${AUTOJUMP_DATA_DIR}" ]
then
    mkdir "${AUTOJUMP_DATA_DIR}"
    mv ~/.autojump_py "${AUTOJUMP_DATA_DIR}/autojump_py" 2>>/dev/null #migration
    mv ~/.autojump_py.bak "${AUTOJUMP_DATA_DIR}/autojump_py.bak" 2>>/dev/null
    mv ~/.autojump_errors "${AUTOJUMP_DATA_DIR}/autojump_errors" 2>>/dev/null
fi

function autojump_preexec() {
    { (autojump -a "$(pwd -P)"&)>/dev/null 2>>|${AUTOJUMP_DATA_DIR}/autojump_errors ; } 2>/dev/null
}

typeset -ga preexec_functions
preexec_functions+=autojump_preexec

alias jumpstat="autojump --stat"

function j { local new_path="$(autojump $@)";if [ -n "$new_path" ]; then echo -e "\\033[31m${new_path}\\033[0m"; cd "$new_path";else false; fi }
