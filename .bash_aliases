# enable color support of ls and also add handy aliases
# TODO check if this is system-specific
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
alias a="ack"
#this is for ubuntu, where ack is installed as 'ack-grep'
if command -v "ack-grep" 2>&1 >/dev/null; then
    alias ack="ack-grep"
fi
alias v="vim"
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
alias less="less -R"

#I think these are zsh functions, double check!

nullbg(){ 
    "$@" >&/dev/null & 
}
findfile(){ 
    find . -iregex ".*$1.*" -type f -print; 
}
manfind() { 
    man "$1" | less -i -p "$2" 
}
