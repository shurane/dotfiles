# enable color support of ls and also add handy aliases
if [ "$TERM" != "dumb" ]; then
    [ -e "$HOME/.dircolors" ] && DIR_COLORS="$HOME/.dircolors"
    [ -e "$DIR_COLORS" ] || DIR_COLORS=""
    eval "`dircolors -b $DIR_COLORS`"
fi


alias ..='cd ..'
alias ...='cd ../..'
alias ....='cd ../../..'
alias .....='cd ../../../..'

alias ack='ack-grep'
alias attach='screen -RaAD'
alias df='df -h'
alias egrep='egrep --color=auto'
alias fgrep='fgrep --color=auto'
alias gopen='gnome-open'
alias grep='grep --color=auto --ignore-case'
alias info='info --vi-keys'
alias ls='ls --human-readable --group-directories-first --sort=extension --color=auto'
alias ll='ls --human-readable --group-directories-first --sort=extension --color=auto --almost-all --format=long'
alias tmux='tmux -2'

