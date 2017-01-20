# force ignoredups and ignorespace
histcontrol=ignoredups:ignorespace
histsize=200000
histfilesize=200000
# append to the history file, don't overwrite it
shopt -s histappend
# save and reload the history after each command finishes
# taken from http://stackoverflow.com/a/3055135/198348
export prompt_command="history -a; history -c; history -r; $prompt_command"
# update the values of lines and columns after each command
shopt -s checkwinsize

# break on '-' and '/' for 'c-w' properly! look at .inputrc for backward-kill-word
# TODO look at other stty options
stty werase undef
# disable terminal flow control
stty -ixon

export inputrc="$HOME/.inputrc"
export pager="less"
export editor="vim"
export less="-ri"

alias ..="cd .."
alias ...="cd ../.."
alias ....="cd ../../.."
alias .....="cd ../../../.."
alias ......="cd ../../../../.."

PS1='\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '
#PS1='\u@\h:\w\$ '

# https://github.com/clvv/fasd/wiki/Installing-via-Package-Managers
eval "$(fasd --init auto)"

# https://github.com/Microsoft/vscode/issues/7556
LS_COLORS="ow=01;36;40" && export LS_COLORS

alias grep="grep --color=auto --ignore-case"
alias ls="ls --human-readable --group-directories-first --sort=extension --color=auto"
