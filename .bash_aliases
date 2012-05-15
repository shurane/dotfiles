# enable color support of ls and also add handy aliases
# TODO check if this is system-specific
if [ "$TERM" != "dumb" ]; then
    [ -e "$HOME/.dircolors" ] && DIR_COLORS="$HOME/.dircolors"
    [ -e "$DIR_COLORS" ] || DIR_COLORS=""
    eval "`dircolors -b $DIR_COLORS`"
fi

#I think these are zsh functions, double check!
# Random useful functions {{{
nullbg(){ 
    "$@" >&/dev/null & 
}
findfile(){ 
    find . -iregex ".*$1.*" -type f -print; 
}
manfind() { 
    man "$1" | less -i -p "$2" 
}
# }}}

# stolen from http://unix.stackexchange.com/a/4291/11839 {{{
# prepended by 'se' to not conflict with default namespace
# TODO it would be cool if this ignored duplicate directories
# TODO this doesn't work with GNU make for some reason
se_pushd()
{
    if [ $# -eq 0 ]; then
        DIR="${HOME}"
    else
        DIR="$1"
    fi

    builtin pushd "${DIR}" > /dev/null
    echo -n "DIRSTACK: "
    dirs
}

se_pushd_builtin()
{
  builtin pushd > /dev/null
  echo -n "DIRSTACK: "
  dirs
}

se_popd()
{
  builtin popd > /dev/null
  echo -n "DIRSTACK: "
  dirs
}

#alias cd='se_pushd'
alias cdd='se_pushd'
#alias back='se_popd'
alias baa='se_popd'
#alias ba='se_popd'
alias flip='se_pushd_builtin'
alias po="se_popd"
alias pu="se_pushd"

# }}}

alias ..="cd .."
alias ...="cd ../.."
alias ....="cd ../../.."
alias .....="cd ../../../.."
alias ......="cd ../../../../.."

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

