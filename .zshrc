export EDITOR=vim
export HISTSIZE=20000

# setup for virtualenvwrapper and pip
export WORKON_HOME=$HOME/projects/envs
export PIP_VIRTUALENV_BASE=$WORKON_HOME
export PIP_RESPECT_VIRTUALENV=true

# Oh-My-Zsh {{{
#
# Path to your oh-my-zsh configuration.
export ZSH=$HOME/.oh-my-zsh
# Set name of the theme to load.
# Look in ~/.oh-my-zsh/themes/
# Optionally, if you set this to "random", it'll load a random theme each
# time that oh-my-zsh is loaded.
export ZSH_THEME="unt"

export DISABLE_AUTO_UPDATE="true"     # Comment this out to disable weekly auto-update checks
export DISABLE_AUTO_TITLE="true"        # Uncomment following line if you want to disable autosetting terminal title.

# zsh-syntax highlighting.. maybe
#ZSH_HIGHLIGHT_HIGHLIGHTERS=(main brackets pattern cursor)
#
# Which plugins would you like to load? (plugins can be found in ~/.oh-my-zsh/plugins/*)
# Example format: plugins=(rails git textmate ruby lighthouse)
plugins=(git) #zsh-syntax-highlighting)

source $ZSH/oh-my-zsh.sh

#}}}

# Prompt, using oh-my-zsh colors {{{

function zle-line-init zle-keymap-select {
    MODE="${${KEYMAP/vicmd/-N-}/(main|viins)/-I-}"
    RPS1="%{$fg[cyan]%}%1c %{$reset_color%}$MODE %{$fg_bold[green]%}% $USER@$HOST% %{$reset_color%}"
    RPS2=$RPS1
    zle reset-prompt
}

zle -N zle-keymap-select
zle -N zle-line-init

# this stuff is way more confusing than it needs be
#[ -n "$TMUX" ] && tmux setenv TMUXPWD_$(tmux display -p "#I") $PWD
PROMPT='%{$fg_bold[red]%}➜%{$fg_bold[blue]%}$(git_prompt_info)%{$fg_bold[blue]%} %{$reset_color%}'
#RPROMPT='%{$fg[cyan]%}%1c %{$fg_bold[green]%}% $USER@$HOST% %{$reset_color%}'

# }}}


# Customize to your needs...
export PATH=$HOME/bin:/var/lib/gems/1.8/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/usr/games

[[ -f $HOME/.pythonbrew/etc/bashrc ]] && source $HOME/.pythonbrew/etc/bashrc
[[ -f $HOME/.rvm/scripts/rvm ]] && source $HOME/.rvm/scripts/rvm
[[ -f /etc/profile.d/autojump.zsh ]] && source /etc/profile.d/autojump.zsh
#command -v virtualenvwrapper.sh >/dev/null && source virtualenvwrapper.sh #>&/dev/null


#TODO double check these options?
setopt autopushd
setopt pushdignoredups
setopt histignorealldups
setopt incappendhistory
setopt rmstarwait
setopt noclobber
setopt autocontinue
stty -ixon

#Vim-mode emulation, with some emacs-style readline to boot
#check zshzle for more options {{{
bindkey -v
bindkey -M viins 'jj' vi-cmd-mode
bindkey -M viins '^K' kill-line
bindkey -M viins '^U' backward-kill-line
bindkey -M viins '^W' backward-kill-word
bindkey -M viins '^R' history-incremental-search-backward
bindkey -M viins '^S' history-incremental-search-forward
bindkey -M viins '^P' up-line-or-history
bindkey -M viins '^N' down-line-or-history
bindkey -M viins '^A' beginning-of-line
bindkey -M viins '^E' end-of-line
#bindkey -M viins '^[B' vi-backward-word
#bindkey -M viins '^[F' vi-forward-word

# }}}

[[ -f $HOME/.bash_aliases ]] && source $HOME/.bash_aliases
