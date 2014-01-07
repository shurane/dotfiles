# Lines configured by zsh-newuser-install
export HISTFILE=~/.histfile
export HISTSIZE=100000
export SAVEHIST=100000
export PATH=$HOME/bin:$PATH
export PROMPT="%n@%m:%20<...<%d%<<%% "
export EDITOR=vim
# End of lines configured by zsh-newuser-install
# The following lines were added by compinstall
zstyle :compinstall filename '/home/ehtesh/.zshrc'

source $HOME/.pathrc

autoload -Uz compinit
compinit
# End of lines added by compinstall


#TODO double check these options?
unsetopt beep
setopt autopushd
setopt pushdignoredups
setopt histignorealldups
setopt inc_append_history
setopt share_history
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
bindkey -M viins '^?' backward-delete-char
bindkey -M viins '^h' backward-delete-char
bindkey -M viins '^R' history-incremental-search-backward
bindkey -M viins '^S' history-incremental-search-forward
bindkey -M viins '^P' up-line-or-history
bindkey -M viins '^N' down-line-or-history
bindkey -M viins '^A' beginning-of-line
bindkey -M viins '^E' end-of-line
bindkey -M viins 'b' vi-backward-word
bindkey -M viins 'f' vi-forward-word

# }}}

# antigen.zsh stuff: https://github.com/zsh-users/antigen

source $HOME/projects-vanilla/antigen/antigen.zsh

antigen use oh-my-zsh
antigen bundle zsh-users/zsh-syntax-highlighting
antigen bundle zsh-users/zsh-completions src
antigen bundle git
#antigen bundle pip
#antigen bundle lein
#antigen bundle command-not-found
#antigen bundle rsync
antigen bundle python
#antigen bundle virtualenvwrapper
#antigen bundle node
#antigen bundle npm
#antigen bundle history
#antigen bundle tmux
#antigen bundle vundle
#antigen bundle sprunge
antigen theme alanpeabody

antigen apply

source ~/.loadrc
