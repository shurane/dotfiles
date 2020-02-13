# If not running interactively, don't do anything
case $- in
    *i*) ;;
      *) return;;
esac

# force ignoredups and ignorespace
HISTCONTROL=ignoredups:ignorespace
HISTSIZE=200000
HISTFILESIZE=200000
# append to the history file, don't overwrite it
shopt -s histappend
# save and reload the history after each command finishes
# taken from http://stackoverflow.com/a/3055135/198348
export PROMPT_COMMAND="history -a; history -c; history -r; $prompt_command"
# update the values of lines and columns after each command
shopt -s checkwinsize

# using `tty -s` because of https://askubuntu.com/a/918479/22073
# break on '-' and '/' for 'c-w' properly! look at .inputrc for backward-kill-word
# TODO look at other stty options
tty -s && stty werase undef
# disable terminal flow control
tty -s && stty -ixon

# enable programmable completion features (you don't need to enable
# this, if it's already enabled in /etc/bash.bashrc and /etc/profile
# sources /etc/bash.bashrc).
if ! shopt -oq posix; then
  if [ -f /usr/share/bash-completion/bash_completion ]; then
    . /usr/share/bash-completion/bash_completion
  elif [ -f /etc/bash_completion ]; then
    . /etc/bash_completion
  fi
fi

export INPUTRC="$HOME/.inputrc"
export PAGER="less"
export EDITOR="vim"
export LESS="-FRXI"

alias ..="cd .."
alias ...="cd ../.."
alias ....="cd ../../.."
alias .....="cd ../../../.."
alias ......="cd ../../../../.."

PS1='\[\033[01;32m\]\u@\h\[\033[00m\]:\[\033[01;34m\]\w\[\033[00m\]\$ '
#PS1='\u@\h:\w\$ '

# https://github.com/clvv/fasd/wiki/Installing-via-Package-Managers
test -x fasd && eval "$(fasd --init auto)"
test -r ~/.dircolors && eval "$(dircolors -b ~/.dircolors)"

alias grep="grep --color=auto --ignore-case"
alias ls="ls --human-readable --group-directories-first --sort=extension --color=auto"

# https://github.com/BurntSushi/ripgrep/issues/86#issuecomment-331718946
rgl() { rg -i -p -M 500 "$@" | less -XFR }
rgf() { rg --files | rg -i -p -M 500 "$@" | less -XFR }
rglc() { rg -i -p -M 500 --type csharp "$@" | less -XFR }

# https://github.com/junegunn/fzf#respecting-gitignore
export FZF_DEFAULT_COMMAND='
 (git ls-tree -r --name-only HEAD ||
  find . -path "*/\.*" -prune -o -type f -print -o -type l -print |
  sed s/^..//) 2> /dev/null'
