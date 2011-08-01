# enable color support of ls and also add handy aliases
if [ "$TERM" != "dumb" ]; then
    [ -e "$HOME/.dircolors" ] && DIR_COLORS="$HOME/.dircolors"
    [ -e "$DIR_COLORS" ] || DIR_COLORS=""
    eval "`dircolors -b $DIR_COLORS`"
fi

alias ..="cd .."
alias ...="cd ../.."
alias ....="cd ../../.."
alias .....="cd ../../../.."

alias po="popd"
alias pu="pushd"
alias ack="ack-grep"
#sd = sizedir
alias sd="du -ch . | tail -n 1"
alias df="df -ch"
alias egrep="egrep --color=auto"
alias fgrep="fgrep --color=auto"
alias gopen="gnome-open"
alias grep="grep --color=auto --ignore-case"
alias info="info --vi-keys"
alias ls="ls --human-readable --group-directories-first --sort=extension --color=auto"
alias ll="ls --human-readable --group-directories-first --sort=extension --color=auto --almost-all --format=long"
alias tmux="tmux -2"

nullbg(){ "$@" >&/dev/null & }

