# enable color support of ls and also add handy aliases
# TODO check if this is system-specific
if [ "$TERM" != "dumb" ]; then
    [ -e "$HOME/.dircolors" ] && DIR_COLORS="$HOME/.dircolors"
    [ -e "$DIR_COLORS" ] || DIR_COLORS=""
    eval "`dircolors -b $DIR_COLORS`"
fi

# Random useful functions {{{
#nullbg(){ 
    #"$@" &>/dev/null & 
#}
#findfile(){ 
    #find . -iregex ".*$1.*" -type f -print; 
#}
manfind() { 
    man "$1" | less -i -p "$2" 
}
# }}}


alias ..="cd .."
alias ...="cd ../.."
alias ....="cd ../../.."
alias .....="cd ../../../.."
alias ......="cd ../../../../.."

alias reds="redshift -l 40.85:-73.88 -m vidmode -r -t 3600:3600 &"
alias a="ack"
#this is for ubuntu, where ack is installed as 'ack-grep'
if command -v "ack-grep" 2>&1 >/dev/null; then
    alias ack="ack-grep"
fi

alias grep="grep --color=auto --ignore-case"
alias v="vim"
alias ls="ls --human-readable --group-directories-first --sort=extension --color=auto"
alias ll="ls --human-readable --group-directories-first --sort=extension --color=auto --almost-all --format=long"
alias tmux="tmux -2"
alias less="less -R"
alias t='python ~/bin/t --task-dir ~/Dropbox/tasks --list tasks'
alias task='python ~/bin/t'
alias chrome="google-chrome"
alias startx='startx'
# let's try this out. http://superuser.com/a/333740/45927
alias ssh='ssh'
